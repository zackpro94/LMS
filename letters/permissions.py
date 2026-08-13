from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


class BasePermissionMixin(UserPassesTestMixin):
    """
    Base permission mixin that ensures unauthenticated users are redirected to the login page
    with the 'next' parameter set, while authenticated users who lack permission get a 403 Forbidden.
    """
    permission_denied_message = "You do not have permission to access this page."

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect_to_login(self.request.get_full_path())
        raise PermissionDenied(self.permission_denied_message)


class AdminOrAssignedMixin(BasePermissionMixin):
    """Allow only admin users or the assigned person."""
    permission_denied_message = "Only admins or assigned staff can access this letter."

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser or user.groups.filter(name='Admin').exists():
            return True
        letter = self.get_object()
        return letter.assigned_person == user


class CanCreateLetterMixin(BasePermissionMixin):
    """Allow Front Desk, Department Staff, and Admin to create letters."""
    permission_denied_message = "You do not have permission to create letters."

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        allowed_groups = ('Front Desk', 'Department Staff', 'Admin')
        return user.groups.filter(name__in=allowed_groups).exists()


def user_can_close(user, letter):
    """Return True if user can close/archive a letter."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name='Admin').exists():
        return True
    if letter.assigned_person == user:
        return True
    return False


def user_can_view_all_letters(user):
    """Return True if user has permission to view all letters across all departments."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name__in=['Admin', 'Front Desk']).exists():
        return True
    if user.has_perm('letters.can_view_all_letters'):
        return True
    return False


def user_can_view_letter(user, letter):
    """Return True if user is authorized to view a specific letter."""
    if not user.is_authenticated:
        return False
    if user_can_view_all_letters(user):
        return True
    user_depts = user.departments.all()
    return (
        (letter.assigned_department in user_depts) or
        (letter.assigned_person == user) or
        (letter.created_by == user)
    )


def user_can_view_attachment_logs(user, attachment=None):
    """
    Return True if user can view staff interaction/view logs for attachments.
    Allowed for superusers, Admin group users, or users granted the 'can_view_attachment_analytics' permission.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name='Admin').exists():
        return True
    return user.has_perm('letters.can_view_attachment_analytics')


class CanViewLetterMixin(BasePermissionMixin):
    """Allow access if user can view all or belongs to the department, is assigned, or created the letter."""
    permission_denied_message = "You do not have permission to view this letter."

    def test_func(self):
        if not self.request.user.is_authenticated:
            return False
        letter = self.get_object()
        return user_can_view_letter(self.request.user, letter)


class SuperuserOrAdminRequiredMixin(BasePermissionMixin):
    """Enforce that only superusers or users in the Admin group can access administrative views."""
    permission_denied_message = "Administrative privileges are required to access this area."

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or user.groups.filter(name='Admin').exists()
        )


def _can_view_direction(user, perm_codename):
    """Shared helper: return True if user may access a direction-specific list."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.groups.filter(name__in=['Admin', 'Front Desk']).exists():
        return True
    if user.has_perm('letters.can_view_all_letters'):
        return True
    return user.has_perm(f'letters.{perm_codename}')


class CanViewOutgoingLettersMixin(BasePermissionMixin):
    """Allow access to outgoing letters list for authorised users."""
    permission_denied_message = "You do not have permission to view outgoing letters."

    def test_func(self):
        return _can_view_direction(self.request.user, 'can_view_outgoing_letters')


class CanViewIncomingLettersMixin(BasePermissionMixin):
    """Allow access to incoming letters list for authorised users."""
    permission_denied_message = "You do not have permission to view incoming letters."

    def test_func(self):
        return _can_view_direction(self.request.user, 'can_view_incoming_letters')
