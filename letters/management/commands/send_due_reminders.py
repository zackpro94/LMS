"""Django management command to send Telegram reminders for due letters."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from letters.models import Letter
from letters.telegram_utils import send_telegram_message


class Command(BaseCommand):
    help = 'Send Telegram reminders for letters due tomorrow or overdue'

    def handle(self, *args, **options):
        today = timezone.now().date()
        tomorrow = today + timezone.timedelta(days=1)
        
        # Statuses that should not trigger reminders
        inactive_statuses = ['CLOSED', 'ARCHIVED', 'CANCELLED']
        
        # Find letters due tomorrow
        letters_due_tomorrow = Letter.objects.filter(
            due_date=tomorrow,
            status__in=[s[0] for s in Letter.STATUS_CHOICES if s[0] not in inactive_statuses]
        )
        
        # Find overdue letters (due date has passed)
        overdue_letters = Letter.objects.filter(
            due_date__lt=today,
            status__in=[s[0] for s in Letter.STATUS_CHOICES if s[0] not in inactive_statuses]
        )
        
        total_sent = 0
        
        # Send reminders for letters due tomorrow
        for letter in letters_due_tomorrow:
            if letter.assigned_person:
                try:
                    profile = letter.assigned_person.profile
                    if profile.telegram_chat_id and profile.telegram_notifications:
                        # Determine sender/recipient based on direction
                        if letter.direction == 'INCOMING':
                            contact_info = f"From: {letter.sender}" if letter.sender else ""
                        else:
                            contact_info = f"To: {letter.recipient}" if letter.recipient else ""
                        
                        direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"
                        
                        message = (
                            f"{direction_emoji} Reminder: Letter due tomorrow\n"
                            f"Reference: {letter.reference_no}\n"
                            f"Subject: {letter.subject}\n"
                            f"Due: {letter.due_date.strftime('%Y-%m-%d')}"
                        )
                        
                        if contact_info:
                            message += f"\n{contact_info}"
                        
                        # Add letter link
                        letter_url = f"https://lms.pro.et/letters/{letter.id}/"
                        message += f"\n\n<a href='{letter_url}'>View Letter</a>"
                        
                        if send_telegram_message(profile.telegram_chat_id, message):
                            total_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent reminder for {letter.reference_no} to {letter.assigned_person.username}"
                                )
                            )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error sending reminder for {letter.reference_no}: {str(e)}"
                        )
                    )
        
        # Send reminders for overdue letters
        for letter in overdue_letters:
            if letter.assigned_person:
                try:
                    profile = letter.assigned_person.profile
                    if profile.telegram_chat_id and profile.telegram_notifications:
                        # Determine sender/recipient based on direction
                        if letter.direction == 'INCOMING':
                            contact_info = f"From: {letter.sender}" if letter.sender else ""
                        else:
                            contact_info = f"To: {letter.recipient}" if letter.recipient else ""
                        
                        direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"
                        
                        message = (
                            f"{direction_emoji} Overdue: Letter was due on {letter.due_date.strftime('%Y-%m-%d')}\n"
                            f"Reference: {letter.reference_no}\n"
                            f"Subject: {letter.subject}\n"
                            f"Days overdue: {(today - letter.due_date).days}"
                        )
                        
                        if contact_info:
                            message += f"\n{contact_info}"
                        
                        # Add letter link
                        letter_url = f"https://lms.pro.et/letters/{letter.id}/"
                        message += f"\n\n<a href='{letter_url}'>View Letter</a>"
                        
                        if send_telegram_message(profile.telegram_chat_id, message):
                            total_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent overdue reminder for {letter.reference_no} to {letter.assigned_person.username}"
                                )
                            )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Error sending overdue reminder for {letter.reference_no}: {str(e)}"
                        )
                    )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nTotal reminders sent: {total_sent}\n"
                f"Letters due tomorrow: {letters_due_tomorrow.count()}\n"
                f"Overdue letters: {overdue_letters.count()}"
            )
        )
