"""
Tenant (College) Views
======================
Only the SaaS Admin (Django superuser) can create colleges.
This is enforced both here and via IsAdminUser permission.
"""
from rest_framework import generics, permissions
from .serializers import TenantCreateSerializer, TenantListSerializer, TenantUpdateSerializer
from .models import Tenant


class TenantCreateAPIView(generics.ListCreateAPIView):
    """
    SaaS Admin only: Create and list colleges (tenants).
    
    After creating a college, the SaaS Admin must:
    1. Log in to the college's tenant subdomain
    2. Create a Management user (College Admin) via POST /register/
    3. The College Admin then creates departments
    4. After departments exist, the College Admin creates other users
    """
    queryset = Tenant.objects.all()
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return TenantListSerializer
        return TenantCreateSerializer

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can create colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().create(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can list colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().list(request, *args, **kwargs)


class TenantDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    SaaS Admin only: Retrieve, update, or delete a college (tenant).
    """
    queryset = Tenant.objects.all()
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return TenantUpdateSerializer
        return TenantListSerializer

    def retrieve(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can view college details."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can update colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can delete colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        # Custom delete: also clean up associated schemas if desired, but django-tenants handles this on model delete.
        return super().destroy(request, *args, **kwargs)


from django.db import connection
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceUploadReceiptSerializer

class InvoiceListAPIView(APIView):
    """
    List invoices for the active tenant and display Polynexus bank details.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        active_tenant = connection.tenant
        if active_tenant.schema_name == 'public':
            return Response({"error": "No invoices associated with the public central schema."}, status=status.HTTP_400_BAD_REQUEST)

        invoices = Invoice.objects.filter(tenant=active_tenant).order_by('-created_at')
        serializer = InvoiceSerializer(invoices, many=True)

        bank_details = {
            "bank_name": "State Bank of India",
            "account_name": "Polynexus Technologies Private Limited",
            "account_number": "41234567890",
            "ifsc_code": "SBIN0001234",
            "branch": "Nagpur Main Branch"
        }

        return Response({
            "invoices": serializer.data,
            "bank_details": bank_details,
            "subscription_status": active_tenant.subscription_status,
            "subscription_end_date": active_tenant.subscription_end_date,
            "trial_end_date": active_tenant.trial_end_date
        }, status=status.HTTP_200_OK)


class InvoiceUploadReceiptAPIView(APIView):
    """
    Upload NEFT/RTGS transaction receipt image and UTR transaction number.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        active_tenant = connection.tenant
        if active_tenant.schema_name == 'public':
            return Response({"error": "Not allowed in public central schema."}, status=status.HTTP_400_BAD_REQUEST)

        invoice = Invoice.objects.filter(pk=pk, tenant=active_tenant).first()
        if not invoice:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        if invoice.status == 'paid':
            return Response({"error": "Invoice is already paid."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = InvoiceUploadReceiptSerializer(invoice, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(
                status='under_review',
                uploaded_at=timezone.now()
            )
            return Response({
                "message": "Payment receipt uploaded successfully. The Polynexus finance team will verify the payment and activate/extend your subscription shortly.",
                "invoice": InvoiceSerializer(invoice).data
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SaaSInvoiceListAPIView(generics.ListAPIView):
    """
    SaaS Admin only: List all invoices across all tenants.
    """
    queryset = Invoice.objects.all().order_by('-created_at')
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]


class SaaSInvoiceApproveAPIView(APIView):
    """
    SaaS Admin only: Approve invoice payment and extend subscription.
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def post(self, request, pk):
        invoice = Invoice.objects.filter(pk=pk).first()
        if not invoice:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        if invoice.status == 'paid':
            return Response({"error": "Invoice is already approved/paid."}, status=status.HTTP_400_BAD_REQUEST)

        tenant = invoice.tenant
        
        # Calculate new subscription end date
        now_date = timezone.now().date()
        base_date = tenant.subscription_end_date if (tenant.subscription_end_date and tenant.subscription_end_date > now_date) else now_date

        days_to_add = 30 if tenant.billing_cycle == 'monthly' else 365
        new_end_date = base_date + timezone.timedelta(days=days_to_add)

        # Update Tenant Subscription
        tenant.subscription_status = 'active'
        tenant.subscription_end_date = new_end_date
        tenant.is_active = True
        tenant.save(update_fields=['subscription_status', 'subscription_end_date', 'is_active'])

        # Update Invoice
        invoice.status = 'paid'
        invoice.marked_paid_at = timezone.now()
        invoice.save(update_fields=['status', 'marked_paid_at'])

        # Send payment confirmation email
        try:
            from django.core.mail import send_mail
            send_mail(
                "Payment Confirmed & Subscription Activated - CampusNexus",
                f"Dear Principal/Authorized Admin,\n\nWe have verified your RTGS/NEFT payment of Rs. {invoice.amount} for Invoice {invoice.invoice_number}.\n\nYour subscription has been successfully extended until {new_end_date}.\n\nThank you for choosing CampusNexus.\n\nPolynexus Technologies Private Limited",
                None,
                [tenant.contact_email or "admin@polynexus.in"],
                fail_silently=True
            )
        except Exception:
            pass

        return Response({
            "message": f"Invoice approved. Subscription extended until {new_end_date}.",
            "invoice": InvoiceSerializer(invoice).data
        }, status=status.HTTP_200_OK)


class SaaSInvoiceRejectAPIView(APIView):
    """
    SaaS Admin only: Reject invoice receipt screenshot.
    """
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def post(self, request, pk):
        invoice = Invoice.objects.filter(pk=pk).first()
        if not invoice:
            return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)

        if invoice.status == 'paid':
            return Response({"error": "Cannot reject an already paid invoice."}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', 'Payment screenshot was invalid or not found in our bank records. Please verify and upload again.').strip()

        invoice.status = 'pending_payment'
        invoice.bank_receipt = None
        invoice.utr_number = None
        invoice.save(update_fields=['status', 'bank_receipt', 'utr_number'])

        # Send rejection notice email
        tenant = invoice.tenant
        try:
            from django.core.mail import send_mail
            send_mail(
                "Payment Verification Failed - CampusNexus",
                f"Dear Principal/Authorized Admin,\n\nWe were unable to verify your payment for Invoice {invoice.invoice_number}.\n\nReason: {reason}\n\nPlease check the transaction or upload a valid payment receipt screen capture again.\n\nPolynexus Technologies Private Limited",
                None,
                [tenant.contact_email or "admin@polynexus.in"],
                fail_silently=True
            )
        except Exception:
            pass

        return Response({
            "message": "Invoice payment receipt rejected. Notice sent to college admin.",
            "invoice": InvoiceSerializer(invoice).data
        }, status=status.HTTP_200_OK)
