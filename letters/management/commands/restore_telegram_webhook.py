"""Django management command to restore production Telegram webhook."""
from django.core.management.base import BaseCommand
from django.conf import settings
import requests

WEBHOOK_URL = 'https://lms.pro.et/telegram/webhook/?secret=nxz3_RIR0-njUpmbOB48urGCHdwaqi_l1wLgVulOImw'


class Command(BaseCommand):
    help = 'Restore the production Telegram webhook for lms.pro.et'

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stderr.write(self.style.ERROR('TELEGRAM_BOT_TOKEN not configured in settings.'))
            return

        url = f'https://api.telegram.org/bot{token}/setWebhook'
        try:
            resp = requests.post(url, json={'url': WEBHOOK_URL}, timeout=10)
            res = resp.json()
            if res.get('ok'):
                self.stdout.write(self.style.SUCCESS(f'[SUCCESS] Production webhook restored: {WEBHOOK_URL}'))
            else:
                self.stderr.write(self.style.ERROR(f'Failed to restore webhook: {res}'))
        except requests.exceptions.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Request failed: {e}'))

