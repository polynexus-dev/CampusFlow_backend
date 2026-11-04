from django.db import models

class TenantModulePermission(models.Model):
    """
    Defines which of the subscribed modules are permitted for a specific role/group
    within the current tenant schema, what the role may do inside each module, and
    how much of the college's data it sees (see services/rbac.py).
    """
    SCOPE_ALL = "all"
    SCOPE_DEPARTMENT = "department"
    SCOPE_OWN = "own"
    SCOPE_CHOICES = [
        (SCOPE_ALL, "All college records"),
        (SCOPE_DEPARTMENT, "Only their own department"),
        (SCOPE_OWN, "Only the classes they teach"),
    ]

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
    module_actions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-module action list, e.g. {'fees': ['view', 'add']}. A module absent from "
                  "this dict has every action; an empty list means the role has no access to it.",
    )
    data_scope = models.CharField(
        max_length=16,
        choices=SCOPE_CHOICES,
        default=SCOPE_ALL,
        help_text="How much student data this role sees (services/rbac.py scope_students).",
    )
    based_on = models.CharField(
        max_length=100,
        blank=True,
        help_text="For a custom role: the built-in role whose rules it inherits. Every role check "
                  "in the codebase compares built-in names, so get_user_group() answers with this.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant Module Permission"
        verbose_name_plural = "Tenant Module Permissions"

    def __str__(self):
        return f"Permissions for {self.group_name} — {len(self.allowed_modules)} modules"
