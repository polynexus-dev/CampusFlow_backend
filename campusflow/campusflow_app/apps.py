from django.apps import AppConfig


class CampusflowAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "campusflow_app"

    def ready(self):
        # Remove this line: import attendance_app.signals
        # The signals that automatically create profiles are no longer used here.
        pass # No signals to import for this new profile structure.