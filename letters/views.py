import calendar
import os
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

from django.conf import settings

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.urls import reverse, reverse_lazy
from django.contrib.auth.models import User, Group
from django.views.generic import (
    CreateView, DetailView, ListView, TemplateView, UpdateView, DeleteView, FormView
)
from django_filters.views import FilterView
from django.db import models
 
from django.utils.timesince import timesince

from .filters import LetterFilter
from .forms import (
    ActionLogForm, AttachmentForm, LetterForm, DepartmentForm, CategoryForm, StaffForm,
    IncomingLetterForm, OutgoingLetterForm, UserProfileForm, UserPreferencesForm, CustomPasswordChangeForm,
    OldArchiveIncomingForm, OldArchiveOutgoingForm, OldArchiveExcelImportForm,
)
from .models import (
    ActionLog, Attachment, AttachmentView, Department, Letter, Category, SavedSearch,
    UserProfile, Notification, PushSubscription, SystemSetting, CustomSMSLog,
)
from django.core.files.base import ContentFile
from .permissions import (
    user_can_close, user_can_view_all_letters, user_can_view_letter, user_can_view_attachment_logs,
    CanViewLetterMixin, SuperuserOrAdminRequiredMixin, SuperuserRequiredMixin,
)
from .export_utils import export_letters_to_excel, export_letters_to_pdf
from .archive_import import import_archive_letters_from_excel, generate_sample_archive_excel
from .email_utils import (
    send_overdue_notification, send_status_change_notification,
    send_assignment_notification, send_new_action_notification
)
from .push_utils import send_push_notification
from .telegram_utils import send_telegram_notification
from .sms_utils import send_sms_with_result, normalize_phone_number


# ---------------------------------------------------------------------------
# Notification Helper Functions
# ---------------------------------------------------------------------------
def create_notification(recipient, notification_type, title, message, related_letter=None):
    """Create a notification for a user."""
    # Check if user has email notifications enabled
    try:
        profile = recipient.profile
        if not profile.email_notifications:
            return
    except UserProfile.DoesNotExist:
        # Create profile if it doesn't exist
        profile = UserProfile.objects.create(user=recipient)
    
    # Create in-app notification
    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
        related_letter=related_letter
    )
    
    # Send push notification
    url = related_letter.get_absolute_url() if related_letter else None
    send_push_notification(recipient, title, message, url)
    
    # Send Telegram notification
    send_telegram_notification(recipient, title, message, url)


def get_user_letter_queryset(user, qs=None):
    """Filters a letter queryset based on the user's role and assigned department."""
    if qs is None:
        qs = Letter.objects.all()
    if not user_can_view_all_letters(user):
        user_depts = user.departments.all()
        qs = qs.filter(
            Q(assigned_department__in=user_depts) |
            Q(assigned_person=user) |
            Q(created_by=user)
        )
    return qs


def build_letter_search_query(search_term):
    """Builds Q objects for searching letters by reference_no, subject, parties, departments, and Ethiopian/Gregorian dates."""
    if not search_term:
        return Q()

    search = str(search_term).strip()
    search_q = (
        Q(subject__icontains=search)
        | Q(sender__icontains=search)
        | Q(recipient__icontains=search)
        | Q(reference_no__icontains=search)
        | Q(attention_to__icontains=search)
        | Q(assigned_department__name__icontains=search)
        | Q(assigned_department__code__icontains=search)
        | Q(archive_notes__icontains=search)
    )

    try:
        from .ethiopian_calendar import (
            parse_ethiopian_date, ethiopian_year_gregorian_range,
            ETHIOPIAN_MONTH_MAP, ethiopian_month_gregorian_range, gregorian_to_ethiopian
        )
        # Exact date check
        parsed_eth_date = parse_ethiopian_date(search)
        if parsed_eth_date:
            search_q |= Q(date=parsed_eth_date)

        # Year check (e.g. "2018" or "2017")
        if search.isdigit() and 1900 <= int(search) <= 2150:
            y_start, y_end = ethiopian_year_gregorian_range(int(search))
            search_q |= Q(date__range=(y_start, y_end))

        # Month name check (e.g. "Nehase" or "ነሐሴ")
        clean_term = search.lower()
        if clean_term in ETHIOPIAN_MONTH_MAP or search in ETHIOPIAN_MONTH_MAP:
            m_idx = ETHIOPIAN_MONTH_MAP.get(clean_term) or ETHIOPIAN_MONTH_MAP.get(search)
            cur_ey, _, _ = gregorian_to_ethiopian(timezone.now().date())
            for ey in range(cur_ey - 3, cur_ey + 2):
                m_start, m_end = ethiopian_month_gregorian_range(ey, m_idx)
                search_q |= Q(date__range=(m_start, m_end))
    except Exception as e:
        logger.debug("Failed parsing Ethiopian date for query '%s': %s", search, e)

    return search_q


class AjaxListMixin:
    """Mixin to return rendered HTML partial for AJAX requests in list views."""
    ajax_partial_template_name = None

    def render_to_response(self, context, **response_kwargs):
        if (self.request.headers.get('x-requested-with') == 'XMLHttpRequest' or 
            self.request.GET.get('ajax') == '1') and self.ajax_partial_template_name:
            from django.template.loader import render_to_string
            table_html = render_to_string(self.ajax_partial_template_name, context, request=self.request)
            count = context['paginator'].count if context.get('is_paginated') else len(context.get('letters', []))
            return JsonResponse({
                'table_html': table_html,
                'count': count,
                'count_text': f"{count} letter{'s' if count != 1 else ''} found"
            })
        return super().render_to_response(context, **response_kwargs)


# ---------------------------------------------------------------------------
# Letter Search API (Autocomplete & Realtime Global Command Palette)
# ---------------------------------------------------------------------------
class LetterSearchView(LoginRequiredMixin, View):
    """API endpoint for realtime global search and related letter autocomplete."""
    def get(self, request):
        query = request.GET.get('q', '').strip()
        if not query:
            return JsonResponse({'results': [], 'count': 0})
        
        filter_type = request.GET.get('type', 'ALL').upper()
        limit = min(int(request.GET.get('limit', 15)), 50)
        
        letters_qs = get_user_letter_queryset(request.user)
        
        if filter_type == 'INCOMING':
            letters_qs = letters_qs.filter(direction='INCOMING', is_old_archive=False)
        elif filter_type == 'OUTGOING':
            letters_qs = letters_qs.filter(direction='OUTGOING', is_old_archive=False)
        elif filter_type == 'ARCHIVE':
            letters_qs = letters_qs.filter(is_old_archive=True)
        
        search_q = build_letter_search_query(query)
        letters_qs = letters_qs.filter(search_q).select_related(
            'assigned_department', 'assigned_person', 'category'
        ).order_by('-date', '-created_at')
        
        total_count = letters_qs.count()
        letters = letters_qs[:limit]
        
        results = []
        for letter in letters:
            party = letter.sender if letter.direction == 'INCOMING' else letter.recipient
            results.append({
                'id': letter.pk,
                'text': f"{letter.reference_no} - {letter.subject[:50]}{'...' if len(letter.subject) > 50 else ''}",
                'reference_no': letter.reference_no or '—',
                'subject': letter.subject or '',
                'direction': letter.direction,
                'direction_display': letter.get_direction_display(),
                'letter_type': letter.letter_type,
                'letter_type_display': letter.get_letter_type_display(),
                'status': letter.status,
                'status_display': letter.get_status_display(),
                'priority': letter.priority,
                'priority_display': letter.get_priority_display(),
                'sender': letter.sender or '',
                'recipient': letter.recipient or '',
                'party': party or '',
                'attention_to': letter.attention_to or '',
                'department': (letter.assigned_department.code or letter.assigned_department.name) if letter.assigned_department else '',
                'date': letter.date.strftime('%d %b %Y') if letter.date else '',
                'ethiopian_date': letter.ethiopian_date or '',
                'is_overdue': getattr(letter, 'is_overdue', False),
                'is_old_archive': letter.is_old_archive,
                'url': letter.get_absolute_url(),
            })
        
        return JsonResponse({
            'results': results,
            'count': total_count
        })


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.now().date()
        user = self.request.user

        letters_qs = get_user_letter_queryset(user).filter(is_old_archive=False)
        ctx['total_letters'] = letters_qs.count()
        ctx['incoming_count'] = letters_qs.filter(direction='INCOMING').count()
        ctx['outgoing_count'] = letters_qs.filter(direction='OUTGOING').count()
        ctx['pending_count'] = letters_qs.filter(
            status__in=['RECEIVED', 'DRAFTED', 'IN_REVIEW'],
        ).count()
        ctx['overdue_count'] = letters_qs.filter(
            due_date__lt=today,
        ).exclude(status__in=['ARCHIVED']).count()
        ctx['in_review_count'] = letters_qs.filter(status='IN_REVIEW').count()
        ctx['urgent_count'] = letters_qs.filter(
            priority='URGENT',
        ).exclude(status__in=['ARCHIVED']).count()

        # Filter action logs so user only sees actions for letters they can view
        action_qs = ActionLog.objects.all()
        if not user_can_view_all_letters(user):
            user_depts = user.departments.all()
            action_qs = action_qs.filter(
                Q(letter__assigned_department__in=user_depts) |
                Q(letter__assigned_person=user) |
                Q(letter__created_by=user)
            )



        ctx['recent_actions'] = (
            action_qs
            .select_related('letter', 'action_by')[:10]
        )
        ctx['recent_letters'] = (
            letters_qs
            .select_related('assigned_department', 'created_by')[:5]
        )
        return ctx


# ---------------------------------------------------------------------------
# Letter list (filterable)
# ---------------------------------------------------------------------------
class LetterListView(LoginRequiredMixin, AjaxListMixin, FilterView):
    model = Letter
    template_name = 'letters/letter_list.html'
    context_object_name = 'letters'
    filterset_class = LetterFilter
    paginate_by = 20
    ajax_partial_template_name = 'letters/includes/letter_table_partial.html'

    def get_queryset(self):
        qs = super().get_queryset().filter(is_old_archive=False)
        qs = get_user_letter_queryset(self.request.user, qs)
        qs = qs.select_related(
            'assigned_department', 'assigned_person', 'created_by', 'category',
        )
        search = self.request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(build_letter_search_query(search))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['list_title'] = 'All Letters'
        ctx['list_clear_url'] = reverse_lazy('letters:letter_list')
        ctx['saved_searches'] = SavedSearch.objects.filter(user=self.request.user)[:10]
        return ctx

    def get(self, request, *args, **kwargs):
        # Handle export requests
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            queryset = self.get_queryset()
            if export_format == 'excel':
                return export_letters_to_excel(queryset, 'All_Letters')
            elif export_format == 'pdf':
                return export_letters_to_pdf(queryset, 'All_Letters')
        return super().get(request, *args, **kwargs)


