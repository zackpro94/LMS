from django import template

register = template.Library()

@register.filter
def in_group(user, group_name):
    """Return True if the user belongs to the given auth group."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


@register.filter
def in_any_group(user, group_names):
    """Return True if the user belongs to any of the comma-separated groups."""
    if not user.is_authenticated:
        return False
    names = [name.strip() for name in group_names.split(',') if name.strip()]
    return user.groups.filter(name__in=names).exists()
