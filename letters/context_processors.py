from .permissions import user_can_view_all_letters


def lms_navigation(request):
    """Expose shared navigation flags for templates."""
    user = request.user
    if not user.is_authenticated:
        return {}

    is_system_admin = user.is_superuser or user.groups.filter(name='Admin').exists()

    return {
        'lms_is_system_admin': is_system_admin,
        'lms_can_view_all': user_can_view_all_letters(user),
    }
