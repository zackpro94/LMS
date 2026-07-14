"""Django management command to poll Telegram for updates (for local development)."""
from django.core.management.base import BaseCommand
from letters.telegram_utils import get_telegram_updates, handle_telegram_webhook


class Command(BaseCommand):
    help = 'Poll Telegram for updates (for local development without webhooks)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Starting Telegram polling...'))
        self.stdout.write('Press Ctrl+C to stop.')
        
        offset = 0
        
        try:
            while True:
                updates = get_telegram_updates(offset=offset, timeout=30)
                
                if updates:
                    for update in updates:
                        try:
                            result = handle_telegram_webhook(update)
                            if result.get('ok'):
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"Processed update {update.get('update_id')}"
                                    )
                                )
                            else:
                                self.stdout.write(
                                    self.style.ERROR(
                                        f"Failed to process update {update.get('update_id')}: {result.get('error')}"
                                    )
                                )
                            
                            # Update offset to mark this update as processed
                            offset = update.get('update_id') + 1
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"Error processing update {update.get('update_id')}: {str(e)}"
                                )
                            )
                            offset = update.get('update_id') + 1
                else:
                    self.stdout.write('No updates received.')
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\nPolling stopped.'))
