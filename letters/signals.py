from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Letter, Notification, ActionLog
import json

try:
    channel_layer = get_channel_layer()
    CHANNELS_AVAILABLE = True
except Exception:
    channel_layer = None
    CHANNELS_AVAILABLE = False


@receiver(post_save, sender=Letter)
def letter_saved(sender, instance, created, **kwargs):
    """Send real-time notification when a letter is created or updated."""
    if created:
        # Notify relevant users about new letter
        notify_users_about_letter(instance, 'created')
    else:
        # Notify about letter update
        notify_users_about_letter(instance, 'updated')


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
