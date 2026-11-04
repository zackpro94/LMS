"""Telegram notification utilities for sending messages via Telegram Bot API."""
import logging
import secrets
import string
import time
from io import BytesIO
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# In-memory session store for conversational flows
# Key: chat_id (str)  →  Value: dict with session data
# Sessions auto-expire after SESSION_TIMEOUT_MINUTES of inactivity.
# ---------------------------------------------------------------------------
_sessions = {}
SESSION_TIMEOUT_MINUTES = 15

# Session states
STATE_AWAITING_PHONE = 'awaiting_phone'
STATE_AWAITING_OTP = 'awaiting_otp'
STATE_AWAITING_REF = 'awaiting_ref'
STATE_AWAITING_ATTACHMENT = 'awaiting_attachment'


def _get_session(chat_id):
    """Get an active session for a chat_id, or None if expired/missing."""
    session = _sessions.get(chat_id)
    if session:
        elapsed = (timezone.now() - session['last_activity']).total_seconds()
        if elapsed > SESSION_TIMEOUT_MINUTES * 60:
            _sessions.pop(chat_id, None)
            return None
        return session
    return None


def _set_session(chat_id, **kwargs):
    """Create or update a session for a chat_id."""
    chat_id = str(chat_id)
    session = _sessions.get(chat_id, {})
    session.update(kwargs)
    session['last_activity'] = timezone.now()
    _sessions[chat_id] = session


def _clear_session(chat_id):
    """Remove a session for a chat_id."""
    _sessions.pop(str(chat_id), None)


def _track_message(chat_id, message_id):
    """Track a message_id for the chat_id so it can be auto-deleted later."""
    if not message_id:
        return
    chat_id = str(chat_id)
    session = _sessions.get(chat_id)
    if session is None:
        _sessions[chat_id] = {
            'last_activity': timezone.now(),
            'tracked_message_ids': []
        }
        session = _sessions[chat_id]
    if 'tracked_message_ids' not in session:
        session['tracked_message_ids'] = []
    if message_id not in session['tracked_message_ids']:
        session['tracked_message_ids'].append(message_id)


def _cleanup_tracked_messages(chat_id, keep_last=0):
    """
    Delete tracked messages from Telegram chat for privacy and cleanliness.
    
    Args:
        chat_id: Telegram chat ID
        keep_last (int): Number of most recent messages to keep (default 0 = delete all)
    """
    chat_id = str(chat_id)
    session = _sessions.get(chat_id)
    if not session or not session.get('tracked_message_ids'):
        return

    all_ids = session['tracked_message_ids']
    if keep_last > 0 and len(all_ids) > keep_last:
        to_delete = all_ids[:-keep_last]
        session['tracked_message_ids'] = all_ids[-keep_last:]
    else:
        to_delete = list(all_ids)
        session['tracked_message_ids'] = []

    if to_delete:
        delete_telegram_messages(chat_id, to_delete)


# ---------------------------------------------------------------------------
# Message deletion utilities
# ---------------------------------------------------------------------------

def delete_telegram_message(chat_id, message_id):
    """
    Delete a single message from a Telegram chat.
    
    Args:
        chat_id (str): Telegram chat ID
        message_id (int): Message ID to delete
    
    Returns:
        bool: True if deleted, False otherwise
    """
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id or not message_id:
        return False
    url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/deleteMessage'
    try:
        response = requests.post(
            url,
            json={'chat_id': str(chat_id), 'message_id': int(message_id)},
            timeout=5
        )
        return response.json().get('ok', False)
    except Exception as e:
        logger.warning(f"Failed to delete Telegram message {message_id}: {e}")
        return False


