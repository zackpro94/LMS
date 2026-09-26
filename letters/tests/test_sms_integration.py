"""Tests for AfroMessage SMS notification integration."""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from letters.models import UserProfile, Letter, Department, Category
from letters.sms_utils import normalize_phone_number, send_sms, send_sms_notification, verify_phone_number


class PhoneNumberNormalizationTests(TestCase):
    """Test Ethiopian phone number normalization."""

    def test_local_09_format(self):
        """09XXXXXXXX should be normalized to +2519XXXXXXXX."""
        self.assertEqual(normalize_phone_number('0912345678'), '+251912345678')

    def test_local_07_format(self):
        """07XXXXXXXX (Safaricom) should be normalized to +2517XXXXXXXX."""
        self.assertEqual(normalize_phone_number('0712345678'), '+251712345678')

    def test_international_with_plus(self):
        """+2519XXXXXXXX should remain unchanged."""
        self.assertEqual(normalize_phone_number('+251912345678'), '+251912345678')

    def test_international_without_plus(self):
        """2519XXXXXXXX should have + added."""
        self.assertEqual(normalize_phone_number('251912345678'), '+251912345678')

    def test_with_spaces_and_dashes(self):
        """Formatted numbers should be cleaned and normalized."""
        self.assertEqual(normalize_phone_number('0912 34 56 78'), '+251912345678')
        self.assertEqual(normalize_phone_number('0912-34-56-78'), '+251912345678')
        self.assertEqual(normalize_phone_number('+251 912-345-678'), '+251912345678')

    def test_invalid_numbers(self):
        """Invalid phone numbers should return empty string."""
        self.assertEqual(normalize_phone_number(''), '')
        self.assertEqual(normalize_phone_number(None), '')
        self.assertEqual(normalize_phone_number('12345'), '')
        self.assertEqual(normalize_phone_number('09123456'), '')  # Too short
        self.assertEqual(normalize_phone_number('091234567890'), '')  # Too long
        self.assertEqual(normalize_phone_number('0812345678'), '')  # Invalid prefix


class SendSmsApiTests(TestCase):
    """Test AfroMessage SMS API sender."""

    @override_settings(AFROMESSAGE_API_TOKEN=None)
    def test_token_missing_skips_sms(self):
        """When AFROMESSAGE_API_TOKEN is not set, SMS should be skipped gracefully."""
        result = send_sms('0912345678', 'Test message')
        self.assertFalse(result)

    @override_settings(AFROMESSAGE_API_TOKEN='test-token', AFROMESSAGE_SENDER_NAME='AELMS')
    @patch('requests.get')
    def test_successful_sms(self, mock_get):
        """Successful API response should return True."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'acknowledge': 'success',
            'response': {'status': 'sent'}
        }
        mock_get.return_value = mock_response

        result = send_sms('0912345678', 'Hello LMS')
        self.assertTrue(result)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn('Authorization', kwargs['headers'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(kwargs['params']['to'], '+251912345678')
        self.assertEqual(kwargs['params']['message'], 'Hello LMS')

    @override_settings(AFROMESSAGE_API_TOKEN='test-token')
    @patch('requests.get')
    def test_failed_sms_api_error(self, mock_get):
        """API error response should return False."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'acknowledge': 'error',
            'message': 'Insufficient balance'
        }
        mock_get.return_value = mock_response

        result = send_sms('0912345678', 'Test message')
        self.assertFalse(result)

    @override_settings(AFROMESSAGE_API_TOKEN='test-token')
    def test_invalid_phone_skips_sms(self):
        """Invalid phone should return False without making HTTP call."""
        result = send_sms('invalid', 'Test message')
        self.assertFalse(result)


