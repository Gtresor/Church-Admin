from django.apps import AppConfig


class BaseConfig(AppConfig):
    name = "base"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import base.signals  # noqa: F401