def delete_telegram_messages(chat_id, message_ids):
    """
    Delete multiple messages from a Telegram chat (bulk or one-by-one).
    
    Args:
        chat_id (str): Telegram chat ID
        message_ids (list): List of message IDs to delete
    
    Returns:
        bool: True if call completed
    """
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id or not message_ids:
        return False

    valid_ids = [int(mid) for mid in set(message_ids) if mid]
    if not valid_ids:
        return False

    # Telegram deleteMessages supports batches of up to 100
    batch_size = 100
    for i in range(0, len(valid_ids), batch_size):
        batch = valid_ids[i:i + batch_size]
        url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/deleteMessages'
        try:
            resp = requests.post(
                url,
                json={'chat_id': str(chat_id), 'message_ids': batch},
                timeout=5
            )
            result = resp.json()
            if not result.get('ok'):
                for mid in batch:
                    delete_telegram_message(chat_id, mid)
        except Exception:
            for mid in batch:
                delete_telegram_message(chat_id, mid)
    return True


# ---------------------------------------------------------------------------
# Existing utility functions (unchanged)
# ---------------------------------------------------------------------------

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
        int/bool: Message ID if sent successfully (truthy), False otherwise
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
            msg_id = result.get('result', {}).get('message_id')
            if msg_id:
                _track_message(chat_id, msg_id)
            return msg_id or True
        else:
            logger.error(f'Telegram API error: {result.get("description", "Unknown error")}')
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f'Failed to send Telegram message: {str(e)}')
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


# ---------------------------------------------------------------------------
# Telegram file download helper
# ---------------------------------------------------------------------------

def _download_telegram_file(file_id):
    """
    Download a file from Telegram servers.
    
    Args:
        file_id (str): Telegram file_id
    
    Returns:
        tuple: (file_bytes, file_name) or (None, None) on failure
    """
    try:
        # Step 1: Get file path from Telegram
        url = f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getFile'
        response = requests.get(url, params={'file_id': file_id}, timeout=10)
        result = response.json()
        
        if not result.get('ok'):
            logger.error(f'Failed to get file info: {result}')
            return None, None
        
        file_path = result['result']['file_path']
        file_name = file_path.split('/')[-1]
        
        # Step 2: Download the file
        download_url = f'https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}'
        file_response = requests.get(download_url, timeout=30)
        file_response.raise_for_status()
        
        return file_response.content, file_name
        
    except Exception as e:
        logger.error(f'Failed to download Telegram file: {str(e)}')
        return None, None


# ---------------------------------------------------------------------------
# /attach flow handlers
# ---------------------------------------------------------------------------

def _handle_attach_command(chat_id):
    """Start the /attach flow — ask for phone number or resume active session."""
    session = _get_session(chat_id)
    # If the user is already authenticated in this session, skip straight to reference number
    if session and session.get('authenticated_user_id'):
        user_id = session.get('authenticated_user_id')
        try:
            user = User.objects.get(id=user_id)
            display_name = user.get_full_name() or user.username
            _set_session(chat_id, state=STATE_AWAITING_REF, user_id=user.id, letter_id=None, upload_count=0)
            send_telegram_message(
                chat_id,
                f"📎 <b>Archive Attachment Upload</b>\n"
                f"👤 Authenticated as: <b>{display_name}</b>\n\n"
                "Please enter the letter <b>Reference Number</b>:\n"
                "<i>(e.g. AE/HR/0012/24)</i>\n\n"
                "Type /logout to switch accounts, or /cancel to cancel."
            )
            return
        except User.DoesNotExist:
            pass

    _set_session(chat_id, state=STATE_AWAITING_PHONE, user=None, letter=None, upload_count=0)
    send_telegram_message(
        chat_id,
        "📎 <b>Archive Attachment Upload</b>\n\n"
        "📱 Please enter your registered phone number to verify your identity.\n"
        "<i>(e.g. 0912345678 or 0712345678)</i>\n\n"
        "Type /cancel to cancel anytime."
    )


