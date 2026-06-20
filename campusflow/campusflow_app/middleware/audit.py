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
            _current_request.reset(request._audit_token)
            request._audit_token_used = True
        return response

    def process_exception(self, request, exception):
        if hasattr(request, '_audit_token') and not getattr(request, '_audit_token_used', False):
            _current_request.reset(request._audit_token)
            request._audit_token_used = True


def get_current_request():
    return _current_request.get()
