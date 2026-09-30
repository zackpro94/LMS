from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Letter, Notification, ActionLog
from .telegram_utils import send_telegram_message
from .sms_utils import send_sms_notification
import json
import logging

logger = logging.getLogger(__name__)

try:
    channel_layer = get_channel_layer()
    CHANNELS_AVAILABLE = True
except Exception:
    channel_layer = None
    CHANNELS_AVAILABLE = False


@receiver(pre_save, sender=Letter)
def track_old_status(sender, instance, **kwargs):
    """Track the old status before save to detect changes."""
    if instance.pk:
        try:
            instance._old_status = Letter.objects.get(pk=instance.pk).status
        except Letter.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=Letter)
def letter_saved(sender, instance, created, **kwargs):
    """Send real-time notification when a letter is created or updated."""
    if created:
        # Notify relevant users about new letter
        notify_users_about_letter(instance, 'created')
        # Send Telegram notification for new assignment
        send_telegram_for_letter_assignment(instance)
        # Send SMS notification for new assignment
        send_sms_for_letter_assignment(instance)
    else:
        # Notify about letter update
        notify_users_about_letter(instance, 'updated')
        # Send Telegram notification for status changes
        send_telegram_for_status_change(instance)
        # Send SMS notification for status changes
        send_sms_for_status_change(instance)


@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """Send real-time notification when a notification is created."""
    if created:
        send_notification_to_user(instance)


@receiver(post_save, sender=ActionLog)
def action_log_created(sender, instance, created, **kwargs):
    """Send real-time notification when an action is logged."""
    if created:
        notify_users_about_action(instance)


def notify_users_about_letter(letter, action_type):
    """Notify relevant users about letter changes."""
    # Get users who should be notified
    users_to_notify = set()
    
    # Add assigned person
    if letter.assigned_person:
        users_to_notify.add(letter.assigned_person)
    
    # Add department staff
    if letter.assigned_department:
        users_to_notify.update(letter.assigned_department.users.all())
    
    # Add creator
    if letter.created_by:
        users_to_notify.add(letter.created_by)
    
    # Send notification to each user
    for user in users_to_notify:
        if user.id != letter.assigned_person_id or action_type == 'created':
            send_letter_update_to_user(user, letter, action_type)


def notify_users_about_action(action):
    """Notify relevant users about new action."""
    if action.letter:
        # Notify letter creator and assigned user
        users_to_notify = set()
        if action.letter.created_by:
            users_to_notify.add(action.letter.created_by)
        if action.letter.assigned_person:
            users_to_notify.add(action.letter.assigned_person)
        
        for user in users_to_notify:
            if user != action.action_by:
                send_action_notification_to_user(user, action)


def send_notification_to_user(notification):
    """Send notification to user via WebSocket."""
    if not CHANNELS_AVAILABLE:
        return
    
    try:
        group_name = f"user_{notification.recipient.id}"
        
        notification_data = {
            'id': notification.id,
            'title': notification.title,
            'message': notification.message,
            'notification_type': notification.notification_type,
            'is_read': notification.is_read,
            'created_at': notification.created_at.isoformat(),
            'related_letter_id': notification.related_letter.id if notification.related_letter else None,
        }
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'notification_message',
                'notification': notification_data
            }
        )
    except ConnectionError as e:
        print(f"Redis connection error in send_notification_to_user: {e}")
    except Exception as e:
        print(f"Error sending notification via WebSocket: {e}")


def send_letter_update_to_user(user, letter, action_type):
    """Send letter update to user via WebSocket."""
    if not CHANNELS_AVAILABLE:
        return
    
    try:
        group_name = f"user_{user.id}"
        
        letter_data = {
            'id': letter.id,
            'subject': letter.subject,
            'action_type': action_type,
            'status': letter.status,
            'priority': letter.priority,
            'updated_at': letter.updated_at.isoformat(),
        }
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'letter_update',
                'letter': letter_data
            }
        )
    except ConnectionError as e:
        print(f"Redis connection error in send_letter_update_to_user: {e}")
    except Exception as e:
        print(f"Error sending letter update via WebSocket: {e}")