def _handle_phone_input(chat_id, phone_text):
    """Handle phone number input — look up user and send OTP."""
    from .models import UserProfile, SMSVerificationCode
    from .sms_utils import normalize_phone_number, send_sms

    raw = phone_text.strip()
    normalized = normalize_phone_number(raw)
    digits_only = ''.join(c for c in raw if c.isdigit())

    # Build potential phone representations to match various DB formats
    candidates = set()
    if normalized:
        candidates.add(normalized)
        if normalized.startswith('+251'):
            suffix = normalized[4:]
            candidates.add(suffix)
            candidates.add(f"0{suffix}")
            candidates.add(f"251{suffix}")
    if raw:
        candidates.add(raw)
    if digits_only:
        candidates.add(digits_only)
        if digits_only.startswith('251') and len(digits_only) == 12:
            candidates.add(f"+{digits_only}")
            candidates.add(f"0{digits_only[3:]}")
            candidates.add(digits_only[3:])
        elif digits_only.startswith('0') and len(digits_only) == 10:
            candidates.add(f"+251{digits_only[1:]}")
            candidates.add(f"251{digits_only[1:]}")
            candidates.add(digits_only[1:])

    # Look up user by phone number
    profile = UserProfile.objects.filter(phone_number__in=list(candidates)).select_related('user').first()
    if not profile or not profile.user:
        send_telegram_message(
            chat_id,
            "❌ No account found with this phone number.\n"
            "Make sure your phone number is registered in your LMS profile."
        )
        return

    user = profile.user
    sms_target = normalized if normalized else (f"+251{digits_only[-9:]}" if len(digits_only) >= 9 else raw)

    # Generate and send OTP
    try:
        otp = SMSVerificationCode.generate_code(user, sms_target)
        sms_sent = send_sms(sms_target, f"AE LMS: Your verification code is {otp.code}. Expires in 5 minutes.")
        
        if sms_sent:
            _set_session(chat_id, state=STATE_AWAITING_OTP, user_id=user.id, phone=sms_target)
            send_telegram_message(
                chat_id,
                f"🔐 OTP sent via SMS to <b>{raw}</b>\n\n"
                "Enter the 6-digit code:"
            )
        else:
            send_telegram_message(
                chat_id,
                "❌ Failed to send OTP via SMS. Please try again later."
            )
    except Exception as e:
        logger.error(f"Error generating/sending OTP for Telegram attach: {e}")
        send_telegram_message(
            chat_id,
            "❌ An error occurred sending the OTP. Please try again."
        )


def _handle_otp_input(chat_id, otp_text):
    """Handle OTP verification."""
    from .models import SMSVerificationCode

    session = _get_session(chat_id)
    if not session:
        send_telegram_message(chat_id, "❌ Session expired. Please start again with /attach")
        return

    user_id = session.get('user_id')
    if not user_id:
        send_telegram_message(chat_id, "❌ Session error. Please start again with /attach")
        _clear_session(chat_id)
        return

    user = User.objects.get(id=user_id)
    code_text = otp_text.strip()

    # Find the latest valid OTP for this user
    try:
        otp_record = SMSVerificationCode.objects.filter(
            user=user,
            is_used=False,
        ).order_by('-created_at').first()

        if not otp_record or not otp_record.is_valid:
            send_telegram_message(
                chat_id,
                "❌ OTP has expired. Please start again with /attach"
            )
            _clear_session(chat_id)
            return

        if otp_record.code != code_text:
            otp_record.attempts += 1
            otp_record.save()
            remaining = 5 - otp_record.attempts
            if remaining <= 0:
                otp_record.is_used = True
                otp_record.save()
                send_telegram_message(
                    chat_id,
                    "❌ Too many failed attempts. Please start again with /attach"
                )
                _clear_session(chat_id)
            else:
                send_telegram_message(
                    chat_id,
                    f"❌ Incorrect code. {remaining} attempt(s) remaining.\n"
                    "Enter the 6-digit code:"
                )
            return

        # OTP is correct — mark as used
        otp_record.is_used = True
        otp_record.save()

        # Automatically delete phone number & OTP messages from chat history for privacy
        _cleanup_tracked_messages(chat_id)

        # Get display name
        display_name = user.get_full_name() or user.username

        _set_session(
            chat_id,
            state=STATE_AWAITING_REF,
            user_id=user.id,
            authenticated_user_id=user.id,
            upload_count=0
        )
        send_telegram_message(
            chat_id,
            f"✅ Verified! Welcome, <b>{display_name}</b>.\n\n"
            "📎 Enter the letter <b>Reference Number</b>:\n"
            "<i>(e.g. AE/HR/0012/24)</i>"
        )

    except Exception as e:
        logger.error(f"Error verifying OTP in Telegram: {e}")
        send_telegram_message(chat_id, "❌ An error occurred. Please try again with /attach")
        _clear_session(chat_id)


