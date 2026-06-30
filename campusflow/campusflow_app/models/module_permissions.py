from django.db import models

class TenantModulePermission(models.Model):
    """
    Defines which of the subscribed modules are permitted for a specific role/group
    within the current tenant schema.
    """
    group_name = models.CharField(
        max_length=100, 
        unique=True,
        help_text="Name of the user group (e.g. 'student', 'Faculty', 'Department Head')"
    )
    allowed_modules = models.JSONField(
        default=list,
        blank=True,
        help_text="List of modules permitted for this group, e.g. ['attendance', 'exams']"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant Module Permission"
        verbose_name_plural = "Tenant Module Permissions"

    def __str__(self):
        return f"Permissions for {self.group_name} — {len(self.allowed_modules)} modules"