def send_action_notification_to_user(user, action):
    """Send action notification to user via WebSocket."""
    if not CHANNELS_AVAILABLE:
        return
    
    try:
        group_name = f"user_{user.id}"
        
        action_data = {
            'id': action.id,
            'action_type': action.action,
            'letter_id': action.letter.id if action.letter else None,
            'performed_by': action.action_by.username if action.action_by else 'Unknown',
            'created_at': action.action_date.isoformat(),
        }
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'notification_message',
                'notification': {
                    'title': f'New Action: {action.action}',
                    'message': f'{action.action_by.username if action.action_by else "Unknown"} performed {action.action}',
                    'notification_type': 'action',
                    'is_read': False,
                    'created_at': action.action_date.isoformat(),
                }
            }
        )
    except ConnectionError as e:
        print(f"Redis connection error in send_action_notification_to_user: {e}")
    except Exception as e:
        print(f"Error sending action notification via WebSocket: {e}")


def send_telegram_for_letter_assignment(letter):
    """Send Telegram notification when a letter is assigned to a user."""
    if not letter.assigned_person:
        return

    try:
        profile = getattr(letter.assigned_person, 'profile', None)
        if profile and profile.telegram_chat_id and profile.telegram_notifications:
            # Determine sender/recipient based on direction
            if letter.direction == 'INCOMING':
                contact_info = f"From: {letter.sender}" if letter.sender else ""
            else:
                contact_info = f"To: {letter.recipient}" if letter.recipient else ""

            direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"

            # Priority emoji
            priority_emojis = {
                'URGENT': '🔴',
                'CONFIDENTIAL': '🔒',
                'NORMAL': '📋'
            }
            priority_emoji = priority_emojis.get(letter.priority, '📋')

            # Letter type emoji
            type_emoji = '📄' if letter.letter_type == 'HARDCOPY' else '💻'

            message = (
                f"{direction_emoji} {priority_emoji} New letter assigned\n\n"
                f"<b>Reference:</b> {letter.reference_no}\n"
                f"<b>Subject:</b> {letter.subject}\n"
                f"<b>Type:</b> {type_emoji} {letter.get_letter_type_display()}\n"
                f"<b>Priority:</b> {letter.get_priority_display()}"
            )

            # Add category
            if letter.category:
                message += f"\n<b>Category:</b> {letter.category.name}"

            # Add assigned by
            if letter.created_by:
                message += f"\n<b>Assigned by:</b> {letter.created_by.get_full_name() or letter.created_by.username}"

            # Add contact info
            if contact_info:
                message += f"\n<b>{contact_info}</b>"

            # Add date info
            if letter.date:
                message += f"\n<b>Date:</b> {letter.date.strftime('%Y-%m-%d')}"
                if letter.ethiopian_date:
                    message += f" ({letter.ethiopian_date})"

            # Add due date
            if letter.due_date:
                message += f"\n<b>Due:</b> {letter.due_date.strftime('%Y-%m-%d')}"
                if letter.ethiopian_due_date:
                    message += f" ({letter.ethiopian_due_date})"
                if letter.is_overdue:
                    message += " ⚠️ OVERDUE"

            # Add letter link
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', 'https://lms.pro.et')
            letter_url = f"{site_url}{letter.get_short_url()}"
            message += f"\n\n<a href='{letter_url}'>📎 View Letter</a>"

            send_telegram_message(profile.telegram_chat_id, message)
    except Exception as e:
        logger.error(f"Error sending Telegram notification for letter assignment: {e}")


