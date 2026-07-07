from django.contrib import admin
from .models import Department, ReferenceCounter, Letter, Attachment, ActionLog, Category, UserProfile, SavedSearch


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')
    ordering = ('name',)



# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------
class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ('uploaded_at',)


class ActionLogInline(admin.TabularInline):
    model = ActionLog
    extra = 0
    readonly_fields = ('action_date',)


# ---------------------------------------------------------------------------
# Model admins
# ---------------------------------------------------------------------------
@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'contact_person', 'email', 'phone')
    search_fields = ('name', 'code', 'contact_person')
    ordering = ('name',)
    filter_horizontal = ('users',)


@admin.register(ReferenceCounter)
class ReferenceCounterAdmin(admin.ModelAdmin):
    list_display = ('department', 'year', 'last_number')
    list_filter = ('year', 'department')


@admin.register(Letter)
class LetterAdmin(admin.ModelAdmin):
    list_display = (
        'reference_no', 'direction', 'subject', 'category',
        'priority', 'status', 'assigned_department',
        'assigned_person', 'date', 'due_date',
    )
    list_filter = (
        'direction', 'status', 'category', 'priority',
        'assigned_department', 'date',
    )
    search_fields = (
        'reference_no', 'subject', 'sender', 'recipient', 'remarks',
    )
    readonly_fields = ('reference_no', 'created_at', 'updated_at')
    date_hierarchy = 'date'
    inlines = [AttachmentInline, ActionLogInline]
    raw_id_fields = ('assigned_person', 'created_by', 'related_letter')


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('letter', 'filename', 'uploaded_by', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('file', 'letter__reference_no')
    readonly_fields = ('uploaded_at',)


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ('letter', 'action', 'action_by', 'action_date')
    list_filter = ('action_date',)
    search_fields = ('action', 'notes', 'letter__reference_no')
    readonly_fields = ('action_date',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'dark_mode', 'created_at', 'updated_at')
    list_filter = ('dark_mode', 'created_at')
    search_fields = ('user__username', 'user__email')


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'user__username')
