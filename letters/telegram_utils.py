"""Telegram notification utilities for sending messages via Telegram Bot API."""
import logging
import secrets
import string
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)
User = get_user_model()


def generate_connection_code():
    """Generate a unique connection code for Telegram linking."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(8))
        from .models import UserProfile
        if not UserProfile.objects.filter(telegram_connection_code=code).exists():
            return code


def send_telegram_message(chat_id, message, parse_mode='HTML'):
    """
    Send a message via Telegram Bot API.
    
    Args:
        chat_id (str): Telegram chat ID of the recipient
        message (str): Message content
        parse_mode (str): Parse mode for the message (HTML or Markdown)
    
    Returns:
        bool: True if message sent successfully, False otherwise
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning('Telegram bot token not configured. Skipping notification.')
        return False
    
    if not chat_id:
        logger.warning('Telegram chat ID not provided. Skipping notification.')
        return False
    
    url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage'
    
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        
        result = response.json()
        if result.get('ok'):
            logger.info(f'Telegram message sent successfully to chat_id: {chat_id}')
            return True
        else:
            logger.error(f'Telegram API error: {result.get("description", "Unknown error")}')
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f'Failed to send Telegram message: {str(e)}')
        return False


def send_telegram_notification(user, title, message, url=None):
    """
    Send a formatted notification to a user via Telegram.
    
    Args:
        user: User object
        title (str): Notification title
        message (str): Notification message
        url (str, optional): URL to include in the notification
    
    Returns:
        bool: True if message sent successfully, False otherwise
    """
    try:
        profile = user.profile
        if not profile.telegram_chat_id:
            logger.info(f'User {user.username} has no Telegram chat ID configured.')
            return False
        
        if not profile.telegram_notifications:
            logger.info(f'User {user.username} has Telegram notifications disabled.')
            return False
        
        # Format the message
        formatted_message = f"<b>{title}</b>\n\n{message}"
        
        if url:
            formatted_message += f"\n\n<a href='{url}'>View Details</a>"
        
        return send_telegram_message(profile.telegram_chat_id, formatted_message)
        
    except Exception as e:
        logger.error(f'Error sending Telegram notification to user {user.username}: {str(e)}')
        return False


def verify_telegram_chat_id(chat_id):
    """
    Verify if a chat ID is valid by sending a test message.
    
    Args:
        chat_id (str): Telegram chat ID to verify
    
    Returns:
        bool: True if chat ID is valid, False otherwise
    """
    test_message = "✅ Telegram notifications are now enabled for your account."
    return send_telegram_message(chat_id, test_message)


def handle_telegram_webhook(update):
    """
    Handle incoming Telegram webhook updates.
    
    Args:
        update (dict): Telegram update object
    
    Returns:
        dict: Response for the webhook
    """
    try:
        message = update.get('message', {})
        text = message.get('text', '').strip()
        chat_id = str(message.get('chat', {}).get('id', ''))
        
        if not text or not chat_id:
            return {'ok': True}
        
        # Handle /start command with token
        if text.startswith('/start '):
            token = text[7:].strip()  # Remove '/start '
            
            from .models import TelegramLinkToken
            try:
                link_token = TelegramLinkToken.objects.get(token=token)
                
                if link_token.is_valid:
                    # Link the chat ID
                    profile = link_token.user.profile
                    profile.telegram_chat_id = chat_id
                    profile.telegram_connected_at = timezone.now()
                    profile.telegram_notifications = True
                    profile.save()
                    
                    # Mark token as used
                    link_token.is_used = True
                    link_token.save()
                    
                    # Send confirmation message
                    welcome_msg = "✅ Connected! You'll now receive LMS notifications here."
                    send_telegram_message(chat_id, welcome_msg)
                    
                    logger.info(f"Telegram account {chat_id} connected to user {link_token.user.username}")
                else:
                    error_msg = "❌ This link has expired or is invalid. Please generate a new one from the LMS and try again."
                    send_telegram_message(chat_id, error_msg)
                    
            except TelegramLinkToken.DoesNotExist:
                error_msg = "❌ This link has expired or is invalid. Please generate a new one from the LMS and try again."
                send_telegram_message(chat_id, error_msg)
        
        # Handle /start command without token
        elif text == '/start':
            help_msg = (
                "🤖 Welcome to AE LMS Bot!\n\n"
                "To connect your Telegram account:\n"
                "1. Go to your profile on the LMS website\n"
                "2. Click 'Connect with Telegram'\n"
                "3. This will open this chat automatically\n\n"
                "Your account will be linked instantly!"
            )
            send_telegram_message(chat_id, help_msg)
        
        # Handle /help command
        elif text == '/help':
            help_msg = (
                "📚 Available commands:\n\n"
                "/start - Get started\n"
                "/help - Show this help message"
            )
            send_telegram_message(chat_id, help_msg)
        
        return {'ok': True}
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {str(e)}")
        return {'ok': False, 'error': str(e)}


def get_telegram_updates(offset=0, timeout=30):
    """
    Get updates from Telegram via polling (for local development).
    
    Args:
        offset (int): Offset to start from
        timeout (int): Long polling timeout in seconds
    
    Returns:
        dict: Updates from Telegram
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning('Telegram bot token not configured.')
        return None
    
    url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates'
    
    params = {
        'offset': offset,
        'timeout': timeout
    }
    
    try:
        response = requests.get(url, params=params, timeout=timeout + 5)
        response.raise_for_status()
        result = response.json()
        
        if result.get('ok'):
            return result.get('result', [])
        else:
            logger.error(f'Telegram polling error: {result.get("description", "Unknown error")}')
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f'Failed to poll Telegram: {str(e)}')
        return None
