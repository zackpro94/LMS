"""Unit tests for the Telegram bot /attach archive attachment flow."""
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from letters.models import Letter, UserProfile, SMSVerificationCode, Attachment
from letters.telegram_utils import (
    handle_telegram_webhook,
    _clear_session,
    STATE_AWAITING_PHONE,
    STATE_AWAITING_OTP,
    STATE_AWAITING_REF,
    STATE_AWAITING_ATTACHMENT,
    _get_session,
)

User = get_user_model()


class TelegramAttachFlowTestCase(TestCase):
    def setUp(self):
        self.chat_id = '123456789'
        _clear_session(self.chat_id)

        # Create user with profile & phone number
        self.user = User.objects.create_user(
            username='teststaff',
            password='Password123!',
            first_name='Abebe',
            last_name='Bikila'
        )
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.profile.phone_number = '0911223344'
        self.profile.save()

        # Create an old archive letter
        self.archive_letter = Letter.objects.create(
            subject='Old Contract Archive 1998',
            direction=Letter.INCOMING,
            date=timezone.now().date(),
            sender='Ministry of Construction',
            reference_no='AE/OLD/0042/98',
            is_old_archive=True,
            created_by=self.user
        )

    def tearDown(self):
        _clear_session(self.chat_id)

    @patch('letters.telegram_utils.delete_telegram_messages')
    @patch('letters.telegram_utils.send_telegram_message')
    @patch('letters.sms_utils.send_sms', return_value=True)
    def test_complete_attach_flow(self, mock_sms, mock_tg, mock_delete_msgs):
        """Test the entire conversational flow from /attach to upload to /done with message cleanup."""
        # 1. User sends /attach
        update1 = {
            'update_id': 1,
            'message': {
                'message_id': 101,
                'chat': {'id': int(self.chat_id)},
                'text': '/attach'
            }
        }
        res1 = handle_telegram_webhook(update1)
        self.assertTrue(res1.get('ok'))
        session = _get_session(self.chat_id)
        self.assertEqual(session.get('state'), STATE_AWAITING_PHONE)

        # 2. User enters registered phone number
        update2 = {
            'update_id': 2,
            'message': {
                'message_id': 102,
                'chat': {'id': int(self.chat_id)},
                'text': '0911223344'
            }
        }
        res2 = handle_telegram_webhook(update2)
        self.assertTrue(res2.get('ok'))
        session = _get_session(self.chat_id)
        self.assertEqual(session.get('state'), STATE_AWAITING_OTP)

        # Verify OTP was generated in DB
        otp_record = SMSVerificationCode.objects.filter(user=self.user, is_used=False).first()
        self.assertIsNotNone(otp_record)
        otp_code = otp_record.code

        # 3. User submits incorrect OTP
        update3_wrong = {
            'update_id': 3,
            'message': {
                'message_id': 103,
                'chat': {'id': int(self.chat_id)},
                'text': '000000'
            }
        }
        handle_telegram_webhook(update3_wrong)
        otp_record.refresh_from_db()
        self.assertEqual(otp_record.attempts, 1)

        # 4. User submits correct OTP -> Should trigger sensitive message cleanup
        update3_correct = {
            'update_id': 4,
            'message': {
                'message_id': 104,
                'chat': {'id': int(self.chat_id)},
                'text': otp_code
            }
        }
        res3 = handle_telegram_webhook(update3_correct)
        self.assertTrue(res3.get('ok'))
        self.assertTrue(mock_delete_msgs.called)
        session = _get_session(self.chat_id)
        self.assertEqual(session.get('state'), STATE_AWAITING_REF)
        self.assertEqual(session.get('authenticated_user_id'), self.user.id)

        # 5. User enters letter reference number
        update4 = {
            'update_id': 5,
            'message': {
                'message_id': 105,
                'chat': {'id': int(self.chat_id)},
                'text': 'AE/OLD/0042/98'
            }
        }
        res4 = handle_telegram_webhook(update4)
        self.assertTrue(res4.get('ok'))
        session = _get_session(self.chat_id)
        self.assertEqual(session.get('state'), STATE_AWAITING_ATTACHMENT)
        self.assertEqual(session.get('letter_id'), self.archive_letter.id)

        # 6. User sends a photo
        fake_photo_bytes = b'fake_jpeg_image_data_here'
        with patch('letters.telegram_utils._download_telegram_file', return_value=(fake_photo_bytes, 'photo.jpg')):
            update5 = {
                'update_id': 6,
                'message': {
                    'message_id': 106,
                    'chat': {'id': int(self.chat_id)},
                    'photo': [
                        {'file_id': 'small_photo', 'file_size': 100},
                        {'file_id': 'large_photo', 'file_size': 5000},
                    ]
                }
            }
            res5 = handle_telegram_webhook(update5)
            self.assertTrue(res5.get('ok'))

        # Check Attachment was created in DB
        attachments = Attachment.objects.filter(letter=self.archive_letter)
        self.assertEqual(attachments.count(), 1)
        self.assertEqual(attachments.first().uploaded_by, self.user)

        # 7. User sends /done -> Should trigger automatic session message cleanup
        mock_delete_msgs.reset_mock()
        update6 = {
            'update_id': 7,
            'message': {
                'message_id': 107,
                'chat': {'id': int(self.chat_id)},
                'text': '/done'
            }
        }
        res6 = handle_telegram_webhook(update6)
        self.assertTrue(res6.get('ok'))
        self.assertTrue(mock_delete_msgs.called)
        session = _get_session(self.chat_id)
        self.assertIsNone(session.get('state'))
        # User remains authenticated for 15 mins
        self.assertEqual(session.get('authenticated_user_id'), self.user.id)

    @patch('letters.telegram_utils.delete_telegram_messages')
    @patch('letters.telegram_utils.send_telegram_message')
    def test_clear_command(self, mock_tg, mock_delete_msgs):
        """Test /clear command deletes chat history."""
        update = {
            'update_id': 10,
            'message': {
                'message_id': 999,
                'chat': {'id': int(self.chat_id)},
                'text': '/clear'
            }
        }
        res = handle_telegram_webhook(update)
        self.assertTrue(res.get('ok'))
        self.assertTrue(mock_delete_msgs.called)

    @patch('letters.telegram_utils.send_telegram_message')
    def test_unregistered_phone(self, mock_tg):
        """Test submitting a phone number not registered in LMS."""
        update1 = {
            'update_id': 1,
            'message': {
                'chat': {'id': int(self.chat_id)},
                'text': '/attach'
            }
        }
        handle_telegram_webhook(update1)

        update2 = {
            'update_id': 2,
            'message': {
                'chat': {'id': int(self.chat_id)},
                'text': '0999999999'
            }
        }
        res = handle_telegram_webhook(update2)
        self.assertTrue(res.get('ok'))
        session = _get_session(self.chat_id)
        # Should stay on awaiting_phone
        self.assertEqual(session.get('state'), STATE_AWAITING_PHONE)
