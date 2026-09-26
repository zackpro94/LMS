"""Tests for Super Admin Custom SMS Broadcast feature."""
import json
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.contrib.auth.models import User, Group
from django.urls import reverse

from letters.models import UserProfile, Department, CustomSMSLog


class CustomSMSPermissionTests(TestCase):
    """Test access control for Custom SMS feature (Super Admin only)."""

    def setUp(self):
        # Regular user
        self.regular_user = User.objects.create_user(
            username='regularuser', password='password123'
        )
        UserProfile.objects.create(user=self.regular_user, phone_number='+251911111111')

        # Admin group user (not superuser)
        self.admin_group_user = User.objects.create_user(
            username='admingroupuser', password='password123'
        )
        admin_group, _ = Group.objects.get_or_create(name='Admin')
        self.admin_group_user.groups.add(admin_group)
        UserProfile.objects.create(user=self.admin_group_user, phone_number='+251922222222')

        # Superuser
        self.superuser = User.objects.create_superuser(
            username='superuser', password='password123', email='super@example.com'
        )
        UserProfile.objects.create(user=self.superuser, phone_number='+251933333333')

        self.url = reverse('letters:custom_sms')

    def test_anonymous_redirected_to_login(self):
        """Unauthenticated user should be redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_regular_user_forbidden(self):
        """Regular authenticated user should get 403 Forbidden."""
        self.client.login(username='regularuser', password='password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_admin_group_user_forbidden_if_not_superuser(self):
        """Staff in Admin group but not superuser should get 403 Forbidden."""
        self.client.login(username='admingroupuser', password='password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_access_get(self):
        """Superuser should successfully load custom SMS broadcast page."""
        self.client.login(username='superuser', password='password123')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin_dashboard/custom_sms.html')
        self.assertContains(response, 'Custom SMS Broadcast')
        self.assertContains(response, 'Super Admin Only')


class CustomSMSBroadcastTests(TestCase):
    """Test broadcast functionality and AfroMessage delivery logging."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='superuser', password='password123', email='super@example.com'
        )
        UserProfile.objects.create(user=self.superuser, phone_number='+251933333333')

        # Create department
        self.dept = Department.objects.create(name='Legal', code='LEG')

        # Staff with phone
        self.staff1 = User.objects.create_user(
            username='staff1', first_name='John', last_name='Doe', password='password123'
        )
        self.dept.users.add(self.staff1)
        UserProfile.objects.create(user=self.staff1, phone_number='+251912345678')

        # Staff without phone
        self.staff2 = User.objects.create_user(
            username='staff2', first_name='Jane', last_name='Smith', password='password123'
        )
        self.dept.users.add(self.staff2)
        UserProfile.objects.create(user=self.staff2, phone_number=None)

        self.url = reverse('letters:custom_sms')
        self.client.login(username='superuser', password='password123')

    @patch('letters.views.send_sms_with_result')
    def test_broadcast_to_all_staff(self, mock_send):
        """Sending to all staff should target only staff with registered phone numbers."""
        mock_send.return_value = (True, 'SMS sent successfully.')

        data = {
            'recipient_mode': 'all_staff',
            'message': 'Hello everyone, urgent team meeting at 3 PM.',
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Check mock calls - superuser (+251933333333) and staff1 (+251912345678) have phones, staff2 has None
        self.assertEqual(mock_send.call_count, 2)

        # Check CustomSMSLog record
        log = CustomSMSLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.sender, self.superuser)
        self.assertEqual(log.message, 'Hello everyone, urgent team meeting at 3 PM.')
        self.assertEqual(log.total_recipients, 2)
        self.assertEqual(log.success_count, 2)
        self.assertEqual(log.failed_count, 0)

    @patch('letters.views.send_sms_with_result')
    def test_broadcast_by_department(self, mock_send):
        """Sending by department should target staff belonging to that department with phones."""
        mock_send.return_value = (True, 'SMS sent successfully.')

        data = {
            'recipient_mode': 'by_department',
            'departments': [self.dept.id],
            'message': 'Legal department reminder.',
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Only staff1 is in Legal with a phone
        self.assertEqual(mock_send.call_count, 1)
        mock_send.assert_called_with('+251912345678', 'Legal department reminder.')

        log = CustomSMSLog.objects.first()
        self.assertEqual(log.total_recipients, 1)

    @patch('letters.views.send_sms_with_result')
    def test_broadcast_to_external_numbers(self, mock_send):
        """Sending to external phone numbers should parse and normalize numbers."""
        mock_send.return_value = (True, 'SMS sent successfully.')

        data = {
            'recipient_mode': 'external_only',
            'external_numbers': '0911526889\n0712345678, +251944556677',
            'message': 'External partner broadcast message.',
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        # 3 external numbers
        self.assertEqual(mock_send.call_count, 3)

        log = CustomSMSLog.objects.first()
        self.assertEqual(log.total_recipients, 3)
        self.assertEqual(log.success_count, 3)

    @patch('letters.views.send_sms_with_result')
    def test_broadcast_combined_staff_and_external(self, mock_send):
        """Sending to selected staff + external numbers should combine recipients without duplicates."""
        mock_send.return_value = (True, 'SMS sent successfully.')

        data = {
            'recipient_mode': 'selected_staff',
            'staff_ids': [self.staff1.id],
            'external_numbers': '0912345678, 0977889900',  # Note: 0912345678 is staff1's number!
            'message': 'Combined broadcast alert.',
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Duplicate phone number 0912345678 should be de-duplicated! So only 2 unique numbers sent
        self.assertEqual(mock_send.call_count, 2)

    @patch('letters.views.send_sms_with_result')
    def test_failed_sms_tracked_in_log(self, mock_send):
        """Failed delivery from AfroMessage API should be tracked with error message."""
        mock_send.return_value = (False, 'Insufficient balance')

        data = {
            'recipient_mode': 'external_only',
            'external_numbers': '0912345678',
            'message': 'Test balance error.',
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)

        log = CustomSMSLog.objects.first()
        self.assertEqual(log.total_recipients, 1)
        self.assertEqual(log.success_count, 0)
        self.assertEqual(log.failed_count, 1)
        self.assertEqual(log.delivery_details[0]['status'], 'failed')
        self.assertEqual(log.delivery_details[0]['error'], 'Insufficient balance')

    def test_log_detail_ajax_view(self):
        """Detail view should return JSON representation of log."""
        log = CustomSMSLog.objects.create(
            sender=self.superuser,
            message='Test log detail',
            target_type='All Staff',
            total_recipients=1,
            success_count=1,
            failed_count=0,
            delivery_details=[{
                'phone': '+251912345678',
                'name': 'John Doe',
                'type': 'Staff',
                'status': 'success',
                'error': '',
            }]
        )
        detail_url = reverse('letters:custom_sms_log_detail', kwargs={'pk': log.pk})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], log.id)
        self.assertEqual(data['sender'], 'superuser')
        self.assertEqual(data['success_count'], 1)
        self.assertEqual(len(data['delivery_details']), 1)
