from django.contrib.auth.models import Group, User
from django.test import TestCase, RequestFactory
from django.utils import timezone

from letters.models import Department, Letter
from letters.permissions import user_can_close


class StatusTransitionTest(TestCase):
    """Tests for status change permissions and transition logic."""

    def setUp(self):
        self.dept = Department.objects.create(name='Finance', code='FIN')

        # Create groups
        self.front_desk_group = Group.objects.create(name='Front Desk')
        self.dept_staff_group = Group.objects.create(name='Department Staff')
        self.admin_group = Group.objects.create(name='Admin')

        # Create users
        self.admin_user = User.objects.create_user(
            username='admin_user', password='pass',
            is_superuser=True,
        )
        self.admin_user.groups.add(self.admin_group)

        self.frontdesk_user = User.objects.create_user(
            username='frontdesk', password='pass',
        )
        self.frontdesk_user.groups.add(self.front_desk_group)

        self.assigned_staff = User.objects.create_user(
            username='assigned_staff', password='pass',
        )
        self.assigned_staff.groups.add(self.dept_staff_group)

        self.other_staff = User.objects.create_user(
            username='other_staff', password='pass',
        )
        self.other_staff.groups.add(self.dept_staff_group)

        self.letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Test Sender',
            subject='Test Letter for Permissions',
            assigned_department=self.dept,
            assigned_person=self.assigned_staff,
            status='RECEIVED',
            created_by=self.frontdesk_user,
        )

    # -------------------------------------------------------------------
    # user_can_close
    # -------------------------------------------------------------------
    def test_superuser_can_close(self):
        """Superuser can always close/archive."""
        self.assertTrue(user_can_close(self.admin_user, self.letter))

    def test_admin_group_can_close(self):
        """Admin group member can close/archive."""
        admin_member = User.objects.create_user(username='admin2', password='pass')
        admin_member.groups.add(self.admin_group)
        self.assertTrue(user_can_close(admin_member, self.letter))

    def test_assigned_person_can_close(self):
        """The assigned person can close/archive their own letter."""
        self.assertTrue(user_can_close(self.assigned_staff, self.letter))

    def test_frontdesk_cannot_close(self):
        """Front Desk users cannot close letters."""
        self.assertFalse(user_can_close(self.frontdesk_user, self.letter))

    def test_unassigned_staff_cannot_close(self):
        """Department staff not assigned to the letter cannot close it."""
        self.assertFalse(user_can_close(self.other_staff, self.letter))

    # -------------------------------------------------------------------
    # Status transitions
    # -------------------------------------------------------------------
    def test_valid_status_transition(self):
        """Any user can change status to non-terminal states."""
        self.letter.status = 'IN_REVIEW'
        self.letter.save()
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, 'IN_REVIEW')

    def test_status_to_closed(self):
        """Status can be set to CLOSED (model allows it; permission check is in the view)."""
        self.letter.status = 'CLOSED'
        self.letter.save()
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, 'CLOSED')

    def test_status_to_archived(self):
        """Status can be set to ARCHIVED at the model level."""
        self.letter.status = 'ARCHIVED'
        self.letter.save()
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, 'ARCHIVED')

    # -------------------------------------------------------------------
    # View-level permission check (via test client)
    # -------------------------------------------------------------------
    def test_frontdesk_action_close_blocked(self):
        """Front Desk user POSTing close via AddActionView gets blocked."""
        self.client.login(username='frontdesk', password='pass')
        response = self.client.post(
            f'/letters/{self.letter.pk}/action/',
            {'action': 'Attempting close', 'new_status': 'CLOSED', 'notes': ''},
        )
        # Should redirect back with an error message
        self.assertEqual(response.status_code, 302)
        self.letter.refresh_from_db()
        # Status should NOT have changed
        self.assertEqual(self.letter.status, 'RECEIVED')

    def test_assigned_user_action_close_allowed(self):
        """Assigned user can close a letter via AddActionView."""
        self.client.login(username='assigned_staff', password='pass')
        response = self.client.post(
            f'/letters/{self.letter.pk}/action/',
            {'action': 'Closing letter', 'new_status': 'CLOSED', 'notes': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, 'CLOSED')

    def test_admin_action_close_allowed(self):
        """Admin user can close any letter via AddActionView."""
        self.client.login(username='admin_user', password='pass')
        response = self.client.post(
            f'/letters/{self.letter.pk}/action/',
            {'action': 'Admin closing', 'new_status': 'CLOSED', 'notes': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, 'CLOSED')