def _handle_ref_input(chat_id, ref_text):
    """Handle reference number lookup."""
    from .models import Letter

    session = _get_session(chat_id)
    if not session:
        send_telegram_message(chat_id, "❌ Session expired. Please start again with /attach")
        return

    ref = ref_text.strip()

    try:
        letter = Letter.objects.filter(
            reference_no__iexact=ref,
            is_old_archive=True
        ).first()

        if not letter:
            # Try a looser match (contains)
            letter = Letter.objects.filter(
                reference_no__icontains=ref,
                is_old_archive=True
            ).first()

        if not letter:
            send_telegram_message(
                chat_id,
                f"❌ No old archive letter found with ref: <b>{ref}</b>\n\n"
                "Please check and try again, or type /cancel to cancel."
            )
            return

        # Found it — show details and ask for attachment
        direction_emoji = "📥" if letter.direction == 'INCOMING' else "📤"
        contact = ""
        if letter.direction == 'INCOMING' and letter.sender:
            contact = f"\n👤 From: {letter.sender}"
        elif letter.direction == 'OUTGOING' and letter.recipient:
            contact = f"\n👤 To: {letter.recipient}"

        existing_count = letter.attachments.count()
        existing_info = f"\n📁 Existing attachments: {existing_count}" if existing_count > 0 else ""

        _set_session(chat_id, state=STATE_AWAITING_ATTACHMENT, letter_id=letter.id, upload_count=0)
        send_telegram_message(
            chat_id,
            f"✅ <b>Letter Found!</b>\n\n"
            f"{direction_emoji} <b>{letter.reference_no}</b>\n"
            f"📄 {letter.subject}{contact}\n"
            f"📅 {letter.date or 'No date'}{existing_info}\n\n"
            "📷 Now send me the <b>photo(s)</b> or <b>document(s)</b> to attach.\n\n"
            "Type /done when finished, or /cancel to cancel."
        )

    except Exception as e:
        logger.error(f"Error looking up letter ref in Telegram: {e}")
        send_telegram_message(chat_id, "❌ An error occurred. Please try again.")


