from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from .middleware.audit import get_current_request
from .models.audit import AuditLog

@receiver(pre_save)
def capture_old_values(sender, instance, **kwargs):
    """
    In pre_save, fetch the existing model values from the DB (if any)
    to compare them later in post_save.
    """
    if sender._meta.app_label != 'campusflow_app' or sender.__name__ == 'AuditLog':
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
    if sender._meta.app_label != 'campusflow_app' or sender.__name__ == 'AuditLog':
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
                # Convert relationship objects to representation or IDs
                changes[field.name] = {
                    'old': None,
                    'new': str(val)
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
                    'old': str(old_val) if old_val is not None else None,
                    'new': str(new_val) if new_val is not None else None
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


@receiver(post_delete)
def log_delete(sender, instance, **kwargs):
    """
    In post_delete, write a DELETE action to the AuditLog database model.
    """
    if sender._meta.app_label != 'campusflow_app' or sender.__name__ == 'AuditLog':
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
            'old': str(val) if val is not None else None,
            'new': None
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
