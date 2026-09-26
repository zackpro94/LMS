import django_filters
from django import forms
from .models import Letter, Department, Category
from .ethiopian_calendar import parse_ethiopian_date


class LetterFilter(django_filters.FilterSet):
    """Filter set for the letter list view with dual Gregorian and Ethiopian date support."""

    direction = django_filters.ChoiceFilter(
        choices=Letter.DIRECTION_CHOICES,
        empty_label='All Directions',
    )
    letter_type = django_filters.ChoiceFilter(
        choices=Letter.LETTER_TYPE_CHOICES,
        empty_label='All Types',
    )
    status = django_filters.ChoiceFilter(
        choices=Letter.STATUS_CHOICES,
        empty_label='All Statuses',
    )
    category = django_filters.ModelChoiceFilter(
        queryset=Category.objects.all(),
        empty_label='All Categories',
    )
    priority = django_filters.ChoiceFilter(
        choices=Letter.PRIORITY_CHOICES,
        empty_label='All Priorities',
    )
    assigned_department = django_filters.ModelChoiceFilter(
        queryset=Department.objects.all(),
        empty_label='All Departments',
    )
    date_from = django_filters.DateFilter(
        field_name='date',
        lookup_expr='gte',
        label='From Date (G.C.)',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = django_filters.DateFilter(
        field_name='date',
        lookup_expr='lte',
        label='To Date (G.C.)',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    eth_date_from = django_filters.CharFilter(
        method='filter_eth_date_from',
        label='From Date (E.C.)',
        widget=forms.TextInput(attrs={'placeholder': 'YYYY-MM-DD', 'class': 'form-control form-control-sm'}),
    )
    eth_date_to = django_filters.CharFilter(
        method='filter_eth_date_to',
        label='To Date (E.C.)',
        widget=forms.TextInput(attrs={'placeholder': 'YYYY-MM-DD', 'class': 'form-control form-control-sm'}),
    )

    def filter_eth_date_from(self, queryset, name, value):
        if value:
            try:
                greg_date = parse_ethiopian_date(value)
                if greg_date:
                    return queryset.filter(date__gte=greg_date)
            except Exception:
                pass
        return queryset

    def filter_eth_date_to(self, queryset, name, value):
        if value:
            try:
                greg_date = parse_ethiopian_date(value)
                if greg_date:
                    return queryset.filter(date__lte=greg_date)
            except Exception:
                pass
        return queryset

    class Meta:
        model = Letter
        fields = [
            'direction', 'letter_type', 'status', 'category', 'priority',
            'assigned_department',
        ]
