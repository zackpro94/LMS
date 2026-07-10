from django.apps import AppConfig


class LettersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'letters'
    verbose_name = 'Letter Management'

    def ready(self):
        import letters.signals