def send_telegram_for_status_change(letter):
    """Send Telegram notification when letter status changes to specific values."""
    old_status = getattr(letter, '_old_status', None)
    
    # Only notify for specific status changes
    status_changes_to_notify = ['RESPONDED', 'CLOSED', 'APPROVED', 'REJECTED']
    
    if old_status and letter.status in status_changes_to_notify and old_status != letter.status:
        try:
            # Notify the letter creator
            if letter.created_by:
                profile = getattr(letter.created_by, 'profile', None)
                if profile and profile.telegram_chat_id and profile.telegram_notifications:
                    # Determine sender/recipient based on direction
                    if letter.direction == 'INCOMING':
                        contact_info = f"From: {letter.sender}" if letter.sender else ""
                    else:
                        contact_info = f"To: {letter.recipient}" if letter.recipient else ""
                    
                    direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"
                    
                    message = (
                        f"{direction_emoji} Letter status updated\n"
                        f"Reference: {letter.reference_no}\n"
                        f"Status: {old_status} → {letter.status}\n"
                        f"Subject: {letter.subject}"
                    )
                    
                    if contact_info:
                        message += f"\n{contact_info}"
                    
                    # Add letter link
                    from django.conf import settings
                    site_url = getattr(settings, 'SITE_URL', 'https://lms.pro.et')
                    letter_url = f"{site_url}{letter.get_short_url()}"
                    message += f"\n\n<a href='{letter_url}'>View Letter</a>"
                    
                    send_telegram_message(profile.telegram_chat_id, message)
        except Exception as e:
            logger.error(f"Error sending Telegram notification for status change: {e}")


def send_sms_for_letter_assignment(letter):
    """Send SMS notification when a letter is assigned to a user."""
    if not letter.assigned_person:
        return

    try:
        profile = getattr(letter.assigned_person, 'profile', None)
        if profile and profile.phone_number and profile.sms_notifications:
            direction_label = "IN" if letter.direction == 'INCOMING' else "OUT"

            # Priority indicator
            priority_indicators = {
                'URGENT': '!',
                'CONFIDENTIAL': '#',
                'NORMAL': ''
            }
            priority_indicator = priority_indicators.get(letter.priority, '')

            sms_text = (
                f"AE LMS: New {direction_label} letter {priority_indicator}\n"
                f"Ref: {letter.reference_no}\n"
                f"Subj: {letter.subject[:50]}"
            )

            # Add priority
            sms_text += f"\nPrio: {letter.get_priority_display()}"

            # Add sender/recipient
            if letter.direction == 'INCOMING' and letter.sender:
                sms_text += f"\nFrom: {letter.sender[:30]}"
            elif letter.direction == 'OUTGOING' and letter.recipient:
                sms_text += f"\nTo: {letter.recipient[:30]}"

            # Add due date
            if letter.due_date:
                sms_text += f"\nDue: {letter.due_date.strftime('%Y-%m-%d')}"
                if letter.is_overdue:
                    sms_text += " OVERDUE"

            # Add assigned by
            if letter.created_by:
                assigned_by = letter.created_by.get_full_name() or letter.created_by.username
                sms_text += f"\nBy: {assigned_by[:20]}"

            # Add letter detail link
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', 'https://lms.pro.et')
            letter_url = f"{site_url}{letter.get_short_url()}"
            sms_text += f"\n{letter_url}"

            send_sms_notification(letter.assigned_person, 'New Letter Assigned', sms_text)
    except Exception as e:
        logger.error(f"Error sending SMS notification for letter assignment: {e}")


def send_sms_for_status_change(letter):
    """Send SMS notification when letter status changes to specific values."""
    old_status = getattr(letter, '_old_status', None)

    # Only notify for specific status changes
    status_changes_to_notify = ['RESPONDED', 'CLOSED', 'APPROVED', 'REJECTED']

    if old_status and letter.status in status_changes_to_notify and old_status != letter.status:
        try:
            # Notify the letter creator
            if letter.created_by:
                profile = getattr(letter.created_by, 'profile', None)
                if profile and profile.phone_number and profile.sms_notifications:
                    sms_text = (
                        f"AE LMS: Letter status updated\n"
                        f"Ref: {letter.reference_no}\n"
                        f"Status: {old_status} > {letter.status}\n"
                        f"Subject: {letter.subject[:50]}"
                    )

                    # Add letter detail link
                    from django.conf import settings
                    site_url = getattr(settings, 'SITE_URL', 'https://lms.pro.et')
                    letter_url = f"{site_url}{letter.get_short_url()}"
                    sms_text += f"\n{letter_url}"

                    send_sms_notification(letter.created_by, 'Status Update', sms_text)
        except Exception as e:
            logger.error(f"Error sending SMS notification for status change: {e}")
