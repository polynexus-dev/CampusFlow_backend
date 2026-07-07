"""
Gateway adapter layer for online fee payments.

Each tenant (college) picks one active gateway (`Tenant.payment_gateway_active`)
and configures its own credentials on the Tenant model. `get_adapter_for_tenant`
returns the right adapter instance; views/payments.py only talks to the
BaseGatewayAdapter interface, so adding a new gateway later means writing one
new adapter class, not touching the views.

Razorpay is the only fully-implemented adapter right now (most mature official
Python SDK). Cashfree/PayU are wired into the same interface but raise
GatewayNotImplementedError until a real integration is added.
"""
import razorpay


class GatewayNotImplementedError(Exception):
    """Raised when a tenant's active gateway has no working adapter yet."""
    pass


class BaseGatewayAdapter:
    def __init__(self, tenant):
        self.tenant = tenant

    def create_order(self, amount, currency, receipt, notes):
        """Returns dict with at least {'order_id': ..., 'raw_response': {...}}."""
        raise NotImplementedError

    def verify_payment_signature(self, payload: dict) -> bool:
        """Verifies the checkout success callback the frontend posts back."""
        raise NotImplementedError

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        raise NotImplementedError

    def parse_webhook_event(self, payload: dict) -> dict:
        """Normalizes a webhook payload to {event_type, gateway_order_id, gateway_payment_id, status}."""
        raise NotImplementedError


class RazorpayAdapter(BaseGatewayAdapter):
    def _client(self):
        return razorpay.Client(auth=(self.tenant.razorpay_key_id, self.tenant.razorpay_key_secret))

    def create_order(self, amount, currency, receipt, notes):
        client = self._client()
        # Razorpay amounts are in the smallest currency unit (paise for INR).
        response = client.order.create({
            "amount": int(amount * 100),
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
        })
        return {"order_id": response["id"], "raw_response": response}

    def verify_payment_signature(self, payload: dict) -> bool:
        client = self._client()
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": payload.get("razorpay_order_id"),
                "razorpay_payment_id": payload.get("razorpay_payment_id"),
                "razorpay_signature": payload.get("razorpay_signature"),
            })
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        client = self._client()
        try:
            client.utility.verify_webhook_signature(
                raw_body.decode() if isinstance(raw_body, bytes) else raw_body,
                signature,
                self.tenant.razorpay_webhook_secret,
            )
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def parse_webhook_event(self, payload: dict) -> dict:
        event_type = payload.get("event", "")
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        status = "paid" if event_type == "payment.captured" else "failed" if event_type == "payment.failed" else "unknown"
        return {
            "event_type": event_type,
            "gateway_order_id": entity.get("order_id"),
            "gateway_payment_id": entity.get("id"),
            "status": status,
        }


class CashfreeAdapter(BaseGatewayAdapter):
    _NOT_READY = "Cashfree isn't wired up yet for online checkout — switch this college to Razorpay, or ask CampusFlow support to enable Cashfree."

    def create_order(self, amount, currency, receipt, notes):
        raise GatewayNotImplementedError(self._NOT_READY)

    def verify_payment_signature(self, payload: dict) -> bool:
        raise GatewayNotImplementedError(self._NOT_READY)

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        raise GatewayNotImplementedError(self._NOT_READY)

    def parse_webhook_event(self, payload: dict) -> dict:
        raise GatewayNotImplementedError(self._NOT_READY)


class PayUAdapter(BaseGatewayAdapter):
    _NOT_READY = "PayU isn't wired up yet for online checkout — switch this college to Razorpay, or ask CampusFlow support to enable PayU."

    def create_order(self, amount, currency, receipt, notes):
        raise GatewayNotImplementedError(self._NOT_READY)

    def verify_payment_signature(self, payload: dict) -> bool:
        raise GatewayNotImplementedError(self._NOT_READY)

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        raise GatewayNotImplementedError(self._NOT_READY)

    def parse_webhook_event(self, payload: dict) -> dict:
        raise GatewayNotImplementedError(self._NOT_READY)


_ADAPTERS = {
    "razorpay": RazorpayAdapter,
    "cashfree": CashfreeAdapter,
    "payu": PayUAdapter,
}


def get_adapter_for_tenant(tenant) -> BaseGatewayAdapter:
    gateway = tenant.payment_gateway_active
    if gateway == "manual" or not gateway:
        raise GatewayNotImplementedError("Online payments aren't enabled for your college yet. Please pay via the college office.")
    adapter_cls = _ADAPTERS.get(gateway)
    if adapter_cls is None:
        raise GatewayNotImplementedError(f"'{gateway}' has no online checkout integration yet.")
    return adapter_cls(tenant)
