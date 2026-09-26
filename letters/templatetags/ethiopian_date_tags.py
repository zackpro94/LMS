from django import template
from django.utils.safestring import mark_safe
from letters.ethiopian_calendar import (
    format_ethiopian_date,
    gregorian_to_ethiopian,
    ETHIOPIAN_MONTHS_EN,
    ETHIOPIAN_MONTHS_AM,
)

register = template.Library()


@register.filter(name='to_ethiopian')
def to_ethiopian_filter(value, fmt='full'):
    """Format Gregorian date as Ethiopian date string (English)."""
    if not value:
        return ""
    return format_ethiopian_date(value, fmt=fmt, amharic=False)


@register.filter(name='ethiopian_amharic')
def ethiopian_amharic_filter(value):
    """Format Gregorian date as Ethiopian date string in Amharic."""
    if not value:
        return ""
    return format_ethiopian_date(value, fmt='full', amharic=True)


@register.filter(name='dual_date')
def dual_date_filter(value):
    """Return both Gregorian and Ethiopian dates in a clean string."""
    if not value:
        return ""
    return format_ethiopian_date(value, fmt='dual', amharic=False)


@register.filter(name='ethiopian_short')
def ethiopian_short_filter(value):
    """Format as short Ethiopian date: 15/12/2018 E.C."""
    if not value:
        return ""
    return format_ethiopian_date(value, fmt='short', amharic=False)


@register.filter(name='ethiopian_iso')
def ethiopian_iso_filter(value):
    """Format as ISO Ethiopian date: YYYY-MM-DD"""
    if not value:
        return ""
    return format_ethiopian_date(value, fmt='iso', amharic=False)


@register.filter(name='dual_date_html')
def dual_date_html_filter(value, extra_class=''):
    """
    Render a clean, responsive dual-calendar badge showing both Gregorian and Ethiopian dates.
    """
    if not value:
        return mark_safe('<span class="text-muted">—</span>')

    greg_str = value.strftime("%d %b %Y")
    eth_str = format_ethiopian_date(value, fmt='full', amharic=False)
    eth_amharic = format_ethiopian_date(value, fmt='full', amharic=True)

    html = (
        f'<div class="d-inline-flex flex-column align-items-start {extra_class}">'
        f'  <span class="fw-semibold text-dark" style="font-size: 0.88rem;">{greg_str}</span>'
        f'  <small class="text-muted d-inline-flex align-items-center gap-1" style="font-size: 0.75rem;" title="{eth_amharic}">'
        f'    <i class="bi bi-calendar-event text-primary opacity-75" style="font-size: 0.7rem;"></i>'
        f'    <span>{eth_str}</span>'
        f'  </small>'
        f'</div>'
    )
    return mark_safe(html)
