"""Django management command to send Telegram and SMS reminders for due letters."""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from letters.models import Letter
from letters.telegram_utils import send_telegram_message
from letters.sms_utils import send_sms


class Command(BaseCommand):
    help = 'Send Telegram and SMS reminders for letters due tomorrow or overdue'

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
        
        telegram_sent = 0
        sms_sent = 0
        
        # Send reminders for letters due tomorrow
        for letter in letters_due_tomorrow:
            if letter.assigned_person:
                t, s = self._send_due_reminder(letter, today, is_overdue=False)
                telegram_sent += t
                sms_sent += s
        
        # Send reminders for overdue letters
        for letter in overdue_letters:
            if letter.assigned_person:
                t, s = self._send_due_reminder(letter, today, is_overdue=True)
                telegram_sent += t
                sms_sent += s
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\nReminders sent — Telegram: {telegram_sent}, SMS: {sms_sent}\n"
                f"Letters due tomorrow: {letters_due_tomorrow.count()}\n"
                f"Overdue letters: {overdue_letters.count()}"
            )
        )

    def _send_due_reminder(self, letter, today, is_overdue=False):
        """Send due/overdue reminder via Telegram and SMS. Returns (telegram_count, sms_count)."""
        telegram_count = 0
        sms_count = 0

        try:
            profile = letter.assigned_person.profile
        except Exception:
            return (0, 0)

        # Determine sender/recipient based on direction
        if letter.direction == 'INCOMING':
            contact_info = f"From: {letter.sender}" if letter.sender else ""
        else:
            contact_info = f"To: {letter.recipient}" if letter.recipient else ""

        direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"

        # --- Telegram ---
        if profile.telegram_chat_id and profile.telegram_notifications:
            try:
                if is_overdue:
                    days_overdue = (today - letter.due_date).days
                    tg_message = (
                        f"{direction_emoji} Overdue: Letter was due on {letter.due_date.strftime('%Y-%m-%d')}\n"
                        f"Reference: {letter.reference_no}\n"
                        f"Subject: {letter.subject}\n"
                        f"Days overdue: {days_overdue}"
                    )
                else:
                    tg_message = (
                        f"{direction_emoji} Reminder: Letter due tomorrow\n"
                        f"Reference: {letter.reference_no}\n"
                        f"Subject: {letter.subject}\n"
                        f"Due: {letter.due_date.strftime('%Y-%m-%d')}"
                    )

                if contact_info:
                    tg_message += f"\n{contact_info}"

                letter_url = f"https://lms.pro.et/letters/{letter.id}/"
                tg_message += f"\n\n<a href='{letter_url}'>View Letter</a>"

                if send_telegram_message(profile.telegram_chat_id, tg_message):
                    telegram_count = 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[Telegram] {'Overdue' if is_overdue else 'Due'} reminder for "
                            f"{letter.reference_no} → {letter.assigned_person.username}"
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"[Telegram] Error for {letter.reference_no}: {str(e)}"
                    )
                )

        # --- SMS ---
        if profile.phone_number and profile.sms_notifications:
            try:
                direction_label = "Incoming" if letter.direction == 'INCOMING' else "Outgoing"

                if is_overdue:
                    days_overdue = (today - letter.due_date).days
                    sms_message = (
                        f"AE LMS: OVERDUE {direction_label} letter\n"
                        f"Ref: {letter.reference_no}\n"
                        f"Subject: {letter.subject[:40]}\n"
                        f"Days overdue: {days_overdue}"
                    )
                else:
                    sms_message = (
                        f"AE LMS: Letter due TOMORROW\n"
                        f"Ref: {letter.reference_no}\n"
                        f"Subject: {letter.subject[:40]}\n"
                        f"Due: {letter.due_date.strftime('%Y-%m-%d')}"
                    )

                if send_sms(profile.phone_number, sms_message):
                    sms_count = 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[SMS] {'Overdue' if is_overdue else 'Due'} reminder for "
                            f"{letter.reference_no} → {profile.phone_number}"
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"[SMS] Error for {letter.reference_no}: {str(e)}"
                    )
                )

        return (telegram_count, sms_count)
