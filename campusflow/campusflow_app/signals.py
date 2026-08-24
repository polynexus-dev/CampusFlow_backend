from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from .middleware.audit import get_current_request
from .models.audit import AuditLog
from .utils import mask_sensitive_field

# Fields that must never appear in an audit diff as plain text — Aadhaar/PAN/
# bank details are masked the same way they are everywhere else in the API
# (see mask_sensitive_field), and encrypted credential fields (payment
# gateway secrets) are never shown at all, since the whole point of
# EncryptedCharField is that the plaintext exists nowhere outside the field
# itself. See Docs/campusnexus_security_compliance.html's minimisation claim
# — this is what makes it actually true for the audit trail too, not just
# the regular API responses.
HIDDEN_AUDIT_FIELDS = {'password'}
MASKED_AUDIT_FIELDS = {'aadhaar_number', 'pan_number', 'bank_account_number'}
ENCRYPTED_AUDIT_FIELDS = {
    'razorpay_key_secret', 'razorpay_webhook_secret', 'cashfree_secret_key',
    'payu_merchant_salt', 'phonepe_salt_key', 'paytm_merchant_key',
    'mobikwik_secret_key', 'email_smtp_password', 'erp_auth_token',
}


def _audit_repr(field_name, value):
    """Renders one field's value for the audit diff, redacting sensitive fields."""
    if value is None:
        return None
    if field_name in HIDDEN_AUDIT_FIELDS:
        return '[HIDDEN]'
    if field_name in ENCRYPTED_AUDIT_FIELDS:
        return '[ENCRYPTED]'
    if field_name in MASKED_AUDIT_FIELDS:
        return mask_sensitive_field(str(value))
    return str(value)


def is_audit_eligible(sender):
    """
    Checks if a model is audit-log eligible. Includes campusflow_app models
    (except AuditLog itself) and the auth.User model.
    """
    from django.db import connection
    if getattr(connection, 'schema_name', 'public') == 'public':
        return False
    return (
        (sender._meta.app_label == 'campusflow_app' and sender.__name__ != 'AuditLog') or
        (sender._meta.app_label == 'auth' and sender.__name__ == 'User')
    )

def cleanup_old_audit_logs():
    """
    Automatically purges AuditLog logs older than 30 days.
    Uses cache throttling to run this query at most once a day.
    """
    try:
        if not cache.get('audit_log_cleanup_done'):
            cutoff_date = timezone.now() - timedelta(days=30)
            AuditLog.objects.filter(timestamp__lt=cutoff_date).delete()
            cache.set('audit_log_cleanup_done', True, 86400)
    except Exception:
        pass

@receiver(pre_save)
def capture_old_values(sender, instance, **kwargs):
    """
    In pre_save, fetch the existing model values from the DB (if any)
    to compare them later in post_save.
    """
    if not is_audit_eligible(sender):
        return
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            instance._old_values = {
                field.name: getattr(old_instance, field.name)
                for field in sender._meta.fields
                if field.name not in ['updated_at', 'timestamp']
            }
        except sender.DoesNotExist:
            instance._old_values = {}
    else:
        instance._old_values = {}


@receiver(post_save)
def log_save(sender, instance, created, **kwargs):
    """
    In post_save, compare the old values (from pre_save) with the current values
    and write to the AuditLog database model.
    """
    if not is_audit_eligible(sender):
        return

    request = get_current_request()
    user = None
    ip_address = None
    user_agent = None
    endpoint = None

    if request:
        if request.user and request.user.is_authenticated:
            user = request.user
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        endpoint = request.path[:500]

    action = 'CREATE' if created else 'UPDATE'
    changes = {}

    if created:
        for field in sender._meta.fields:
            if field.name in ['updated_at', 'timestamp']:
                continue
            val = getattr(instance, field.name)
            if val is not None:
                changes[field.name] = {
                    'old': None,
                    'new': _audit_repr(field.name, val),
                }
    else:
        old_values = getattr(instance, '_old_values', {})
        for field in sender._meta.fields:
            if field.name in ['updated_at', 'timestamp']:
                continue
            old_val = old_values.get(field.name)
            new_val = getattr(instance, field.name)
            if old_val != new_val:
                changes[field.name] = {
                    'old': _audit_repr(field.name, old_val),
                    'new': _audit_repr(field.name, new_val),
                }
        if not changes:
            return

    AuditLog.objects.create(
        user=user,
        action=action,
        model_name=sender.__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:500],
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
        endpoint=endpoint
    )
    cleanup_old_audit_logs()


@receiver(post_delete)
def log_delete(sender, instance, **kwargs):
    """
    In post_delete, write a DELETE action to the AuditLog database model.
    """
    if not is_audit_eligible(sender):
        return

    request = get_current_request()
    user = None
    ip_address = None
    user_agent = None
    endpoint = None

    if request:
        if request.user and request.user.is_authenticated:
            user = request.user
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        endpoint = request.path[:500]

    changes = {}
    for field in sender._meta.fields:
        if field.name in ['updated_at', 'timestamp']:
            continue
        val = getattr(instance, field.name)
        changes[field.name] = {
            'old': _audit_repr(field.name, val),
            'new': None,
        }

    AuditLog.objects.create(
        user=user,
        action='DELETE',
        model_name=sender.__name__,
        object_id=str(instance.pk),
        object_repr=str(instance)[:500],
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
        endpoint=endpoint
    )
    cleanup_old_audit_logs()


# ── Library Management Signal Receivers ──
from campusflow_app.models.library import Book, BookCopy, BookIssue

@receiver(post_save, sender=BookCopy)
def update_book_copies_on_save(sender, instance, created, **kwargs):
    """
    Automatically updates a Book's total_copies and available_copies counts
    whenever a copy is created, updated, or status changes.
    """
    book = instance.book
    book.total_copies = book.copies.count()
    book.available_copies = book.copies.filter(status='Available').count()
    book.save(update_fields=['total_copies', 'available_copies'])

@receiver(post_delete, sender=BookCopy)
def update_book_copies_on_delete(sender, instance, **kwargs):
    """
    Automatically updates a Book's total_copies and available_copies counts
    whenever a copy is deleted.
    """
    book = instance.book
    book.total_copies = book.copies.count()
    book.available_copies = book.copies.filter(status='Available').count()
    book.save(update_fields=['total_copies', 'available_copies'])

@receiver(post_save, sender=BookIssue)
def update_copy_status_on_issue_save(sender, instance, created, **kwargs):
    """
    Automatically adjusts the BookCopy status when an issue registry is created or modified.
    - If status is 'Issued' or 'Overdue', set the Copy status to 'Issued'.
    - If status is 'Returned', set the Copy status to 'Available'.
    """
    copy = instance.book_copy
    if instance.status in ('Issued', 'Overdue'):
        if copy.status != 'Issued':
            copy.status = 'Issued'
            copy.save(update_fields=['status'])
    elif instance.status == 'Returned':
        if copy.status != 'Available':
            copy.status = 'Available'
            copy.save(update_fields=['status'])