class OutgoingLetterListView(LetterListView):
    def get_queryset(self):
        return super().get_queryset().filter(direction='OUTGOING')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['list_title'] = 'Outgoing Letters'
        ctx['is_outgoing_view'] = True
        ctx['list_clear_url'] = reverse_lazy('letters:outgoing_letter_list')
        return ctx

    def get(self, request, *args, **kwargs):
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            queryset = self.get_queryset()
            if export_format == 'excel':
                return export_letters_to_excel(queryset, 'Outgoing_Letters')
            elif export_format == 'pdf':
                return export_letters_to_pdf(queryset, 'Outgoing_Letters')
        return super().get(request, *args, **kwargs)


class IncomingLetterListView(LetterListView):
    def get_queryset(self):
        return super().get_queryset().filter(direction='INCOMING')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['list_title'] = 'Incoming Letters'
        ctx['is_incoming_view'] = True
        ctx['list_clear_url'] = reverse_lazy('letters:incoming_letter_list')
        return ctx

    def get(self, request, *args, **kwargs):
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            queryset = self.get_queryset()
            if export_format == 'excel':
                return export_letters_to_excel(queryset, 'Incoming_Letters')
            elif export_format == 'pdf':
                return export_letters_to_pdf(queryset, 'Incoming_Letters')
        return super().get(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Old Archive views
# ---------------------------------------------------------------------------
def clean_archive_url(url):
    """Strip ajax parameter and normalize URL for clean browser redirects."""
    if not url:
        return ''
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    qd = urllib.parse.parse_qs(parsed.query)
    qd.pop('ajax', None)
    clean_query = urllib.parse.urlencode(qd, doseq=True)
    if clean_query:
        return f"{parsed.path}?{clean_query}"
    return parsed.path


class OldArchiveIncomingListView(LoginRequiredMixin, AjaxListMixin, FilterView):
    """List view for old archived incoming letters."""
    model = Letter
    template_name = 'letters/old_archive_list.html'
    context_object_name = 'letters'
    filterset_class = LetterFilter
    paginate_by = 20
    ajax_partial_template_name = 'letters/includes/old_archive_table_partial.html'

    def get_queryset(self):
        qs = super().get_queryset().filter(is_old_archive=True, direction='INCOMING')
        qs = get_user_letter_queryset(self.request.user, qs)
        qs = qs.select_related('assigned_department', 'created_by', 'category')
        search = self.request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(build_letter_search_query(search))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['list_title'] = 'Old Archive — Incoming'
        ctx['archive_direction'] = 'incoming'
        ctx['create_url'] = reverse_lazy('letters:old_archive_incoming_create')
        return ctx

    def get(self, request, *args, **kwargs):
        clean_url = clean_archive_url(request.get_full_path())
        request.session['last_old_archive_url'] = clean_url
        request.session['last_old_archive_incoming_url'] = clean_url
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            queryset = self.get_queryset()
            if export_format == 'excel':
                return export_letters_to_excel(queryset, 'Old_Archive_Incoming')
            elif export_format == 'pdf':
                return export_letters_to_pdf(queryset, 'Old_Archive_Incoming')
        return super().get(request, *args, **kwargs)


class OldArchiveOutgoingListView(LoginRequiredMixin, AjaxListMixin, FilterView):
    """List view for old archived outgoing letters."""
    model = Letter
    template_name = 'letters/old_archive_list.html'
    context_object_name = 'letters'
    filterset_class = LetterFilter
    paginate_by = 20
    ajax_partial_template_name = 'letters/includes/old_archive_table_partial.html'

    def get_queryset(self):
        qs = super().get_queryset().filter(is_old_archive=True, direction='OUTGOING')
        qs = get_user_letter_queryset(self.request.user, qs)
        qs = qs.select_related('assigned_department', 'created_by', 'category')
        search = self.request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(build_letter_search_query(search))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['list_title'] = 'Old Archive — Outgoing'
        ctx['archive_direction'] = 'outgoing'
        ctx['create_url'] = reverse_lazy('letters:old_archive_outgoing_create')
        return ctx

    def get(self, request, *args, **kwargs):
        clean_url = clean_archive_url(request.get_full_path())
        request.session['last_old_archive_url'] = clean_url
        request.session['last_old_archive_outgoing_url'] = clean_url
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            queryset = self.get_queryset()
            if export_format == 'excel':
                return export_letters_to_excel(queryset, 'Old_Archive_Outgoing')
            elif export_format == 'pdf':
                return export_letters_to_pdf(queryset, 'Old_Archive_Outgoing')
        return super().get(request, *args, **kwargs)


class OldArchiveIncomingCreateView(LoginRequiredMixin, CreateView):
    """Create view for registering an old incoming paper letter."""
    model = Letter
    form_class = OldArchiveIncomingForm
    template_name = 'letters/old_archive_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.is_old_archive = True
        form.instance.status = Letter.ARCHIVED
        response = super().form_valid(form)

        # Handle optional scanned document
        scanned_file = self.request.FILES.get('scanned_copy')
        if scanned_file:
            Attachment.objects.create(
                letter=self.object,
                file=scanned_file,
                uploaded_by=self.request.user,
            )

        ActionLog.objects.create(
            letter=self.object,
            action='Old archive paper letter registered (Incoming)',
            action_by=self.request.user,
        )
        messages.success(
            self.request,
            f'Paper archive letter "{self.object.subject[:50]}" registered successfully.',
        )
        return response

    def get_success_url(self):
        next_url = clean_archive_url(self.request.POST.get('next') or self.request.GET.get('next'))
        if next_url and next_url.startswith('/'):
            return next_url
        session_url = self.request.session.get('last_old_archive_incoming_url') or self.request.session.get('last_old_archive_url')
        if session_url and session_url.startswith('/'):
            return session_url
        return reverse('letters:old_archive_incoming_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'Register Old Incoming Paper Letter'
        ctx['is_old_archive'] = True
        next_url = clean_archive_url(self.request.GET.get('next') or self.request.POST.get('next'))
        if not next_url:
            next_url = self.request.session.get('last_old_archive_incoming_url') or reverse('letters:old_archive_incoming_list')
        ctx['next_url'] = next_url
        ctx['cancel_url'] = next_url
        try:
            ctx['common_senders'] = list(
                Letter.objects.exclude(sender='').values_list('sender', flat=True).distinct()[:30]
            )
        except Exception:
            ctx['common_senders'] = []
        ctx['common_recipients'] = []
        return ctx


class OldArchiveOutgoingCreateView(LoginRequiredMixin, CreateView):
    """Create view for registering an old outgoing paper letter."""
    model = Letter
    form_class = OldArchiveOutgoingForm
    template_name = 'letters/old_archive_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.is_old_archive = True
        form.instance.status = Letter.ARCHIVED
        response = super().form_valid(form)

        # Handle optional scanned document
        scanned_file = self.request.FILES.get('scanned_copy')
        if scanned_file:
            Attachment.objects.create(
                letter=self.object,
                file=scanned_file,
                uploaded_by=self.request.user,
            )

        ActionLog.objects.create(
            letter=self.object,
            action='Old archive paper letter registered (Outgoing)',
            action_by=self.request.user,
        )
        messages.success(
            self.request,
            f'Paper archive letter "{self.object.subject[:50]}" registered successfully.',
        )
        return response

    def get_success_url(self):
        next_url = clean_archive_url(self.request.POST.get('next') or self.request.GET.get('next'))
        if next_url and next_url.startswith('/'):
            return next_url
        session_url = self.request.session.get('last_old_archive_outgoing_url') or self.request.session.get('last_old_archive_url')
        if session_url and session_url.startswith('/'):
            return session_url
        return reverse('letters:old_archive_outgoing_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'Register Old Outgoing Paper Letter'
        ctx['is_old_archive'] = True
        next_url = clean_archive_url(self.request.GET.get('next') or self.request.POST.get('next'))
        if not next_url:
            next_url = self.request.session.get('last_old_archive_outgoing_url') or reverse('letters:old_archive_outgoing_list')
        ctx['next_url'] = next_url
        ctx['cancel_url'] = next_url
        ctx['common_senders'] = []
        try:
            ctx['common_recipients'] = list(
                Letter.objects.exclude(recipient='').values_list('recipient', flat=True).distinct()[:30]
            )
        except Exception:
            ctx['common_recipients'] = []
        return ctx


class OldArchiveImportView(LoginRequiredMixin, FormView):
    """View to bulk import old archived letters from an Excel file."""
    form_class = OldArchiveExcelImportForm
    template_name = 'letters/old_archive_import.html'
    direction = 'INCOMING'

    def get_direction(self):
        dir_param = self.kwargs.get('direction') or self.request.GET.get('direction')
        if dir_param and dir_param.upper() in ('INCOMING', 'OUTGOING'):
            return dir_param.upper()
        return self.direction

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cur_dir = self.get_direction()
        ctx['direction'] = cur_dir
        ctx['direction_display'] = 'Incoming' if cur_dir == 'INCOMING' else 'Outgoing'
        ctx['page_title'] = f'Import Old {ctx["direction_display"]} Paper Letters from Excel'
        ctx['cancel_url'] = reverse('letters:old_archive_incoming_list') if cur_dir == 'INCOMING' else reverse('letters:old_archive_outgoing_list')
        ctx['template_download_url'] = reverse('letters:old_archive_template_download') + f'?direction={cur_dir}'
        return ctx

    def form_valid(self, form):
        excel_file = form.cleaned_data['excel_file']
        date_mode = form.cleaned_data.get('date_mode', 'AUTO')
        assigned_dept = form.cleaned_data.get('assigned_department')
        category = form.cleaned_data.get('category')
        archive_notes = form.cleaned_data.get('archive_notes', '')
        direction = self.get_direction()

        result = import_archive_letters_from_excel(
            file_obj=excel_file,
            user=self.request.user,
            direction=direction,
            default_dept=assigned_dept,
            default_cat=category,
            default_notes=archive_notes,
            date_mode=date_mode,
        )

        if result['success']:
            msg = f"Successfully imported {result['imported_count']} {direction.lower()} paper letter(s) into the archive!"
            if result['skipped_count']:
                msg += f" ({result['skipped_count']} empty row(s) skipped)."
            messages.success(self.request, msg)
            if direction == 'INCOMING':
                return redirect('letters:old_archive_incoming_list')
            return redirect('letters:old_archive_outgoing_list')
        else:
            for err in result['errors']:
                messages.error(self.request, err)
            return self.form_invalid(form)


class OldArchiveTemplateDownloadView(LoginRequiredMixin, View):
    """Download a pre-formatted sample Excel template for old paper archive imports."""
    def get(self, request, *args, **kwargs):
        direction = request.GET.get('direction', 'INCOMING').upper()
        if direction not in ('INCOMING', 'OUTGOING'):
            direction = 'INCOMING'
        excel_stream = generate_sample_archive_excel(direction=direction)
        filename = f"old_archive_{direction.lower()}_template.xlsx"
        response = HttpResponse(
            excel_stream.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# ---------------------------------------------------------------------------
# Letter detail
# ---------------------------------------------------------------------------
class LetterDetailView(LoginRequiredMixin, CanViewLetterMixin, DetailView):
    model = Letter
    template_name = 'letters/letter_detail.html'
    context_object_name = 'letter'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'assigned_department', 'assigned_person',
            'created_by', 'related_letter', 'category',
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        letter = self.object
        can_close = user_can_close(self.request.user, letter)

        ctx['attachments'] = letter.attachments.select_related('uploaded_by')
        ctx['action_logs'] = letter.actions.select_related('action_by')
        ctx['action_form'] = ActionLogForm(can_close=can_close, letter=letter)
        ctx['attachment_form'] = AttachmentForm()
        ctx['can_close'] = can_close
        ctx['is_admin'] = self.request.user.is_superuser or self.request.user.groups.filter(name='Admin').exists()
        ctx['can_view_attachment_logs'] = user_can_view_attachment_logs(self.request.user)
        ctx['related_replies'] = letter.replies.select_related(
            'assigned_department', 'assigned_person',
        )

        ctx['action_count'] = ctx['action_logs'].count()
        
        # Set status flow based on letter direction
        if letter.direction == Letter.INCOMING:
            ctx['status_flow'] = [
                (val, label) for val, label in Letter.STATUS_CHOICES
                if val in ['RECEIVED', 'IN_REVIEW', 'ACTIONED', 'RESPONDED', 'CLOSED', 'ARCHIVED']
            ]
        elif letter.direction == Letter.OUTGOING:
            ctx['status_flow'] = [
                (val, label) for val, label in Letter.STATUS_CHOICES
                if val in ['DRAFTED', 'IN_REVIEW', 'SUBMITTED', 'RESPONDED', 'ARCHIVED']
            ]
        else:
            ctx['status_flow'] = Letter.STATUS_CHOICES

        if getattr(letter, 'is_old_archive', False):
            if letter.direction == Letter.INCOMING:
                ctx['back_url'] = reverse('letters:old_archive_incoming_list')
                ctx['back_label'] = 'Old Archive — Incoming'
            else:
                ctx['back_url'] = reverse('letters:old_archive_outgoing_list')
                ctx['back_label'] = 'Old Archive — Outgoing'
        elif letter.direction == Letter.INCOMING:
            ctx['back_url'] = reverse('letters:incoming_letter_list')
            ctx['back_label'] = 'Incoming Letters'
        elif letter.direction == Letter.OUTGOING:
            ctx['back_url'] = reverse('letters:outgoing_letter_list')
            ctx['back_label'] = 'Outgoing Letters'
        else:
            ctx['back_url'] = reverse('letters:letter_list')
            ctx['back_label'] = 'All Letters'

        return ctx


# ---------------------------------------------------------------------------
# Create / Edit letter
# ---------------------------------------------------------------------------
class LetterCreateView(LoginRequiredMixin, CreateView):
    model = Letter
    form_class = LetterForm
    template_name = 'letters/letter_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        ActionLog.objects.create(
            letter=self.object,
            action=f'Letter created ({self.object.get_direction_display()})',
            action_by=self.request.user,
        )
        
        # Send assignment notification if assigned to someone
        if self.object.assigned_person:
            send_assignment_notification(self.object)
            # Create in-app notification
            create_notification(
                recipient=self.object.assigned_person,
                notification_type='letter_assigned',
                title=f'Letter Assigned: {self.object.reference_no}',
                message=f'You have been assigned to letter "{self.object.subject}"',
                related_letter=self.object
            )
        
        messages.success(
            self.request,
            f'Letter {self.object.reference_no} created successfully.',
        )
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'Register New Letter'
        try:
            ctx['common_senders'] = list(
                Letter.objects.exclude(sender='').values_list('sender', flat=True).distinct()[:30]
            )
            ctx['common_recipients'] = list(
                Letter.objects.exclude(recipient='').values_list('recipient', flat=True).distinct()[:30]
            )
        except Exception:
            ctx['common_senders'] = []
            ctx['common_recipients'] = []
        return ctx


class IncomingLetterCreateView(LetterCreateView):
    """Create view specifically for incoming letters."""
    form_class = IncomingLetterForm
    
    def get_initial(self):
        return {'direction': Letter.INCOMING}
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'Register Incoming Letter'
        return ctx
    
    def get_success_url(self):
        return reverse('letters:incoming_letter_list')


class OutgoingLetterCreateView(LetterCreateView):
    """Create view specifically for outgoing letters."""
    form_class = OutgoingLetterForm
    
    def get_initial(self):
        return {'direction': Letter.OUTGOING}
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['form_title'] = 'Register Outgoing Letter'
        return ctx
    
    def get_success_url(self):
        return reverse('letters:outgoing_letter_list')


class LetterUpdateView(LoginRequiredMixin, CanViewLetterMixin, UpdateView):
    model = Letter
    template_name = 'letters/letter_form.html'

    def get_form_class(self):
        """Use appropriate form based on letter direction and archive status."""
        if getattr(self.object, 'is_old_archive', False):
            if self.object.direction == Letter.OUTGOING:
                return OldArchiveOutgoingForm
            return OldArchiveIncomingForm
        if self.object.direction == Letter.INCOMING:
            return IncomingLetterForm
        elif self.object.direction == Letter.OUTGOING:
            return OutgoingLetterForm
        return LetterForm

    def get_template_names(self):
        if getattr(self.object, 'is_old_archive', False):
            return ['letters/old_archive_form.html']
        return [self.template_name]

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        is_archive = getattr(self.object, 'is_old_archive', False)
        if is_archive:
            form.instance.is_old_archive = True
            form.instance.status = Letter.ARCHIVED

        old_assigned_person = self.object.assigned_person
        old_status = self.object.status

        response = super().form_valid(form)

        if is_archive:
            scanned_file = self.request.FILES.get('scanned_copy')
            if scanned_file:
                Attachment.objects.create(
                    letter=self.object,
                    file=scanned_file,
                    uploaded_by=self.request.user,
                )
            ActionLog.objects.create(
                letter=self.object,
                action='Paper archive letter updated',
                action_by=self.request.user,
            )
            messages.success(
                self.request,
                f'Paper archive letter "{self.object.subject[:50]}" updated successfully.',
            )
            return response

        ActionLog.objects.create(
            letter=self.object,
            action='Letter details updated',
            action_by=self.request.user,
        )

        # Send assignment notification if assigned person changed
        if self.object.assigned_person and self.object.assigned_person != old_assigned_person:
            send_assignment_notification(self.object)
            # Create in-app notification
            create_notification(
                recipient=self.object.assigned_person,
                notification_type='letter_assigned',
                title=f'Letter Assigned: {self.object.reference_no}',
                message=f'You have been assigned to letter "{self.object.subject}"',
                related_letter=self.object
            )

        # Send status change notification if status changed
        if self.object.status != old_status:
            send_status_change_notification(self.object, old_status, self.object.status)
            # Create in-app notification for assigned person
            if self.object.assigned_person:
                create_notification(
                    recipient=self.object.assigned_person,
                    notification_type='status_changed',
                    title=f'Status Changed: {self.object.reference_no}',
                    message=f'Letter status changed from {old_status} to {self.object.status}',
                    related_letter=self.object
                )

        messages.success(
            self.request,
            f'Letter {self.object.reference_no} updated.',
        )
        return response

    def get_success_url(self):
        next_url = clean_archive_url(self.request.POST.get('next') or self.request.GET.get('next'))
        if next_url and next_url.startswith('/'):
            return next_url

        if getattr(self.object, 'is_old_archive', False):
            if self.object.direction == Letter.OUTGOING:
                session_url = self.request.session.get('last_old_archive_outgoing_url') or self.request.session.get('last_old_archive_url')
                if session_url and session_url.startswith('/'):
                    return session_url
                return reverse('letters:old_archive_outgoing_list')
            else:
                session_url = self.request.session.get('last_old_archive_incoming_url') or self.request.session.get('last_old_archive_url')
                if session_url and session_url.startswith('/'):
                    return session_url
                return reverse('letters:old_archive_incoming_list')

        return self.object.get_absolute_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if getattr(self.object, 'is_old_archive', False):
            ctx['is_old_archive'] = True
            direction_label = 'Incoming' if self.object.direction == Letter.INCOMING else 'Outgoing'
            ctx['form_title'] = f'Edit Old Archive {direction_label} Letter'
            next_url = clean_archive_url(self.request.GET.get('next') or self.request.POST.get('next'))
            if not next_url:
                if self.object.direction == Letter.OUTGOING:
                    next_url = self.request.session.get('last_old_archive_outgoing_url') or reverse('letters:old_archive_outgoing_list')
                else:
                    next_url = self.request.session.get('last_old_archive_incoming_url') or reverse('letters:old_archive_incoming_list')
            ctx['next_url'] = next_url
            ctx['cancel_url'] = next_url
        else:
            ctx['form_title'] = f'Edit: {self.object.reference_no}'
        try:
            ctx['common_senders'] = list(
                Letter.objects.exclude(sender='').values_list('sender', flat=True).distinct()[:30]
            )
            ctx['common_recipients'] = list(
                Letter.objects.exclude(recipient='').values_list('recipient', flat=True).distinct()[:30]
            )
        except Exception:
            ctx['common_senders'] = []
            ctx['common_recipients'] = []
        return ctx


class LetterDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a letter - only for superusers."""
    model = Letter
    template_name = 'letters/letter_confirm_delete.html'
    success_url = reverse_lazy('letters:letter_list')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Only superusers can delete letters.')
            return redirect('letters:letter_detail', pk=self.get_object().pk)
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        letter = self.get_object()
        messages.success(request, f'Letter {letter.reference_no} has been deleted.')
        return super().delete(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Action log (POST from detail page)
# ---------------------------------------------------------------------------
class AddActionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        letters_qs = get_user_letter_queryset(request.user)
        letter = get_object_or_404(letters_qs, pk=pk)
        can_close = user_can_close(request.user, letter)
        form = ActionLogForm(request.POST, can_close=can_close, letter=letter)

        if form.is_valid():
            action_text = form.cleaned_data.get('action', '').strip()
            notes_text = form.cleaned_data.get('notes', '').strip()
            new_status = form.cleaned_data.get('new_status')

            # Prevent saving empty logs if no action, notes, or status change was given
            if not action_text and not notes_text and not new_status:
                messages.warning(request, 'Please provide an action, note, or status update.')
                return redirect(letter.get_absolute_url())

            # If action text is empty but notes or status change is present, provide a sensible default action title
            if not action_text:
                if notes_text:
                    action_text = 'Note Added'
                elif new_status:
                    action_text = f'Status update to {dict(Letter.STATUS_CHOICES).get(new_status, new_status)}'

            action_log = form.save(commit=False)
            action_log.action = action_text
            action_log.notes = notes_text
            action_log.letter = letter
            action_log.action_by = request.user
            action_log.save()

            # Send notification for new action
            send_new_action_notification(letter, action_log.action, request.user)
            # Create in-app notification for assigned person
            if letter.assigned_person and letter.assigned_person != request.user:
                create_notification(
                    recipient=letter.assigned_person,
                    notification_type='action_added',
                    title=f'Action Added: {letter.reference_no}',
                    message=f'New action added: "{action_log.action}"',
                    related_letter=letter
                )

            # Optionally update letter status
            if new_status:
                if new_status in ('CLOSED', 'ARCHIVED'):
                    if not user_can_close(request.user, letter):
                        messages.error(
                            request,
                            'Only the assigned person or admin can '
                            'close/archive letters.',
                        )
                        return redirect(letter.get_absolute_url())

                old_display = letter.get_status_display()
                letter.status = new_status
                letter.save(update_fields=['status', 'updated_at'])

                new_display = letter.get_status_display()
                ActionLog.objects.create(
                    letter=letter,
                    action=f'Status changed: {old_display} → {new_display}',
                    action_by=request.user,
                )
                
                # Send status change notification
                send_status_change_notification(letter, old_display, new_display)

            messages.success(request, 'Action and notes logged successfully.')
        else:
            messages.error(request, 'Error logging action. Please check the form.')

        return redirect(letter.get_absolute_url())


# ---------------------------------------------------------------------------
# Attachment upload (POST from detail page)
# ---------------------------------------------------------------------------
class AddAttachmentView(LoginRequiredMixin, View):
    def get(self, request, pk):
        letters_qs = get_user_letter_queryset(request.user)
        letter = get_object_or_404(letters_qs, pk=pk)
        return redirect(f"{letter.get_absolute_url()}#attachment-form")

    def post(self, request, pk):
        letters_qs = get_user_letter_queryset(request.user)
        letter = get_object_or_404(letters_qs, pk=pk)
        form = AttachmentForm(request.POST, request.FILES)

        if form.is_valid():
            try:
                att = form.save(commit=False)
                att.letter = letter
                att.uploaded_by = request.user
                
                # Debug logging
                print(f"Storage backend: {att.file.storage}")
                print(f"File name before save: {att.file.name}")
                print(f"USE_R2_STORAGE: {os.environ.get('USE_R2_STORAGE')}")
                
                att.save()
                
                print(f"File name after save: {att.file.name}")
                print(f"File URL: {att.file.url}")

                ActionLog.objects.create(
                    letter=letter,
                    action=f'Attachment added: {att.filename}',
                    action_by=request.user,
                )
                messages.success(request, 'Attachment uploaded successfully.')
            except Exception as e:
                print(f"Error saving attachment: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f'Error saving attachment: {str(e)}')
        else:
            # Display specific form validation errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')

        return redirect(letter.get_absolute_url())


# ---------------------------------------------------------------------------
# Attachment delete (for admin users)
# ---------------------------------------------------------------------------
class AttachmentDeleteView(LoginRequiredMixin, View):
    """Delete an attachment - only for admin/superuser users."""
    def post(self, request, letter_pk, attachment_pk):
        letters_qs = get_user_letter_queryset(request.user)
        letter = get_object_or_404(letters_qs, pk=letter_pk)
        
        # Check if user is admin or superuser
        if not (request.user.is_superuser or request.user.groups.filter(name='Admin').exists()):
            messages.error(request, 'Only admin users can delete attachments.')
            return redirect(letter.get_absolute_url())
        
        attachment = get_object_or_404(letter.attachments, pk=attachment_pk)
        filename = attachment.filename
        attachment.delete()
        
        ActionLog.objects.create(
            letter=letter,
            action=f'Attachment deleted: {filename}',
            action_by=request.user,
        )
        messages.success(request, f'Attachment "{filename}" deleted successfully.')
        
        return redirect(letter.get_absolute_url())


# ---------------------------------------------------------------------------
# Track Attachment Interaction (View, Download, Share)
# ---------------------------------------------------------------------------
class TrackAttachmentView(LoginRequiredMixin, View):
    """Record a view/download/share action on an attachment by staff."""
    def post(self, request, pk):
        attachment = get_object_or_404(Attachment, pk=pk)
        if not user_can_view_letter(request.user, attachment.letter):
            return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        try:
            data = json.loads(request.body)
            action = data.get('action', AttachmentView.VIEW)
        except (json.JSONDecodeError, AttributeError):
            action = request.POST.get('action', AttachmentView.VIEW)

        if action not in [AttachmentView.VIEW, AttachmentView.DOWNLOAD, AttachmentView.SHARE]:
            action = AttachmentView.VIEW

        # Create interaction log
        AttachmentView.objects.create(
            attachment=attachment,
            user=request.user,
            action=action
        )

        total_views = attachment.views.count()
        unique_staff = attachment.views.values('user').distinct().count()

        return JsonResponse({
            'success': True,
            'total_views': total_views,
            'unique_staff': unique_staff,
        })


class AttachmentViewersListView(LoginRequiredMixin, View):
    """Retrieve list of staff members who viewed/downloaded/shared an attachment."""
    def get(self, request, pk):
        attachment = get_object_or_404(Attachment, pk=pk)
        if not user_can_view_attachment_logs(request.user, attachment):
            return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        views_qs = attachment.views.select_related('user').order_by('-viewed_at')[:50]

        viewers = []
        for v in views_qs:
            full_name = v.user.get_full_name() or v.user.username
            viewers.append({
                'user_name': full_name,
                'username': v.user.username,
                'action': v.get_action_display(),
                'action_code': v.action,
                'viewed_at': v.viewed_at.strftime('%b %d, %Y %I:%M %p'),
                'time_ago': timesince(v.viewed_at) + ' ago',
            })

        total_count = attachment.views.count()
        unique_count = attachment.views.values('user').distinct().count()

        return JsonResponse({
            'success': True,
            'attachment_filename': attachment.filename,
            'total_count': total_count,
            'unique_count': unique_count,
            'viewers': viewers,
        })


# ---------------------------------------------------------------------------
# Overdue letters
# ---------------------------------------------------------------------------
class OverdueLettersView(LoginRequiredMixin, ListView):
    template_name = 'letters/overdue_list.html'
    context_object_name = 'letters'
    paginate_by = 20

    def get_queryset(self):
        today = timezone.now().date()
        qs = Letter.objects.filter(due_date__lt=today).exclude(status__in=['ARCHIVED'])
        qs = get_user_letter_queryset(self.request.user, qs)
        return qs.select_related('assigned_department', 'assigned_person')


# ---------------------------------------------------------------------------
# Bulk Actions
# ---------------------------------------------------------------------------
class BulkActionView(LoginRequiredMixin, View):
    """Handle bulk actions on multiple letters."""
    
    def post(self, request):
        action = request.POST.get('action')
        letter_ids = request.POST.getlist('letter_ids')
        
        if not letter_ids:
            messages.error(request, 'No letters selected.')
            return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))
        
        letters_qs = get_user_letter_queryset(request.user)
        letters = Letter.objects.filter(pk__in=letter_ids)
        
        # Ensure user can only act on letters they have access to
        accessible_ids = set(letters_qs.filter(pk__in=letter_ids).values_list('pk', flat=True))
        letters = letters.filter(pk__in=accessible_ids)
        
        count = 0
        
        if action == 'delete':
            if not request.user.is_superuser:
                messages.error(request, 'Only superusers can delete letters.')
                return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))
            
            count = letters.count()
            letters.delete()
            messages.success(request, f'{count} letter(s) deleted successfully.')
        
        elif action == 'close':
            for letter in letters:
                if user_can_close(request.user, letter):
                    old_status = letter.status
                    # Use CLOSED for incoming, ARCHIVED for outgoing
                    if letter.direction == Letter.INCOMING:
                        new_status = 'CLOSED'
                    else:
                        new_status = 'ARCHIVED'
                    letter.status = new_status
                    letter.save(update_fields=['status', 'updated_at'])
                    ActionLog.objects.create(
                        letter=letter,
                        action=f'Status changed: {old_status} → {new_status} (bulk action)',
                        action_by=request.user,
                    )
                    send_status_change_notification(letter, old_status, new_status)
                    count += 1
            messages.success(request, f'{count} letter(s) closed/archived successfully.')
        
        elif action == 'archive':
            for letter in letters:
                if user_can_close(request.user, letter):
                    old_status = letter.status
                    letter.status = 'ARCHIVED'
                    letter.save(update_fields=['status', 'updated_at'])
                    ActionLog.objects.create(
                        letter=letter,
                        action=f'Status changed: {old_status} → ARCHIVED (bulk action)',
                        action_by=request.user,
                    )
                    send_status_change_notification(letter, old_status, 'ARCHIVED')
                    count += 1
            messages.success(request, f'{count} letter(s) archived successfully.')
        
        elif action == 'reopen':
            for letter in letters:
                old_status = letter.status
                letter.status = 'IN_REVIEW'
                letter.save(update_fields=['status', 'updated_at'])
                ActionLog.objects.create(
                    letter=letter,
                    action=f'Status changed: {old_status} → IN_REVIEW (bulk action)',
                    action_by=request.user,
                )
                send_status_change_notification(letter, old_status, 'IN_REVIEW')
                count += 1
            messages.success(request, f'{count} letter(s) reopened successfully.')
        
        elif action.startswith('assign_to_'):
            user_id = action.replace('assign_to_', '')
            try:
                assign_to = User.objects.get(pk=user_id)
                for letter in letters:
                    old_assigned = letter.assigned_person
                    letter.assigned_person = assign_to
                    letter.save(update_fields=['assigned_person', 'updated_at'])
                    ActionLog.objects.create(
                        letter=letter,
                        action=f'Assigned to {assign_to.get_full_name() or assign_to.username} (bulk action)',
                        action_by=request.user,
                    )
                    if old_assigned != assign_to:
                        send_assignment_notification(letter)
                    count += 1
                messages.success(request, f'{count} letter(s) assigned to {assign_to.get_full_name() or assign_to.username}.')
            except User.DoesNotExist:
                messages.error(request, 'Invalid user selected.')
        
        else:
            messages.error(request, 'Invalid action selected.')
        
        return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))


# ---------------------------------------------------------------------------
# Saved Searches
# ---------------------------------------------------------------------------
class SaveSearchView(LoginRequiredMixin, View):
    """Save current search query for quick access."""
    
    def post(self, request):
        name = request.POST.get('name')
        query_string = request.GET.urlencode()
        
        if not name:
            messages.error(request, 'Please provide a name for your saved search.')
            return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))
        
        # Remove empty parameters
        params = request.GET.copy()
        for key in list(params.keys()):
            if not params[key]:
                del params[key]
        query_string = params.urlencode()
        
        if not query_string:
            messages.error(request, 'Cannot save an empty search.')
            return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))
        
        SavedSearch.objects.update_or_create(
            user=request.user,
            name=name,
            defaults={'query_string': query_string}
        )
        
        messages.success(request, f'Search "{name}" saved successfully.')
        return redirect(request.META.get('HTTP_REFERER', reverse('letters:letter_list')))


class DeleteSearchView(LoginRequiredMixin, DeleteView):
    """Delete a saved search."""
    model = SavedSearch
    template_name = 'includes/confirm_delete.html'
    
    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)
    
    def get_success_url(self):
        return reverse('letters:letter_list')
    
    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Saved search deleted successfully.')
        return super().delete(request, *args, **kwargs)


class ExportActionsView(LoginRequiredMixin, View):
    """Export action logs for a letter to Excel/PDF."""
    
    def get(self, request, pk):
        letters_qs = get_user_letter_queryset(request.user)
        letter = get_object_or_404(letters_qs, pk=pk)
        actions = letter.actions.select_related('action_by')
        
        export_format = request.GET.get('export', 'excel')
        
        if export_format == 'excel':
            from .export_utils import export_letters_to_excel
            # Create a simple Excel export for actions
            from openpyxl import Workbook
            from io import BytesIO
            from django.http import HttpResponse
            
            output = BytesIO()
            wb = Workbook()
            ws = wb.active
            ws.title = "Actions"
            
            # Headers
            headers = ['Date', 'Action', 'Action By', 'Notes']
            for col_num, header in enumerate(headers, 1):
                ws.cell(row=1, column=col_num, value=header)
            
            # Data
            for row_num, action in enumerate(actions, 2):
                ws.cell(row=row_num, column=1, value=action.action_date.strftime('%Y-%m-%d %H:%M'))
                ws.cell(row=row_num, column=2, value=action.action)
                ws.cell(row=row_num, column=3, value=str(action.action_by) if action.action_by else '')
                ws.cell(row=row_num, column=4, value=action.notes or '')
            
            wb.save(output)
            output.seek(0)
            
            response = HttpResponse(
                output.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="actions_{letter.reference_no}.xlsx"'
            return response
        
        return redirect(letter.get_absolute_url())


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class ReportsView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/reports.html'

    def get(self, request, *args, **kwargs):
        # Handle export requests
        export_format = request.GET.get('export')
        if export_format in ('excel', 'pdf'):
            from .export_utils import export_letters_to_excel, export_letters_to_pdf
            from .models import Letter
            
            base_qs = get_user_letter_queryset(request.user, Letter.objects.all())
            
            date_from = request.GET.get('date_from')
            date_to = request.GET.get('date_to')
            eth_date_from = request.GET.get('eth_date_from')
            eth_date_to = request.GET.get('eth_date_to')

            from .ethiopian_calendar import parse_ethiopian_date
            if eth_date_from and not date_from:
                try:
                    date_from = parse_ethiopian_date(eth_date_from)
                except Exception:
                    pass
            if eth_date_to and not date_to:
                try:
                    date_to = parse_ethiopian_date(eth_date_to)
                except Exception:
                    pass
            
            if date_from:
                base_qs = base_qs.filter(date__gte=date_from)
            if date_to:
                base_qs = base_qs.filter(date__lte=date_to)
            
            if export_format == 'excel':
                return export_letters_to_excel(base_qs, 'Reports_Data')
            elif export_format == 'pdf':
                return export_letters_to_pdf(base_qs, 'Reports_Data')
        return super().get(request, *args, **kwargs)


class ReportsDataView(LoginRequiredMixin, View):
    """JSON endpoint consumed by Chart.js on the reports page."""

    def get(self, request):
        today = timezone.now().date()
        user = request.user
        base_qs = get_user_letter_queryset(user)
        
        # Apply date range filters (Gregorian and Ethiopian)
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        eth_date_from = request.GET.get('eth_date_from')
        eth_date_to = request.GET.get('eth_date_to')

        from .ethiopian_calendar import parse_ethiopian_date
        if eth_date_from and not date_from:
            try:
                date_from = parse_ethiopian_date(eth_date_from)
            except Exception:
                pass
        if eth_date_to and not date_to:
            try:
                date_to = parse_ethiopian_date(eth_date_to)
            except Exception:
                pass
        
        if date_from:
            base_qs = base_qs.filter(date__gte=date_from)
        if date_to:
            base_qs = base_qs.filter(date__lte=date_to)

        # -- Monthly volume (last 12 months) ---------------------------------
        monthly = []
        for i in range(11, -1, -1):
            m = today.month - i
            y = today.year
            while m <= 0:
                m += 12
                y -= 1
            incoming = base_qs.filter(
                direction='INCOMING', date__year=y, date__month=m,
            ).count()
            outgoing = base_qs.filter(
                direction='OUTGOING', date__year=y, date__month=m,
            ).count()
            monthly.append({
                'month': f'{calendar.month_abbr[m]} {y}',
                'incoming': incoming,
                'outgoing': outgoing,
            })

        # -- By department ---------------------------------------------------
        dept_data = list(
            base_qs
            .values('assigned_department__name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # -- By category -----------------------------------------------------
        cat_data = [
            {'category': item['category__name'] or 'Uncategorized', 'count': item['count']}
            for item in base_qs.values('category__name').annotate(count=Count('id')).order_by('-count')
        ]

        # -- By status -------------------------------------------------------
        status_data = list(
            base_qs
            .values('status')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        
        # -- By priority -----------------------------------------------------
        priority_data = list(
            base_qs
            .values('priority')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        return JsonResponse({
            'monthly': monthly,
            'by_department': dept_data,
            'by_category': cat_data,
            'by_status': status_data,
            'by_priority': priority_data,
        })


# ---------------------------------------------------------------------------
# Superadmin / System Admin Settings Dashboard and CRUD views
# ---------------------------------------------------------------------------

class AdminDashboardView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, TemplateView):
    template_name = 'admin_dashboard/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_departments'] = Department.objects.count()
        ctx['total_categories'] = Category.objects.count()
        ctx['total_staff'] = User.objects.filter(is_active=True).count()
        ctx['total_letters'] = Letter.objects.count()
        ctx['recent_staff'] = User.objects.order_by('-date_joined')[:5]
        ctx['recent_letters'] = Letter.objects.order_by('-created_at')[:5]
        ctx['system_setting'] = SystemSetting.get_settings()
        return ctx


class AdminToggleAISettingView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, View):
    """Enable or disable AI Assistant and OCR features system-wide."""
    def post(self, request, *args, **kwargs):
        setting = SystemSetting.get_settings()
        feature = request.POST.get('feature', '')
        enable = request.POST.get('enable') in ['true', '1', 'on']

        if feature == 'ai_assistant':
            setting.ai_assistant_enabled = enable
            setting.updated_by = request.user
            setting.save()
            status_text = "enabled" if enable else "disabled"
            messages.success(request, f"AI Platform Assistant has been {status_text}.")
        elif feature == 'ai_ocr':
            setting.ai_ocr_enabled = enable
            setting.updated_by = request.user
            setting.save()
            status_text = "enabled" if enable else "disabled"
            messages.success(request, f"OCR Auto-Fill scanning has been {status_text}.")
        elif feature == 'all':
            setting.ai_assistant_enabled = enable
            setting.ai_ocr_enabled = enable
            setting.updated_by = request.user
            setting.save()
            status_text = "enabled" if enable else "disabled"
            messages.success(request, f"All AI Platform features have been {status_text}.")

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'ai_assistant_enabled': setting.ai_assistant_enabled,
                'ai_ocr_enabled': setting.ai_ocr_enabled,
            })

        return redirect('letters:admin_dashboard')


# --- Department CRUD ---
class DepartmentListView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, ListView):
    model = Department
    template_name = 'admin_dashboard/department_list.html'
    context_object_name = 'departments'
    paginate_by = 10

    def get_queryset(self):
        return Department.objects.annotate(staff_count=Count('users')).order_by('name')


class DepartmentCreateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, CreateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'admin_dashboard/department_form.html'
    success_url = reverse_lazy('letters:admin_department_list')

    def form_valid(self, form):
        messages.success(self.request, f"Department '{form.instance.name}' created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Department'
        return ctx


class DepartmentUpdateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, UpdateView):
    model = Department
    form_class = DepartmentForm
    template_name = 'admin_dashboard/department_form.html'
    success_url = reverse_lazy('letters:admin_department_list')

    def form_valid(self, form):
        messages.success(self.request, f"Department '{form.instance.name}' updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f"Edit Department: {self.object.name}"
        return ctx


class DepartmentDeleteView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, DeleteView):
    model = Department
    template_name = 'admin_dashboard/department_confirm_delete.html'
    success_url = reverse_lazy('letters:admin_department_list')

    def form_valid(self, form):
        messages.success(self.request, f"Department '{self.object.name}' deleted.")
        return super().form_valid(form)


# --- Category CRUD ---
class CategoryListView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, ListView):
    model = Category
    template_name = 'admin_dashboard/category_list.html'
    context_object_name = 'categories'
    paginate_by = 10

    def get_queryset(self):
        return Category.objects.annotate(letter_count=Count('letters')).order_by('name')


class CategoryCreateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'admin_dashboard/category_form.html'
    success_url = reverse_lazy('letters:admin_category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.instance.name}' created successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Category'
        return ctx


class CategoryUpdateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'admin_dashboard/category_form.html'
    success_url = reverse_lazy('letters:admin_category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.instance.name}' updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f"Edit Category: {self.object.name}"
        return ctx


class CategoryDeleteView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, DeleteView):
    model = Category
    template_name = 'admin_dashboard/category_confirm_delete.html'
    success_url = reverse_lazy('letters:admin_category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{self.object.name}' deleted.")
        return super().form_valid(form)


# --- Staff CRUD ---
class StaffListView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, ListView):
    model = User
    template_name = 'admin_dashboard/staff_list.html'
    context_object_name = 'staff_members'
    paginate_by = 10

    def get_queryset(self):
        return User.objects.prefetch_related('departments', 'groups').order_by('-is_active', 'username')


class StaffCreateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, CreateView):
    model = User
    form_class = StaffForm
    template_name = 'admin_dashboard/staff_form.html'
    success_url = reverse_lazy('letters:admin_staff_list')

    def form_valid(self, form):
        messages.success(self.request, f"Staff account '{form.instance.username}' registered successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Register Staff Member'
        return ctx


class StaffUpdateView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, UpdateView):
    model = User
    form_class = StaffForm
    template_name = 'admin_dashboard/staff_form.html'
    success_url = reverse_lazy('letters:admin_staff_list')

    def form_valid(self, form):
        messages.success(self.request, f"Staff account '{form.instance.username}' updated.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f"Edit Staff Account: {self.object.username}"
        return ctx


class StaffDeleteView(LoginRequiredMixin, SuperuserOrAdminRequiredMixin, DeleteView):
    model = User
    template_name = 'admin_dashboard/staff_confirm_delete.html'
    success_url = reverse_lazy('letters:admin_staff_list')

    def form_valid(self, form):
        messages.success(self.request, f"Staff account '{self.object.username}' deleted.")
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Super Admin Custom SMS Broadcast
# ---------------------------------------------------------------------------
class CustomSMSView(LoginRequiredMixin, SuperuserRequiredMixin, View):
    """
    Super Admin only: Send custom SMS messages to staff members, departments,
    or external phone numbers via AfroMessage.
    """
    template_name = 'admin_dashboard/custom_sms.html'

    def get(self, request):
        staff_members = User.objects.filter(is_active=True).select_related('profile').prefetch_related('departments', 'groups').order_by('username')
        departments = Department.objects.annotate(
            active_staff_count=Count('users', filter=Q(users__is_active=True))
        ).order_by('name')

        staff_with_phone_count = sum(
            1 for u in staff_members
            if hasattr(u, 'profile') and u.profile.phone_number
        )

        logs = CustomSMSLog.objects.select_related('sender').order_by('-created_at')[:50]

        is_configured = bool(getattr(settings, 'AFROMESSAGE_API_TOKEN', ''))
        sender_name = getattr(settings, 'AFROMESSAGE_SENDER_NAME', '')

        context = {
            'staff_members': staff_members,
            'departments': departments,
            'staff_with_phone_count': staff_with_phone_count,
            'total_staff_count': staff_members.count(),
            'logs': logs,
            'is_configured': is_configured,
            'sender_name': sender_name,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        import re

        message = request.POST.get('message', '').strip()
        recipient_mode = request.POST.get('recipient_mode', 'all_staff')
        department_ids = request.POST.getlist('departments')
        staff_ids = request.POST.getlist('staff_ids')
        external_numbers_raw = request.POST.get('external_numbers', '').strip()

        # Validation
        if not message:
            messages.error(request, 'Please enter an SMS message.')
            return redirect('letters:custom_sms')

        target_recipients = {}  # normalized_phone -> {'name': ..., 'type': 'Staff'|'External', 'user_id': ...}
        skipped_staff = []      # names of staff skipped because no phone number
        invalid_numbers = []    # invalid external numbers

        # 1. Staff selection based on recipient_mode
        if recipient_mode == 'all_staff':
            staff_qs = User.objects.filter(is_active=True).select_related('profile')
            for u in staff_qs:
                phone = getattr(u.profile, 'phone_number', None) if hasattr(u, 'profile') else None
                normalized = normalize_phone_number(phone)
                if normalized:
                    target_recipients[normalized] = {
                        'name': u.get_full_name() or u.username,
                        'type': 'Staff',
                        'user_id': u.id,
                    }
                else:
                    skipped_staff.append(u.get_full_name() or u.username)

        elif recipient_mode == 'by_department':
            if not department_ids:
                messages.error(request, 'Please select at least one department.')
                return redirect('letters:custom_sms')
            staff_qs = User.objects.filter(is_active=True, departments__id__in=department_ids).select_related('profile').distinct()
            for u in staff_qs:
                phone = getattr(u.profile, 'phone_number', None) if hasattr(u, 'profile') else None
                normalized = normalize_phone_number(phone)
                if normalized:
                    target_recipients[normalized] = {
                        'name': u.get_full_name() or u.username,
                        'type': 'Staff',
                        'user_id': u.id,
                    }
                else:
                    skipped_staff.append(u.get_full_name() or u.username)

        elif recipient_mode == 'selected_staff':
            if not staff_ids:
                messages.error(request, 'Please select at least one staff member.')
                return redirect('letters:custom_sms')
            staff_qs = User.objects.filter(is_active=True, id__in=staff_ids).select_related('profile')
            for u in staff_qs:
                phone = getattr(u.profile, 'phone_number', None) if hasattr(u, 'profile') else None
                normalized = normalize_phone_number(phone)
                if normalized:
                    target_recipients[normalized] = {
                        'name': u.get_full_name() or u.username,
                        'type': 'Staff',
                        'user_id': u.id,
                    }
                else:
                    skipped_staff.append(u.get_full_name() or u.username)

        # 2. External / other numbers (can be added with any mode or external_only)
        if external_numbers_raw:
            raw_tokens = [t.strip() for t in re.split(r'[\r\n,;]+', external_numbers_raw) if t.strip()]
            for token in raw_tokens:
                normalized = normalize_phone_number(token)
                if normalized:
                    if normalized not in target_recipients:
                        target_recipients[normalized] = {
                            'name': 'External Contact',
                            'type': 'External',
                            'user_id': None,
                        }
                else:
                    invalid_numbers.append(token)

        if not target_recipients:
            err_msg = 'No valid recipient phone numbers found.'
            if invalid_numbers:
                err_msg += f' Invalid number(s): {", ".join(invalid_numbers[:5])}.'
            if skipped_staff:
                err_msg += f' {len(skipped_staff)} staff member(s) have no phone number in their profile.'
            messages.error(request, err_msg)
            return redirect('letters:custom_sms')

        # 3. Send SMS to all target recipients
        success_count = 0
        failed_count = 0
        delivery_details = []

        target_type_map = {
            'all_staff': 'All Staff',
            'by_department': 'Department Staff',
            'selected_staff': 'Selected Staff',
            'external_only': 'External Numbers',
        }
        target_label = target_type_map.get(recipient_mode, recipient_mode)
        if external_numbers_raw and recipient_mode != 'external_only':
            target_label += ' + External'

        for phone, info in target_recipients.items():
            success, status_msg = send_sms_with_result(phone, message)
            delivery_details.append({
                'phone': phone,
                'name': info['name'],
                'type': info['type'],
                'status': 'success' if success else 'failed',
                'error': '' if success else status_msg,
            })
            if success:
                success_count += 1
            else:
                failed_count += 1

        # 4. Save to CustomSMSLog
        log = CustomSMSLog.objects.create(
            sender=request.user,
            message=message,
            target_type=target_label,
            total_recipients=len(target_recipients),
            success_count=success_count,
            failed_count=failed_count,
            delivery_details=delivery_details,
        )

        # 5. User Feedback
        if failed_count == 0:
            msg_text = f'Custom SMS successfully sent to all {success_count} recipient(s).'
            if skipped_staff:
                msg_text += f' ({len(skipped_staff)} staff without phone numbers were skipped).'
            messages.success(request, msg_text)
        elif success_count > 0:
            messages.warning(
                request,
                f'Custom SMS partially delivered: {success_count} succeeded, {failed_count} failed. Check the broadcast log below.'
            )
        else:
            first_err = delivery_details[0]['error'] if delivery_details else 'Unknown error'
            messages.error(
                request,
                f'Failed to send SMS to any recipient. AfroMessage response: {first_err}'
            )

        if invalid_numbers:
            messages.warning(
                request,
                f'The following numbers were invalid and skipped: {", ".join(invalid_numbers[:5])}'
            )

        return redirect('letters:custom_sms')


class CustomSMSLogDetailView(LoginRequiredMixin, SuperuserRequiredMixin, View):
    """Return JSON details of a CustomSMSLog record for modal inspection."""
    def get(self, request, pk):
        log = get_object_or_404(CustomSMSLog, pk=pk)
        return JsonResponse({
            'id': log.id,
            'sender': log.sender.username if log.sender else 'System',
            'message': log.message,
            'target_type': log.target_type,
            'total_recipients': log.total_recipients,
            'success_count': log.success_count,
            'failed_count': log.failed_count,
            'created_at': log.created_at.strftime('%b %d, %Y %I:%M %p'),
            'delivery_details': log.delivery_details,
        })


# ---------------------------------------------------------------------------
# Short URL redirect for file sharing
# ---------------------------------------------------------------------------
class ShortUrlRedirectView(View):
    """Redirect short URL to actual file URL with analytics."""
    def get(self, request, short_code):
        # Try to find by custom short code first, then regular short code
        attachment = get_object_or_404(Attachment, models.Q(short_code=short_code) | models.Q(custom_short_code=short_code))

        # Check if link has expired
        if attachment.is_expired():
            from django.http import HttpResponse
            return HttpResponse("This link has expired.", status=410)

        # Update analytics
        attachment.access_count += 1
        attachment.last_accessed = timezone.now()
        attachment.save(update_fields=['access_count', 'last_accessed'])

        if request.user.is_authenticated:
            AttachmentView.objects.create(
                attachment=attachment,
                user=request.user,
                action=AttachmentView.SHARE
            )

        return HttpResponseRedirect(attachment.file.url)


class LetterShortUrlRedirectView(LoginRequiredMixin, View):
    """Redirect short URL to letter detail page."""
    def get(self, request, short_code):
        letter = get_object_or_404(Letter, short_code=short_code)
        return HttpResponseRedirect(letter.get_absolute_url())


# ---------------------------------------------------------------------------
# User Profile Management
# ---------------------------------------------------------------------------
class UserProfileView(LoginRequiredMixin, TemplateView):
    """User profile page with profile info, preferences, and password change."""
    template_name = 'letters/user_profile.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Get or create user profile
        profile, created = UserProfile.objects.get_or_create(user=user)
        
        context['profile'] = profile
        context['profile_form'] = UserProfileForm(instance=user)
        context['preferences_form'] = UserPreferencesForm(instance=profile)
        context['password_form'] = CustomPasswordChangeForm(user=user)
        context['vapid_public_key'] = getattr(settings, 'VAPID_PUBLIC_KEY', '')
        context['telegram_bot_username'] = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'aelms_bot')
        context['afromessage_configured'] = bool(getattr(settings, 'AFROMESSAGE_API_TOKEN', ''))
        
        # Calculate profile completion
        completion = 0
        if user.first_name:
            completion += 25
        if user.last_name:
            completion += 25
        if user.email:
            completion += 25
        if profile.avatar:
            completion += 25
        context['profile_completion'] = completion
        
        # Calculate activity stats
        from .models import Letter, Attachment
        
        letters_assigned = Letter.objects.filter(assigned_person=user).count()
        letters_completed = Letter.objects.filter(
            assigned_person=user,
            status__in=['RESPONDED', 'CLOSED', 'ARCHIVED']
        ).count()
        letters_pending = letters_assigned - letters_completed
        attachments_count = Attachment.objects.filter(uploaded_by=user).count()
        
        context['letters_assigned'] = letters_assigned
        context['letters_completed'] = letters_completed
        context['letters_pending'] = letters_pending
        context['attachments_count'] = attachments_count
        
        return context
    
    def post(self, request, *args, **kwargs):
        user = request.user
        profile, created = UserProfile.objects.get_or_create(user=user)
        
        form_type = request.POST.get('form_type')
        
        if form_type == 'profile':
            form = UserProfileForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('letters:user_profile')
        
        elif form_type == 'preferences':
            form = UserPreferencesForm(request.POST, request.FILES, instance=profile)
            if form.is_valid():
                form.save()
                messages.success(request, 'Preferences saved successfully.')
                return redirect('letters:user_profile')
        
        elif form_type == 'password':
            form = CustomPasswordChangeForm(user=user, data=request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, 'Password changed successfully.')
                return redirect('letters:user_profile')
        
        # If form is invalid, re-render with errors
        context = self.get_context_data(**kwargs)
        if form_type == 'profile':
            context['profile_form'] = form
        elif form_type == 'preferences':
            context['preferences_form'] = form
        elif form_type == 'password':
            context['password_form'] = form
        
        return self.render_to_response(context)


# ---------------------------------------------------------------------------
# Notification Management
# ---------------------------------------------------------------------------
class NotificationListView(LoginRequiredMixin, ListView):
    """List of user notifications."""
    model = Notification
    template_name = 'letters/notification_list.html'
    context_object_name = 'notifications'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = Notification.objects.filter(
            recipient=self.request.user
        ).select_related('related_letter')
        
        # Filter by notification type
        notification_type = self.request.GET.get('type')
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        
        # Filter by read status
        read_status = self.request.GET.get('read')
        if read_status == 'unread':
            queryset = queryset.filter(is_read=False)
        elif read_status == 'read':
            queryset = queryset.filter(is_read=True)
        
        # Check if grouping is enabled
        self.group_by_letter = self.request.GET.get('group') == 'letter'
        
        if self.group_by_letter:
            # Group by related letter
            from django.db.models import Max
            grouped = {}
            for notification in queryset:
                letter_id = notification.related_letter.id if notification.related_letter else None
                if letter_id not in grouped:
                    grouped[letter_id] = []
                grouped[letter_id].append(notification)
            
            # Sort groups by most recent notification
            sorted_groups = sorted(
                grouped.items(),
                key=lambda x: max(n.created_at for n in x[1]),
                reverse=True
            )
            
            # Flatten back to queryset-like structure
            grouped_notifications = []
            for letter_id, notifications in sorted_groups:
                # Sort notifications within group by created_at
                notifications = sorted(notifications, key=lambda x: x.created_at, reverse=True)
                grouped_notifications.extend(notifications)
            
            # Store grouped data for template
            self.grouped_data = grouped
            return grouped_notifications
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['unread_count'] = Notification.objects.filter(
            recipient=self.request.user, is_read=False
        ).count()
        
        # Add filter context
        context['current_type'] = self.request.GET.get('type', '')
        context['current_read'] = self.request.GET.get('read', '')
        context['current_group'] = self.request.GET.get('group', '')
        context['notification_types'] = Notification.NOTIFICATION_TYPES
        context['group_by_letter'] = getattr(self, 'group_by_letter', False)
        context['grouped_data'] = getattr(self, 'grouped_data', {})
        
        return context


class NotificationDetailView(LoginRequiredMixin, DetailView):
    """View single notification and mark as read."""
    model = Notification
    template_name = 'letters/notification_detail.html'
    
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
    
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        notification = self.get_object()
        notification.mark_as_read()
        return response


class MarkAsReadView(LoginRequiredMixin, View):
    """Mark notification as read via AJAX."""
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.mark_as_read()
        return JsonResponse({'success': True})


class MarkAllAsReadView(LoginRequiredMixin, View):
    """Mark all notifications as read."""
    def post(self, request):
        Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return JsonResponse({'success': True})


class NotificationDeleteView(LoginRequiredMixin, View):
    """Delete a notification."""
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.delete()
        return JsonResponse({'success': True})


class NotificationAPIView(LoginRequiredMixin, View):
    """API endpoint for loading notifications via AJAX."""
    def get(self, request):
        notifications = Notification.objects.filter(
            recipient=request.user
        ).select_related('related_letter')[:10]
        
        notification_data = []
        for notification in notifications:
            # Calculate time ago
            from datetime import timedelta
            time_diff = timezone.now() - notification.created_at
            
            if time_diff < timedelta(minutes=1):
                time_ago = 'Just now'
            elif time_diff < timedelta(hours=1):
                time_ago = f'{int(time_diff.total_seconds() / 60)} min ago'
            elif time_diff < timedelta(days=1):
                time_ago = f'{int(time_diff.total_seconds() / 3600)} hours ago'
            else:
                time_ago = f'{time_diff.days} days ago'
            
            # Get icon based on notification type
            icon_map = {
                'letter_assigned': 'bi-envelope',
                'status_changed': 'bi-arrow-repeat',
                'action_added': 'bi-list-check',
                'attachment_added': 'bi-paperclip',
                'overdue_warning': 'bi-exclamation-triangle',
                'comment_added': 'bi-chat',
            }
            
            color_map = {
                'letter_assigned': 'primary',
                'status_changed': 'info',
                'action_added': 'success',
                'attachment_added': 'warning',
                'overdue_warning': 'danger',
                'comment_added': 'secondary',
            }
            
            notification_data.append({
                'id': notification.id,
                'title': notification.title,
                'message': notification.message,
                'is_read': notification.is_read,
                'time_ago': time_ago,
                'icon': icon_map.get(notification.notification_type, 'bi-bell'),
                'color': color_map.get(notification.notification_type, 'primary'),
                'url': notification.related_letter.get_absolute_url() if notification.related_letter else '#',
            })
        
        unread_count = Notification.objects.filter(
            recipient=request.user, is_read=False
        ).count()
        
        return JsonResponse({
            'notifications': notification_data,
            'unread_count': unread_count,
        })


class PushSubscriptionView(LoginRequiredMixin, View):
    """Subscribe to push notifications."""
    def post(self, request):
        try:
            data = json.loads(request.body)
            subscription = data.get('subscription')
            
            if not subscription:
                return JsonResponse({'success': False, 'error': 'No subscription data'}, status=400)
            
            # Validate subscription structure
            if not isinstance(subscription, dict):
                return JsonResponse({'success': False, 'error': 'Invalid subscription format'}, status=400)
            
            endpoint = subscription.get('endpoint')
            keys = subscription.get('keys', {})
            
            if not endpoint:
                return JsonResponse({'success': False, 'error': 'Missing endpoint'}, status=400)
            
            if not isinstance(keys, dict):
                return JsonResponse({'success': False, 'error': 'Invalid keys format'}, status=400)
            
            p256dh = keys.get('p256dh')
            auth = keys.get('auth')
            
            if not p256dh or not auth:
                return JsonResponse({'success': False, 'error': 'Missing p256dh or auth keys'}, status=400)
            
            # Create or update subscription
            PushSubscription.objects.update_or_create(
                user=request.user,
                endpoint=endpoint,
                defaults={
                    'p256dh': p256dh,
                    'auth': auth,
                    'is_active': True
                }
            )
            
            return JsonResponse({'success': True})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(f"Push subscription error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class PushUnsubscribeView(LoginRequiredMixin, View):
    """Unsubscribe from push notifications."""
    def post(self, request):
        try:
            data = json.loads(request.body)
            endpoint = data.get('endpoint')
            
            if endpoint:
                PushSubscription.objects.filter(
                    user=request.user,
                    endpoint=endpoint
                ).delete()
            
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class TelegramSettingsView(LoginRequiredMixin, View):
    """Save Telegram notification settings."""
    def post(self, request):
        try:
            data = json.loads(request.body)
            chat_id = data.get('chat_id', '').strip()
            enabled = data.get('enabled', False)
            
            # Get or create user profile
            profile, created = UserProfile.objects.get_or_create(user=request.user)
            
            # Update Telegram settings
            profile.telegram_chat_id = chat_id if chat_id else None
            profile.telegram_notifications = enabled and bool(chat_id)
            profile.save()
            
            return JsonResponse({'success': True})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(f"Telegram settings error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class TestTelegramView(LoginRequiredMixin, View):
    """Send a test Telegram notification."""
    def post(self, request):
        try:
            from .telegram_utils import verify_telegram_chat_id
            
            data = json.loads(request.body)
            chat_id = data.get('chat_id', '').strip()
            
            if not chat_id:
                return JsonResponse({'success': False, 'error': 'Chat ID is required'}, status=400)
            
            # Send test message
            if verify_telegram_chat_id(chat_id):
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': 'Failed to send test message. Check your chat ID and bot configuration.'}, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            print(f"Test Telegram error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class TelegramWebhookView(View):
    """Handle Telegram webhook updates."""
    
    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def post(self, request):
        try:
            # Validate webhook secret if configured
            from django.conf import settings
            secret = request.GET.get('secret')
            if settings.TELEGRAM_WEBHOOK_SECRET and settings.TELEGRAM_WEBHOOK_SECRET != 'your-secret-token-here':
                if secret != settings.TELEGRAM_WEBHOOK_SECRET:
                    logger.error(f"Invalid webhook secret: {secret}")
                    return JsonResponse({'ok': False, 'error': 'Invalid secret'}, status=403)
            
            from .telegram_utils import handle_telegram_webhook
            
            import json
            update = json.loads(request.body)
            result = handle_telegram_webhook(update)
            
            return JsonResponse(result)
        except Exception as e:
            logger.error(f"Telegram webhook error: {str(e)}")
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)
    
    def get(self, request):
        # Telegram sends a GET request to verify the webhook
        return JsonResponse({'status': 'ok'})


class GenerateTelegramCodeView(LoginRequiredMixin, View):
    """Generate a connection token for Telegram linking."""
    def post(self, request):
        try:
            from .models import TelegramLinkToken
            from django.utils import timezone
            import secrets
            
            # Delete any previous unused tokens for this user
            TelegramLinkToken.objects.filter(
                user=request.user,
                is_used=False
            ).delete()
            
            # Generate new token
            token = secrets.token_hex(8)
            expires_at = timezone.now() + timezone.timedelta(minutes=10)
            
            # Create token record
            TelegramLinkToken.objects.create(
                user=request.user,
                token=token,
                expires_at=expires_at
            )
            
            return JsonResponse({'success': True, 'token': token})
        except Exception as e:
            print(f"Generate token error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class DisconnectTelegramView(LoginRequiredMixin, View):
    """Disconnect Telegram account."""
    def post(self, request):
        try:
            # Get user profile
            profile = request.user.profile
            profile.telegram_chat_id = None
            profile.telegram_connected_at = None
            profile.telegram_notifications = False
            profile.save()
            
            return JsonResponse({'success': True})
        except Exception as e:
            print(f"Disconnect Telegram error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class SmsSettingsView(LoginRequiredMixin, View):
    """Save AfroMessage SMS notification settings."""
    def post(self, request):
        try:
            from .sms_utils import normalize_phone_number
            data = json.loads(request.body)
            phone = data.get('phone_number', '').strip()
            enabled = data.get('enabled', False)

            profile, _ = UserProfile.objects.get_or_create(user=request.user)

            if phone:
                normalized = normalize_phone_number(phone)
                if not normalized:
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid Ethiopian phone number. Please use format 09XXXXXXXX or +2519XXXXXXXX.'
                    }, status=400)
                profile.phone_number = normalized
                profile.sms_notifications = enabled
            else:
                profile.phone_number = None
                profile.sms_notifications = False

            profile.save()
            return JsonResponse({
                'success': True,
                'phone_number': profile.phone_number,
                'enabled': profile.sms_notifications
            })
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"SMS settings error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class TestSmsView(LoginRequiredMixin, View):
    """Send a test SMS via AfroMessage."""
    def post(self, request):
        try:
            from .sms_utils import send_sms_with_result, normalize_phone_number
            data = json.loads(request.body) if request.body else {}
            phone = data.get('phone_number', '').strip()

            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            target_phone = phone or profile.phone_number

            if not target_phone:
                return JsonResponse({'success': False, 'error': 'Phone number is required.'}, status=400)

            normalized = normalize_phone_number(target_phone)
            if not normalized:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid Ethiopian phone number format. Use 09XXXXXXXX, 07XXXXXXXX, or +2519XXXXXXXX.'
                }, status=400)

            user_display = request.user.get_full_name() or request.user.username
            msg = f"AE LMS: Hello {user_display}, your AfroMessage SMS notifications are configured successfully!"

            success, api_message = send_sms_with_result(normalized, msg)
            if success:
                return JsonResponse({'success': True})
            else:
                return JsonResponse({
                    'success': False,
                    'error': api_message
                }, status=400)

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Test SMS error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class DisconnectSmsView(LoginRequiredMixin, View):
    """Disconnect/disable SMS notifications."""
    def post(self, request):
        try:
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.phone_number = None
            profile.sms_notifications = False
            profile.save()
            return JsonResponse({'success': True})
        except Exception as e:
            logger.error(f"Disconnect SMS error: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class OcrExtractView(LoginRequiredMixin, View):
    """
    API view for extracting letter metadata (sender, recipient, attention, subject, date, ref no)
    from uploaded document (PDF or Image) using OCR and text parsing.
    """
    def post(self, request, *args, **kwargs):
        setting = SystemSetting.get_settings()
        if not setting.ai_ocr_enabled:
            return JsonResponse({
                'success': False,
                'error': 'OCR Auto-Fill feature is currently disabled by the system administrator.'
            }, status=403)

        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return JsonResponse({'success': False, 'error': 'No file uploaded.'}, status=400)

        # Check max file size (15MB)
        if uploaded_file.size > 15 * 1024 * 1024:
            return JsonResponse({'success': False, 'error': 'File size exceeds 15 MB limit.'}, status=400)

        try:
            from .ocr_utils import extract_text_from_file, parse_letter_fields

            direction = request.POST.get('direction', 'INCOMING').upper()
            raw_text, error_msg = extract_text_from_file(uploaded_file, uploaded_file.name)
            if error_msg and not raw_text:
                return JsonResponse({'success': False, 'error': error_msg}, status=400)

            fields = parse_letter_fields(raw_text, direction=direction)
            
            return JsonResponse({
                'success': True,
                'fields': fields,
                'raw_text_snippet': raw_text[:500] if raw_text else '',
                'warning': error_msg if error_msg else None
            })
        except Exception as e:
            logger.error(f"OCR extraction error: {str(e)}")
            return JsonResponse({'success': False, 'error': f'Failed to process document: {str(e)}'}, status=500)


# ---------------------------------------------------------------------------
# AI Assistant Views
# ---------------------------------------------------------------------------
class AIAssistantPageView(LoginRequiredMixin, TemplateView):
    """
    Dedicated full page for AE LMS AI Platform Assistant & Guide.
    """
    template_name = 'letters/ai_assistant.html'

    def get(self, request, *args, **kwargs):
        setting = SystemSetting.get_settings()
        if not setting.ai_assistant_enabled:
            is_admin = request.user.is_superuser or request.user.groups.filter(name='Admin').exists()
            if not is_admin:
                messages.warning(request, "AI Platform Assistant is currently disabled by the system administrator.")
                return redirect('letters:dashboard')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        setting = SystemSetting.get_settings()
        from .ai_assistant import AIAssistantService, FAQ_FALLBACK_DATABASE
        context['page_title'] = 'AI Platform Assistant'
        context['page_subtitle'] = 'Ask questions about AE LMS features, workflows, and tools'
        context['faq_database'] = FAQ_FALLBACK_DATABASE
        context['is_ai_enabled'] = setting.ai_assistant_enabled
        context['ai_provider'] = self.request.session.get('ai_provider', getattr(settings, 'AI_MODEL_PROVIDER', 'auto'))
        context['has_gemini_key'] = bool(getattr(settings, 'GEMINI_API_KEY', '').strip() and getattr(settings, 'GEMINI_API_KEY', '') != 'your_free_gemini_api_key_here')
        context['has_groq_key'] = bool(getattr(settings, 'GROQ_API_KEY', '').strip() and getattr(settings, 'GROQ_API_KEY', '') != 'your_free_groq_api_key_here')
        context['has_openrouter_key'] = bool(getattr(settings, 'OPENROUTER_API_KEY', '').strip())
        context['has_cohere_key'] = bool(getattr(settings, 'COHERE_API_KEY', '').strip())
        return context


class AIAssistantChatView(LoginRequiredMixin, View):
    """
    API endpoint for handling chat requests from floating widget or AI page.
    """
    def post(self, request, *args, **kwargs):
        setting = SystemSetting.get_settings()
        if not setting.ai_assistant_enabled:
            return JsonResponse({
                'success': False,
                'error': 'AI Platform Assistant is currently disabled by the system administrator.'
            }, status=403)

        try:
            data = json.loads(request.body.decode('utf-8'))
            user_prompt = data.get('prompt', '').strip()
            history = data.get('history', [])
            selected_provider = data.get('provider', '').strip().lower()

            # Store provider preference in session if specified
            if selected_provider and selected_provider in ['auto', 'gemini', 'groq', 'deepseek', 'openrouter', 'cohere']:
                request.session['ai_provider'] = selected_provider

            if not user_prompt:
                return JsonResponse({'success': False, 'error': 'Prompt cannot be empty.'}, status=400)

            from .ai_assistant import AIAssistantService
            provider_override = request.session.get('ai_provider', None)
            result = AIAssistantService.ask_ai(user_prompt, conversation_history=history, user=request.user, provider_override=provider_override)

            return JsonResponse({
                'success': True,
                'response': result['response'],
                'provider': result['provider'],
                'is_fallback': result.get('is_fallback', False),
                'notice': result.get('notice', None)
            })
        except Exception as e:
            logger.error(f"AI Assistant Chat View Error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to process request: {str(e)}'
            }, status=500)


class AIAssistantStatusView(LoginRequiredMixin, View):
    """
    Returns AI provider status information.
    """
    def get(self, request, *args, **kwargs):
        setting = SystemSetting.get_settings()
        gemini_key = getattr(settings, 'GEMINI_API_KEY', '').strip()
        groq_key = getattr(settings, 'GROQ_API_KEY', '').strip()
        openrouter_key = getattr(settings, 'OPENROUTER_API_KEY', '').strip()
        cohere_key = getattr(settings, 'COHERE_API_KEY', '').strip()
        provider = request.session.get('ai_provider', getattr(settings, 'AI_MODEL_PROVIDER', 'auto'))

        has_gemini = bool(gemini_key and gemini_key != 'your_free_gemini_api_key_here')
        has_groq = bool(groq_key and groq_key != 'your_free_groq_api_key_here')
        has_openrouter = bool(openrouter_key)
        has_cohere = bool(cohere_key)

        is_live = (has_gemini or has_groq or has_openrouter or has_cohere) and setting.ai_assistant_enabled

        if provider == 'auto':
            active_provider = "Auto (Multi-Provider Failover)"
        elif provider == 'gemini':
            active_provider = "Google Gemini"
        elif provider == 'groq':
            active_provider = "Groq Llama 3.3"
        elif provider in ['deepseek', 'openrouter']:
            active_provider = "DeepSeek / OpenRouter"
        elif provider == 'cohere':
            active_provider = "Cohere Command R+"
        else:
            active_provider = "Smart Offline FAQ"

        return JsonResponse({
            'success': True,
            'is_enabled': setting.ai_assistant_enabled,
            'provider': provider,
            'active_engine': active_provider,
            'has_gemini_key': has_gemini,
            'has_groq_key': has_groq,
            'has_openrouter_key': has_openrouter,
            'has_cohere_key': has_cohere,
            'is_live_ai_available': is_live
        })


# ---------------------------------------------------------------------------
# Calendar Conversion API
# ---------------------------------------------------------------------------
class CalendarConvertAPIView(LoginRequiredMixin, View):
    """
    JSON API for bidirectional conversion between Gregorian and Ethiopian dates.
    """
    def get(self, request):
        from .ethiopian_calendar import (
            gregorian_to_ethiopian, ethiopian_to_gregorian,
            format_ethiopian_date, parse_ethiopian_date
        )
        mode = request.GET.get('mode', 'greg_to_eth')
        val = request.GET.get('date', '').strip()

        if not val:
            return JsonResponse({'success': False, 'error': 'No date provided.'}, status=400)

        try:
            if mode == 'greg_to_eth':
                # Input: YYYY-MM-DD
                dt = datetime.strptime(val, '%Y-%m-%d').date()
                ey, em, ed = gregorian_to_ethiopian(dt)
                return JsonResponse({
                    'success': True,
                    'ethiopian_iso': f"{ey:04d}-{em:02d}-{ed:02d}",
                    'ethiopian_full': format_ethiopian_date(dt, fmt='full', amharic=False),
                    'ethiopian_amharic': format_ethiopian_date(dt, fmt='full', amharic=True),
                    'year': ey, 'month': em, 'day': ed
                })
            else:  # eth_to_greg
                dt = parse_ethiopian_date(val)
                if not dt:
                    return JsonResponse({'success': False, 'error': 'Could not parse Ethiopian date.'}, status=400)
                ey, em, ed = gregorian_to_ethiopian(dt)
                return JsonResponse({
                    'success': True,
                    'gregorian_iso': dt.strftime('%Y-%m-%d'),
                    'gregorian_formatted': dt.strftime('%d %b %Y'),
                    'ethiopian_iso': f"{ey:04d}-{em:02d}-{ed:02d}",
                    'ethiopian_full': format_ethiopian_date(dt, fmt='full', amharic=False),
                    'ethiopian_amharic': format_ethiopian_date(dt, fmt='full', amharic=True),
                    'year': dt.year, 'month': dt.month, 'day': dt.day
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)