def _handle_attachment_upload(chat_id, message):
    """Handle photo or document upload from Telegram."""
    from .models import Letter, Attachment

    session = _get_session(chat_id)
    if not session:
        send_telegram_message(chat_id, "❌ Session expired. Please start again with /attach")
        return

    letter_id = session.get('letter_id')
    user_id = session.get('user_id')

    if not letter_id or not user_id:
        send_telegram_message(chat_id, "❌ Session error. Please start again with /attach")
        _clear_session(chat_id)
        return

    try:
        letter = Letter.objects.get(id=letter_id)
        user = User.objects.get(id=user_id)
    except (Letter.DoesNotExist, User.DoesNotExist):
        send_telegram_message(chat_id, "❌ Letter or user not found. Please start again with /attach")
        _clear_session(chat_id)
        return

    file_id = None
    file_name = None

    # Handle photo (Telegram sends multiple sizes, pick the largest)
    if message.get('photo'):
        photos = message['photo']
        largest = max(photos, key=lambda p: p.get('file_size', 0))
        file_id = largest['file_id']
        # Photos don't have a file_name, generate one
        file_name = f"telegram_photo_{int(time.time())}.jpg"

    # Handle document (PDF, images sent as file, etc.)
    elif message.get('document'):
        doc = message['document']
        file_id = doc['file_id']
        file_name = doc.get('file_name', f"telegram_doc_{int(time.time())}")
        
        # Check file size (Telegram Bot API limit is 20MB for downloads)
        file_size = doc.get('file_size', 0)
        if file_size > 20 * 1024 * 1024:
            send_telegram_message(
                chat_id,
                "❌ File is too large (max 20MB). Please send a smaller file."
            )
            return
    else:
        send_telegram_message(
            chat_id,
            "❌ Please send a <b>photo</b> or <b>document</b>.\n"
            "Other message types are not supported."
        )
        return

    # Download from Telegram
    file_bytes, original_name = _download_telegram_file(file_id)
    if not file_bytes:
        send_telegram_message(chat_id, "❌ Failed to download the file. Please try again.")
        return

    # Save as Attachment
    try:
        content_file = ContentFile(file_bytes, name=file_name)
        attachment = Attachment(
            letter=letter,
            uploaded_by=user,
        )
        attachment.file.save(file_name, content_file, save=False)
        attachment.save()

        upload_count = session.get('upload_count', 0) + 1
        _set_session(chat_id, upload_count=upload_count)

        total_attachments = letter.attachments.count()
        send_telegram_message(
            chat_id,
            f"✅ Attachment <b>#{upload_count}</b> saved!\n"
            f"📁 <i>{file_name}</i>\n"
            f"📊 Total attachments on this letter: {total_attachments}\n\n"
            "Send more files, or type /done to finish."
        )

        # Log the action
        from .models import ActionLog
        ActionLog.objects.create(
            letter=letter,
            action=f"Attachment '{file_name}' uploaded via Telegram bot",
            action_by=user,
            notes=f"Uploaded via Telegram by {user.get_full_name() or user.username}"
        )

    except Exception as e:
        logger.error(f"Error saving Telegram attachment: {e}")
        send_telegram_message(chat_id, "❌ Failed to save the attachment. Please try again.")


def _handle_done_command(chat_id):
    """Finish the attachment upload session and clean up chat history."""
    session = _get_session(chat_id)
    upload_count = session.get('upload_count', 0) if session else 0
    auth_user_id = session.get('authenticated_user_id') if session else None

    # Automatically clean up intermediate prompts and uploads from chat history
    _cleanup_tracked_messages(chat_id)

    if upload_count > 0:
        send_telegram_message(
            chat_id,
            f"✅ <b>Done!</b> {upload_count} attachment(s) uploaded successfully.\n\n"
            "🧹 <i>Chat history has been automatically cleaned up.</i>\n\n"
            "Use /attach to upload more to another letter, or /logout to log out."
        )
    else:
        send_telegram_message(
            chat_id,
            "ℹ️ No attachments were uploaded.\n\n"
            "🧹 <i>Chat history cleaned up.</i>\n\n"
            "Use /attach to start again."
        )
    if auth_user_id:
        _set_session(chat_id, state=None, letter_id=None, upload_count=0, authenticated_user_id=auth_user_id, tracked_message_ids=[])
    else:
        _clear_session(chat_id)


def _handle_cancel_command(chat_id):
    """Cancel the current operation without logging out and clean up chat history."""
    session = _get_session(chat_id)
    auth_user_id = session.get('authenticated_user_id') if session else None

    # Automatically clean up cancelled interaction messages
    _cleanup_tracked_messages(chat_id)

    if auth_user_id:
        _set_session(chat_id, state=None, letter_id=None, upload_count=0, authenticated_user_id=auth_user_id, tracked_message_ids=[])
    else:
        _clear_session(chat_id)
    send_telegram_message(
        chat_id,
        "❌ Operation cancelled.\n\n"
        "🧹 <i>Chat history cleaned up.</i>\n\n"
        "Use /attach to start again."
    )