class SmsNotificationServiceTests(TestCase):
    """Test user notification helper with UserProfile."""

    def setUp(self):
        self.user = User.objects.create_user(username='smsuser', password='password123')
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)

    def test_no_phone_configured(self):
        """User without phone number should not receive SMS."""
        self.profile.phone_number = None
        self.profile.sms_notifications = True
        self.profile.save()

        result = send_sms_notification(self.user, 'Title', 'Message')
        self.assertFalse(result)

    def test_notifications_disabled(self):
        """User with notifications disabled should not receive SMS."""
        self.profile.phone_number = '+251912345678'
        self.profile.sms_notifications = False
        self.profile.save()

        result = send_sms_notification(self.user, 'Title', 'Message')
        self.assertFalse(result)

    @override_settings(AFROMESSAGE_API_TOKEN='test-token')
    @patch('letters.sms_utils.send_sms')
    def test_active_notifications_sends_sms(self, mock_send_sms):
        """User with phone and notifications enabled should receive SMS."""
        self.profile.phone_number = '+251912345678'
        self.profile.sms_notifications = True
        self.profile.save()
        mock_send_sms.return_value = True

        result = send_sms_notification(self.user, 'New Letter', 'Ref 123 assigned')
        self.assertTrue(result)
        mock_send_sms.assert_called_once()


class SmsViewsTests(TestCase):
    """Test SMS settings and test views."""

    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='secretpassword')
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.client.login(username='tester', password='secretpassword')

    def test_save_valid_phone_settings(self):
        """SmsSettingsView should validate and save phone number."""
        response = self.client.post(
            reverse('letters:sms_settings'),
            data=json.dumps({
                'phone_number': '0912345678',
                'enabled': True
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['phone_number'], '+251912345678')

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.phone_number, '+251912345678')
        self.assertTrue(self.profile.sms_notifications)

    def test_save_invalid_phone_fails(self):
        """SmsSettingsView should reject invalid phone numbers."""
        response = self.client.post(
            reverse('letters:sms_settings'),
            data=json.dumps({
                'phone_number': '12345',
                'enabled': True
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])

    @override_settings(AFROMESSAGE_API_TOKEN='test-token')
    @patch('letters.sms_utils.send_sms_with_result')
    def test_send_test_sms(self, mock_send_sms_with_result):
        """TestSmsView should send a test SMS to normalized number."""
        mock_send_sms_with_result.return_value = (True, 'SMS sent successfully.')
        self.profile.phone_number = '+251912345678'
        self.profile.sms_notifications = True
        self.profile.save()

        response = self.client.post(
            reverse('letters:test_sms'),
            data=json.dumps({'phone_number': '0912345678'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        mock_send_sms_with_result.assert_called_once()

    def test_disconnect_sms(self):
        """DisconnectSmsView should reset phone and notification flag."""
        self.profile.phone_number = '+251912345678'
        self.profile.sms_notifications = True
        self.profile.save()

        response = self.client.post(reverse('letters:disconnect_sms'))
        self.assertEqual(response.status_code, 200)

        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.phone_number)
        self.assertFalse(self.profile.sms_notifications)


class StaffRegistrationSmsTests(TestCase):
    """Test phone number support on staff registration form."""

    def test_staff_form_valid_phone_saves_to_profile(self):
        """StaffForm should normalize phone number and save it to UserProfile."""
        from letters.forms import StaffForm

        form_data = {
            'username': 'newstaff1',
            'first_name': 'Abebe',
            'last_name': 'Kebede',
            'email': 'abebe@example.com',
            'password': 'strongpassword123',
            'role': 'dept_staff',
            'phone_number': '0911526889',
            'sms_notifications': True,
            'is_active': True,
        }
        form = StaffForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()

        self.assertEqual(user.username, 'newstaff1')
        profile = user.profile
        self.assertEqual(profile.phone_number, '+251911526889')
        self.assertTrue(profile.sms_notifications)

    def test_staff_form_invalid_phone_rejected(self):
        """StaffForm should reject invalid phone numbers."""
        from letters.forms import StaffForm

        form_data = {
            'username': 'newstaff2',
            'password': 'strongpassword123',
            'role': 'dept_staff',
            'phone_number': 'invalid-number',
            'is_active': True,
        }
        form = StaffForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('phone_number', form.errors)

    def test_staff_form_prepopulates_existing_phone(self):
        """StaffForm should pre-populate existing phone number when editing user."""
        from letters.forms import StaffForm

        user = User.objects.create_user(username='existingstaff', password='pwd')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.phone_number = '+251911526889'
        profile.sms_notifications = True
        profile.save()

        form = StaffForm(instance=user)
        self.assertEqual(form.fields['phone_number'].initial, '+251911526889')
        self.assertTrue(form.fields['sms_notifications'].initial)

