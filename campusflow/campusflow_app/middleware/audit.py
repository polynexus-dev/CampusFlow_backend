import contextvars
from django.utils.deprecation import MiddlewareMixin

# Context variable to hold the current request object in a thread/async safe way.
_current_request = contextvars.ContextVar('current_request', default=None)

class AuditMiddleware(MiddlewareMixin):
    """
    Middleware to capture the current request and store it in contextvars
    so that model signals (pre_save, post_save, post_delete) can access it
    to log who performed the action.
    """
    def process_request(self, request):
        request._audit_token = _current_request.set(request)
        request._audit_token_used = False

    def process_response(self, request, response):
        if hasattr(request, '_audit_token') and not getattr(request, '_audit_token_used', False):
            self._reset_token(request._audit_token)
            request._audit_token_used = True
        return response

    def process_exception(self, request, exception):
        if hasattr(request, '_audit_token') and not getattr(request, '_audit_token_used', False):
            self._reset_token(request._audit_token)
            request._audit_token_used = True

    @staticmethod
    def _reset_token(token):
        # Under ASGI (uvicorn), process_request/process_response for this
        # middleware can run in different contextvars Contexts (Django bridges
        # sync MiddlewareMixin hooks across sync/async boundaries via separate
        # thread-executor calls), so the Token from .set() may not belong to
        # the Context calling .reset() here. Resetting is just best-effort
        # cleanup — each request gets its own fresh Context regardless, so a
        # skipped reset can't leak the request into another request's Context.
        try:
            _current_request.reset(token)
        except ValueError:
            pass


def get_current_request():
    return _current_request.get()
