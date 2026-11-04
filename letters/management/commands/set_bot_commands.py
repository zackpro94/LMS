"""Django management command to register Telegram bot commands."""
from django.core.management.base import BaseCommand
from django.conf import settings
import requests


class Command(BaseCommand):
    help = 'Register bot commands with Telegram so they appear in the command menu'

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            self.stderr.write(self.style.ERROR('TELEGRAM_BOT_TOKEN not configured.'))
            return

        url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setMyCommands'

        commands = [
            {'command': 'start', 'description': 'Get started with AE LMS Bot'},
            {'command': 'attach', 'description': 'Upload attachments to old archive letters'},
            {'command': 'done', 'description': 'Finish uploading attachments'},
            {'command': 'cancel', 'description': 'Cancel current operation'},
            {'command': 'clear', 'description': 'Clear chat history'},
            {'command': 'logout', 'description': 'Log out from active upload session'},
            {'command': 'help', 'description': 'Show available commands'},
        ]

        try:
            response = requests.post(url, json={'commands': commands}, timeout=10)
            result = response.json()

            if result.get('ok'):
                self.stdout.write(self.style.SUCCESS('[SUCCESS] Bot commands registered successfully!'))
                for cmd in commands:
                    self.stdout.write(f"  /{cmd['command']} - {cmd['description']}")
            else:
                self.stderr.write(
                    self.style.ERROR(f"Failed: {result.get('description', 'Unknown error')}")
                )
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Request failed: {e}'))

