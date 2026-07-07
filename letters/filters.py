import django_filters
from django import forms
from .models import Letter, Department, Category


class LetterFilter(django_filters.FilterSet):
    """Filter set for the letter list view."""

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
        label='From Date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    date_to = django_filters.DateFilter(
        field_name='date',
        lookup_expr='lte',
        label='To Date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    class Meta:
        model = Letter
        fields = [
            'direction', 'letter_type', 'status', 'category', 'priority',
            'assigned_department',
        ]