def _handle_logout_command(chat_id):
    """Log out, clean up chat, and completely clear session."""
    _cleanup_tracked_messages(chat_id)
    _clear_session(chat_id)
    send_telegram_message(
        chat_id,
        "👋 You have been logged out.\n\n"
        "🧹 <i>Chat history cleaned up.</i>\n\n"
        "Use /attach to authenticate with phone number and OTP when needed."
    )


def _handle_clear_command(chat_id):
    """Manually clear tracked chat messages."""
    _cleanup_tracked_messages(chat_id)
    send_telegram_message(
        chat_id,
        "🧹 <i>Chat history cleared.</i>"
    )


# ---------------------------------------------------------------------------
# Main webhook handler (updated)
# ---------------------------------------------------------------------------

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
        
        if not chat_id:
            return {'ok': True}

        # Track any incoming user message so it can be auto-deleted
        user_msg_id = message.get('message_id')
        if user_msg_id:
            _track_message(chat_id, user_msg_id)

        # ------------------------------------------------------------------
        # Global commands (always available)
        # ------------------------------------------------------------------
        if text == '/clear':
            _handle_clear_command(chat_id)
            return {'ok': True}

        if text == '/logout':
            _handle_logout_command(chat_id)
            return {'ok': True}

        if text == '/cancel':
            _handle_cancel_command(chat_id)
            return {'ok': True}

        if text == '/done':
            session = _get_session(chat_id)
            if session and session.get('state') == STATE_AWAITING_ATTACHMENT:
                _handle_done_command(chat_id)
            else:
                send_telegram_message(chat_id, "ℹ️ Nothing to finish. Use /attach to start uploading.")
            return {'ok': True}

        # ------------------------------------------------------------------
        # /attach command — start the attachment upload flow
        # ------------------------------------------------------------------
        if text == '/attach':
            _handle_attach_command(chat_id)
            return {'ok': True}

        # ------------------------------------------------------------------
        # Handle active session states
        # ------------------------------------------------------------------
        session = _get_session(chat_id)
        if session:
            state = session.get('state')

            if state == STATE_AWAITING_PHONE and text:
                _handle_phone_input(chat_id, text)
                return {'ok': True}

            if state == STATE_AWAITING_OTP and text:
                _handle_otp_input(chat_id, text)
                return {'ok': True}

            if state == STATE_AWAITING_REF and text:
                _handle_ref_input(chat_id, text)
                return {'ok': True}

            if state == STATE_AWAITING_ATTACHMENT:
                # Check if user sent a photo or document
                if message.get('photo') or message.get('document'):
                    _handle_attachment_upload(chat_id, message)
                    return {'ok': True}
                elif text:
                    send_telegram_message(
                        chat_id,
                        "📷 Please send a <b>photo</b> or <b>document</b>.\n"
                        "Type /done to finish, or /cancel to cancel."
                    )
                    return {'ok': True}

        # ------------------------------------------------------------------
        # Existing commands (no active session)
        # ------------------------------------------------------------------

        if not text:
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
                "📎 Use /attach to upload archive letter attachments\n\n"
                "Your account will be linked instantly!"
            )
            send_telegram_message(chat_id, help_msg)
        
        # Handle /help command
        elif text == '/help':
            help_msg = (
                "📚 <b>Available commands:</b>\n\n"
                "/start - Get started with AE LMS Bot\n"
                "/attach - Upload attachments to old archive letters\n"
                "/done - Finish upload session\n"
                "/cancel - Cancel current operation\n"
                "/clear - Clear chat history\n"
                "/logout - Log out from active upload session\n"
                "/help - Show this help message"
            )
            send_telegram_message(chat_id, help_msg)
        
        return {'ok': True}
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {str(e)}")
        return {'ok': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Polling helper (unchanged)
# ---------------------------------------------------------------------------

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
