from django.apps import AppConfig


class TransfersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'transfers'

    def ready(self):
        try:
            import transfers.signals
        except ImportError:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Failed to import transfers.signals.")
