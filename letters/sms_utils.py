"""AfroMessage SMS notification utilities for sending messages via AfroMessage API."""
import logging
from django.conf import settings
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _extract_error_message(result):
    """Extract a user-friendly error message from AfroMessage API response."""
    if not isinstance(result, dict):
        return str(result)
    resp_data = result.get('response')
    if isinstance(resp_data, dict):
        errors = resp_data.get('errors')
        if isinstance(errors, list) and errors:
            return " ".join(str(e) for e in errors)
        elif errors:
            return str(errors)
    return result.get('message') or result.get('error') or 'Unknown AfroMessage error'


def send_sms_with_result(to, message, sender=None):
    """
    Send an SMS via AfroMessage API and return (success, status_or_error_message).

    Args:
        to (str): Recipient phone number (Ethiopian format, e.g. +2519XXXXXXXX or 09XXXXXXXX)
        message (str): SMS text content
        sender (str, optional): Sender name. Uses settings default if not provided.

    Returns:
        tuple: (bool, str) - (True if sent, status or error message)
    """
    token = getattr(settings, 'AFROMESSAGE_API_TOKEN', None)
    if not token:
        logger.warning('AfroMessage API token not configured. Skipping SMS.')
        return False, 'AfroMessage API token not configured in system settings.'

    if not to:
        logger.warning('Recipient phone number not provided. Skipping SMS.')
        return False, 'Recipient phone number not provided.'

    if not message:
        logger.warning('SMS message content is empty. Skipping SMS.')
        return False, 'SMS message content is empty.'

    # Normalize phone number to Ethiopian format
    normalized_to = normalize_phone_number(to)
    if not normalized_to:
        logger.warning(f'Invalid Ethiopian phone number format: {to}')
        return False, f'Invalid Ethiopian phone number ({to}). Use format 09XXXXXXXX, 07XXXXXXXX, or +2519XXXXXXXX.'

    sender_name = sender or getattr(settings, 'AFROMESSAGE_SENDER_NAME', '')
    identifier_id = getattr(settings, 'AFROMESSAGE_IDENTIFIER_ID', '')
    base_url = getattr(settings, 'AFROMESSAGE_API_URL', 'https://api.afromessage.com/api/send')

    headers = {
        'Authorization': f'Bearer {token}',
    }

    params = {
        'to': normalized_to,
        'message': message,
    }
    if identifier_id:
        params['from'] = identifier_id
    if sender_name:
        params['sender'] = sender_name

    # Add callback URL if configured
    callback_url = getattr(settings, 'AFROMESSAGE_CALLBACK_URL', '')
    if callback_url:
        params['callback'] = callback_url

    try:
        response = requests.get(base_url, headers=headers, params=params, timeout=10)
        result = response.json()
        acknowledge = result.get('acknowledge', result.get('status', ''))

        if acknowledge in ('success', 'Success'):
            logger.info(f'SMS sent successfully to: {normalized_to}')
            return True, 'SMS sent successfully.'
        else:
            error_msg = _extract_error_message(result)
            logger.error(f'AfroMessage API error: {error_msg} | Response: {result}')
            return False, error_msg

    except requests.exceptions.Timeout:
        msg = 'AfroMessage API connection timed out. Please try again.'
        logger.error(msg)
        return False, msg
    except requests.exceptions.ConnectionError:
        msg = 'Connection to AfroMessage server failed. Please check internet connection.'
        logger.error(msg)
        return False, msg
    except requests.exceptions.RequestException as e:
        msg = f'Failed to send SMS: {str(e)}'
        logger.error(msg)
        return False, msg
    except ValueError as e:
        msg = 'Invalid response from AfroMessage API.'
        logger.error(msg)
        return False, msg


def send_sms(to, message, sender=None):
    """
    Send an SMS via AfroMessage API.

    Args:
        to (str): Recipient phone number (Ethiopian format, e.g. +2519XXXXXXXX or 09XXXXXXXX)
        message (str): SMS text content
        sender (str, optional): Sender name. Uses settings default if not provided.

    Returns:
        bool: True if message sent successfully, False otherwise
    """
    success, _ = send_sms_with_result(to, message, sender=sender)
    return success


def normalize_phone_number(phone):
    """
    Normalize an Ethiopian phone number to international format (+251XXXXXXXXX).

    Accepts Ethiopian mobile formats (Ethio Telecom and Safaricom):
        - 09XXXXXXXX or 07XXXXXXXX  -> +2519XXXXXXXX or +2517XXXXXXXX
        - 9XXXXXXXX or 7XXXXXXXX    -> +2519XXXXXXXX or +2517XXXXXXXX
        - +2519XXXXXXXX or +2517... -> +2519XXXXXXXX or +2517XXXXXXXX
        - 2519XXXXXXXX or 2517...   -> +2519XXXXXXXX or +2517XXXXXXXX

    Args:
        phone (str): Phone number in any Ethiopian format

    Returns:
        str: Normalized phone number or empty string if invalid
    """
    if not phone:
        return ''

    # Remove spaces, dashes, parentheses
    cleaned = str(phone).strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    # Extract 9-digit mobile suffix
    if cleaned.startswith('+251'):
        digits = cleaned[4:]
    elif cleaned.startswith('251'):
        digits = cleaned[3:]
    elif cleaned.startswith('0'):
        digits = cleaned[1:]
    else:
        digits = cleaned

    # Valid Ethiopian mobile numbers must have exactly 9 digits and start with 9 (Ethio Telecom) or 7 (Safaricom)
    if len(digits) == 9 and digits.isdigit() and digits[0] in ('9', '7'):
        return f'+251{digits}'

    return ''


def send_sms_notification(user, title, message, url=None):
    """
    Send a formatted SMS notification to a user.

    Args:
        user: User object
        title (str): Notification title
        message (str): Notification message
        url (str, optional): URL to include in the SMS

    Returns:
        bool: True if message sent successfully, False otherwise
    """
    try:
        profile = user.profile
        if not profile.phone_number:
            logger.info(f'User {user.username} has no phone number configured.')
            return False

        if not profile.sms_notifications:
            logger.info(f'User {user.username} has SMS notifications disabled.')
            return False

        # Format SMS (keep it concise for SMS)
        sms_text = f'{title}\n{message}'

        if url:
            sms_text += f'\n{url}'

        # SMS character limit awareness (160 chars for single SMS, 306 for concatenated)
        if len(sms_text) > 306:
            sms_text = sms_text[:303] + '...'

        return send_sms(profile.phone_number, sms_text)

    except Exception as e:
        logger.error(f'Error sending SMS notification to user {user.username}: {str(e)}')
        return False


def verify_phone_number(phone):
    """
    Verify if a phone number is valid by sending a test SMS.

    Args:
        phone (str): Phone number to verify

    Returns:
        bool: True if SMS sent successfully, False otherwise
    """
    test_message = 'AE LMS: SMS notifications are now enabled for your account.'
    return send_sms(phone, test_message)
