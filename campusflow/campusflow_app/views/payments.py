from decimal import Decimal, InvalidOperation

from django.db import connection, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status

from campusflow_app.models import StudentFeeInvoice, FeePayment, PaymentGatewayTransaction
from campusflow_app.payment_gateways import get_adapter_for_tenant, GatewayNotImplementedError
from tenants.models import Tenant


class CreatePaymentOrderView(APIView):
    """
    POST /payments/orders/
    Body: {"invoice_id": int, "amount": optional decimal}
    A student starts an online checkout for one of their own invoices.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        invoice_id = request.data.get("invoice_id")
        try:
            invoice = StudentFeeInvoice.objects.get(id=invoice_id)
        except StudentFeeInvoice.DoesNotExist:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        if invoice.student_id != request.user.id:
            return Response({"error": "You can only pay your own invoices."}, status=status.HTTP_403_FORBIDDEN)

        tenant = connection.tenant

        try:
            adapter = get_adapter_for_tenant(tenant)
        except GatewayNotImplementedError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        remaining = invoice.remaining_balance
        if remaining <= 0:
            return Response({"error": "This invoice is already fully paid."}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get("amount")
        try:
            amount = Decimal(str(raw_amount)) if raw_amount is not None else remaining
        except InvalidOperation:
            return Response({"error": "Invalid amount."}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= 0 or amount > remaining:
            return Response(
                {"error": f"amount must be greater than 0 and at most the remaining balance of ₹{remaining}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        convenience_fee_amount = Decimal("0.00")
        if tenant.fee_surcharge_mode == Tenant.SURCHARGE_PASS and tenant.convenience_fee_percent:
            convenience_fee_amount = (amount * tenant.convenience_fee_percent / Decimal("100")).quantize(Decimal("0.01"))
        total_amount = amount + convenience_fee_amount

        txn = PaymentGatewayTransaction.objects.create(
            invoice=invoice,
            initiated_by=request.user,
            gateway=tenant.payment_gateway_active,
            amount=amount,
            convenience_fee_amount=convenience_fee_amount,
            total_amount=total_amount,
        )

        try:
            order = adapter.create_order(
                amount=total_amount,
                currency="INR",
                receipt=f"INV-{invoice.invoice_number}-{txn.id}",
                notes={"invoice_id": str(invoice.id), "student_id": str(request.user.id)},
            )
        except Exception as exc:
            txn.status = PaymentGatewayTransaction.STATUS_FAILED
            txn.failure_reason = str(exc)
            txn.save(update_fields=["status", "failure_reason"])
            return Response({"error": "Could not create payment order. Please try again."}, status=status.HTTP_502_BAD_GATEWAY)

        txn.gateway_order_id = order["order_id"]
        txn.raw_create_response = order["raw_response"]
        txn.save(update_fields=["gateway_order_id", "raw_create_response"])

        return Response({
            "transaction_id": txn.id,
            "gateway": tenant.payment_gateway_active,
            "key_id": tenant.razorpay_key_id if tenant.payment_gateway_active == "razorpay" else None,
            "order_id": txn.gateway_order_id,
            "amount": str(amount),
            "convenience_fee_amount": str(convenience_fee_amount),
            "total_amount": str(total_amount),
            "currency": "INR",
        }, status=status.HTTP_201_CREATED)


def _mark_transaction_paid(txn: PaymentGatewayTransaction, gateway_payment_id: str):
    """Idempotently finalize a transaction: create the FeePayment receipt and update the invoice."""
    if txn.status == PaymentGatewayTransaction.STATUS_PAID:
        return txn.fee_payment if hasattr(txn, "fee_payment") else None

    with transaction.atomic():
        txn.status = PaymentGatewayTransaction.STATUS_PAID
        txn.gateway_payment_id = gateway_payment_id
        txn.save(update_fields=["status", "gateway_payment_id"])

        payment = FeePayment.objects.create(
            invoice=txn.invoice,
            amount_paid=txn.amount,
            payment_method=FeePayment.METHOD_ONLINE,
            transaction_reference=gateway_payment_id,
            gateway_transaction=txn,
            remarks=f"Paid online via {txn.gateway}.",
        )
    return payment


class VerifyPaymentView(APIView):
    """
    POST /payments/verify/
    Body: {"transaction_id": int, "razorpay_order_id": ..., "razorpay_payment_id": ..., "razorpay_signature": ...}
    Called by the frontend right after the gateway checkout widget succeeds.
    The webhook is the authoritative fallback if this never fires.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        txn_id = request.data.get("transaction_id")
        try:
            txn = PaymentGatewayTransaction.objects.select_related("invoice").get(id=txn_id)
        except PaymentGatewayTransaction.DoesNotExist:
            return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)

        if txn.initiated_by_id != request.user.id:
            return Response({"error": "Not your transaction."}, status=status.HTTP_403_FORBIDDEN)

        if txn.status == PaymentGatewayTransaction.STATUS_PAID:
            return Response({"message": "Payment already verified.", "status": txn.status}, status=status.HTTP_200_OK)

        tenant = connection.tenant
        try:
            adapter = get_adapter_for_tenant(tenant)
        except GatewayNotImplementedError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not adapter.verify_payment_signature(request.data):
            txn.status = PaymentGatewayTransaction.STATUS_FAILED
            txn.failure_reason = "Signature verification failed."
            txn.save(update_fields=["status", "failure_reason"])
            return Response({"error": "Payment verification failed."}, status=status.HTTP_400_BAD_REQUEST)

        gateway_payment_id = request.data.get("razorpay_payment_id", "")
        _mark_transaction_paid(txn, gateway_payment_id)

        invoice = txn.invoice
        return Response({
            "message": "Payment verified successfully.",
            "status": invoice.status,
            "remaining_balance": str(invoice.remaining_balance),
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class RazorpayWebhookView(APIView):
    """
    POST /payments/webhook/razorpay/
    Server-to-server confirmation from Razorpay. No user auth — the request
    is already routed to the right tenant schema by domain (CampusFlowTenantMiddleware
    runs before this view), and authenticity is established via the signature header.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        tenant = connection.tenant
        signature = request.headers.get("X-Razorpay-Signature", "")

        try:
            adapter = get_adapter_for_tenant(tenant)
        except GatewayNotImplementedError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if not tenant.razorpay_webhook_secret or not adapter.verify_webhook_signature(request.body, signature):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event = adapter.parse_webhook_event(request.data)
        gateway_order_id = event.get("gateway_order_id")
        if not gateway_order_id:
            return Response(status=status.HTTP_200_OK)

        try:
            txn = PaymentGatewayTransaction.objects.select_related("invoice").get(gateway_order_id=gateway_order_id)
        except PaymentGatewayTransaction.DoesNotExist:
            return Response(status=status.HTTP_200_OK)

        txn.raw_webhook_payload = request.data
        txn.save(update_fields=["raw_webhook_payload"])

        if event.get("status") == "paid":
            _mark_transaction_paid(txn, event.get("gateway_payment_id", ""))
        elif event.get("status") == "failed" and txn.status != PaymentGatewayTransaction.STATUS_PAID:
            txn.status = PaymentGatewayTransaction.STATUS_FAILED
            txn.failure_reason = f"Webhook event: {event.get('event_type')}"
            txn.save(update_fields=["status", "failure_reason"])

        return Response(status=status.HTTP_200_OK)
