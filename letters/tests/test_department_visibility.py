from django.contrib.auth.models import Group, User, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from letters.models import Department, Letter


class DepartmentVisibilityTest(TestCase):
    """Tests for row-level department visibility and overrides."""

    def setUp(self):
        # Create departments
        self.hr_dept = Department.objects.create(name='Human Resources', code='HR')
        self.fin_dept = Department.objects.create(name='Finance', code='FIN')

        # Create groups
        self.front_desk_group = Group.objects.create(name='Front Desk')
        self.dept_staff_group = Group.objects.create(name='Department Staff')
        self.admin_group = Group.objects.create(name='Admin')

        # Add the can_view_all_letters permission to Front Desk and Admin groups
        content_type = ContentType.objects.get_for_model(Letter)
        self.view_all_perm = Permission.objects.get(
            codename='can_view_all_letters',
            content_type=content_type
        )
        self.front_desk_group.permissions.add(self.view_all_perm)
        self.admin_group.permissions.add(self.view_all_perm)

        # Create users
        self.hr_staff = User.objects.create_user(username='hr_staff', password='pass')
        self.hr_staff.groups.add(self.dept_staff_group)
        self.hr_dept.users.add(self.hr_staff)

        self.fin_staff = User.objects.create_user(username='fin_staff', password='pass')
        self.fin_staff.groups.add(self.dept_staff_group)
        self.fin_dept.users.add(self.fin_staff)

        self.frontdesk_user = User.objects.create_user(username='frontdesk', password='pass')
        self.frontdesk_user.groups.add(self.front_desk_group)

        self.superuser = User.objects.create_user(username='superuser', password='pass', is_superuser=True)

        # Create letters
        self.l_hr = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='HR Sender',
            subject='HR Correspondence',
            assigned_department=self.hr_dept,
            assigned_person=self.hr_staff,
            created_by=self.frontdesk_user,
        )

        self.l_fin = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Finance Sender',
            subject='Finance Correspondence',
            assigned_department=self.fin_dept,
            assigned_person=self.fin_staff,
            created_by=self.frontdesk_user,
        )

        # Unassigned but created by HR staff (e.g. draft/internal)
        self.l_created_by_hr = Letter.objects.create(
            direction='OUTGOING',
            date=timezone.now().date(),
            recipient='Internal Recipient',
            subject='HR Internal Note',
            assigned_department=None,
            assigned_person=None,
            created_by=self.hr_staff,
        )

    # -------------------------------------------------------------------
    # List View Filtering
    # -------------------------------------------------------------------
    def test_hr_staff_only_sees_hr_and_own_letters(self):
        """HR staff sees HR department letters and letters they created, but not FIN letters."""
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get('/letters/')
        self.assertEqual(response.status_code, 200)
        letters = list(response.context['letters'])

        self.assertIn(self.l_hr, letters)
        self.assertIn(self.l_created_by_hr, letters)
        self.assertNotIn(self.l_fin, letters)

    def test_fin_staff_only_sees_fin_letters(self):
        """Finance staff sees FIN letters, but not HR letters."""
        self.client.login(username='fin_staff', password='pass')
        response = self.client.get('/letters/')
        self.assertEqual(response.status_code, 200)
        letters = list(response.context['letters'])

        self.assertIn(self.l_fin, letters)
        self.assertNotIn(self.l_hr, letters)
        self.assertNotIn(self.l_created_by_hr, letters)

    def test_assigned_person_can_see_letter_even_if_in_different_department(self):
        """If a letter is in FIN department but explicitly assigned to HR staff, they can see it."""
        crossover_letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Crossover Sender',
            subject='Finance letter assigned to HR person',
            assigned_department=self.fin_dept,
            assigned_person=self.hr_staff,
            created_by=self.frontdesk_user,
        )
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get('/letters/')
        letters = list(response.context['letters'])
        self.assertIn(crossover_letter, letters)

    # -------------------------------------------------------------------
    # Detail / Edit Access Control
    # -------------------------------------------------------------------
    def test_detail_view_access_denied_for_other_department(self):
        """HR staff cannot view the detail page of a FIN letter."""
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get(f'/letters/{self.l_fin.pk}/')
        # Should fail permission check (403 forbidden)
        self.assertEqual(response.status_code, 403)

    def test_detail_view_access_allowed_for_own_department(self):
        """HR staff can view the detail page of their HR letter."""
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get(f'/letters/{self.l_hr.pk}/')
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------
    # Overrides (Admin / Front Desk / Custom Permission)
    # -------------------------------------------------------------------
    def test_front_desk_can_view_all_letters(self):
        """Front desk group members can see all letters across all departments."""
        self.client.login(username='frontdesk', password='pass')
        response = self.client.get('/letters/')
        letters = list(response.context['letters'])
        self.assertIn(self.l_hr, letters)
        self.assertIn(self.l_fin, letters)
        self.assertIn(self.l_created_by_hr, letters)

    def test_superuser_can_view_all_letters(self):
        """Superuser can see all letters across all departments."""
        self.client.login(username='superuser', password='pass')
        response = self.client.get('/letters/')
        letters = list(response.context['letters'])
        self.assertIn(self.l_hr, letters)
        self.assertIn(self.l_fin, letters)

    def test_custom_permission_override(self):
        """Granting 'can_view_all_letters' directly to a user bypasses the department block."""
        # Confirm they can't see it originally
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get(f'/letters/{self.l_fin.pk}/')
        self.assertEqual(response.status_code, 403)

        # Grant permission
        self.hr_staff.user_permissions.add(self.view_all_perm)
        # Force re-authentication / clear permissions cache
        self.hr_staff = User.objects.get(pk=self.hr_staff.pk)

        # Log back in and verify they can see it now
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get(f'/letters/{self.l_fin.pk}/')
        self.assertEqual(response.status_code, 200)

    # -------------------------------------------------------------------
    # Dashboard & Reports Isolation
    # -------------------------------------------------------------------
    def test_dashboard_metrics_isolated(self):
        """Dashboard counts only aggregate letters the user has access to."""
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_letters'], 2)  # HR letter + Created by HR

        self.client.login(username='frontdesk', password='pass')
        response = self.client.get('/')
        self.assertEqual(response.context['total_letters'], 3)  # All letters

    def test_reports_data_isolated(self):
        """Reports JSON API only includes aggregates of visible letters."""
        self.client.login(username='hr_staff', password='pass')
        response = self.client.get('/reports/data/')
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Check by_department sums
        dept_sums = {item['assigned_department__name']: item['count'] for item in data['by_department'] if item['assigned_department__name']}
        self.assertEqual(dept_sums.get('Human Resources'), 1)
        self.assertNotIn('Finance', dept_sums)
