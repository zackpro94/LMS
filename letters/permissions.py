from django.contrib.auth.mixins import UserPassesTestMixin


class AdminOrAssignedMixin(UserPassesTestMixin):
    """Allow only admin users or the assigned person."""

    def test_func(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name='Admin').exists():
            return True
        letter = self.get_object()
        return letter.assigned_person == user


class CanCreateLetterMixin(UserPassesTestMixin):
    """Allow Front Desk, Department Staff, and Admin to create letters."""

    def test_func(self):
        user = self.request.user
        if user.is_superuser:
            return True
        allowed_groups = ('Front Desk', 'Department Staff', 'Admin')
        return user.groups.filter(name__in=allowed_groups).exists()


def user_can_close(user, letter):
    """Return True if user can close/archive a letter."""
    if user.is_superuser:
        return True
    if user.groups.filter(name='Admin').exists():
        return True
    if letter.assigned_person == user:
        return True
    return False


def user_can_view_all_letters(user):
    """Return True if user has permission to view all letters across all departments."""
    if user.is_superuser:
        return True
    if user.groups.filter(name__in=['Admin', 'Front Desk']).exists():
        return True
    if user.has_perm('letters.can_view_all_letters'):
        return True
    return False


class CanViewLetterMixin(UserPassesTestMixin):
    """Allow access if user can view all or belongs to the department, is assigned, or created the letter."""

    raise_exception = True

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user_can_view_all_letters(user):
            return True
        letter = self.get_object()
        user_depts = user.departments.all()
        return (
            (letter.assigned_department in user_depts) or
            (letter.assigned_person == user) or
            (letter.created_by == user)
        )


class SuperuserOrAdminRequiredMixin(UserPassesTestMixin):
    """Enforce that only superusers or users in the Admin group can access administrative views."""

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or user.groups.filter(name='Admin').exists()
        )


def _can_view_direction(user, perm_codename):
    """Shared helper: return True if user may access a direction-specific list."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.groups.filter(name__in=['Admin', 'Front Desk']).exists():
        return True
    if user.has_perm('letters.can_view_all_letters'):
        return True
    return user.has_perm(f'letters.{perm_codename}')


class CanViewOutgoingLettersMixin(UserPassesTestMixin):
    """Allow access to outgoing letters list for authorised users."""

    def test_func(self):
        return _can_view_direction(self.request.user, 'can_view_outgoing_letters')


class CanViewIncomingLettersMixin(UserPassesTestMixin):
    """Allow access to incoming letters list for authorised users."""

    def test_func(self):
        return _can_view_direction(self.request.user, 'can_view_incoming_letters')
