from django.apps import AppConfig


class CampusflowAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "campusflow_app"

    def ready(self):
        import campusflow_app.signals