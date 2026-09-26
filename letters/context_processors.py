from .permissions import user_can_view_all_letters
from .models import SystemSetting


def lms_navigation(request):
    """Expose shared navigation flags and system settings for templates."""
    user = request.user
    if not user.is_authenticated:
        return {}

    is_system_admin = user.is_superuser or user.groups.filter(name='Admin').exists()
    setting = SystemSetting.get_settings()

    return {
        'lms_is_system_admin': is_system_admin,
        'lms_can_view_all': user_can_view_all_letters(user),
        'lms_ai_enabled': setting.ai_assistant_enabled,
        'lms_ocr_enabled': setting.ai_ocr_enabled,
    }
