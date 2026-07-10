from django.urls import path
from . import views

app_name = 'letters'

urlpatterns = [
    # Dashboard (homepage)
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Letters CRUD
    path('letters/', views.LetterListView.as_view(), name='letter_list'),
    path('letters/outgoing/', views.OutgoingLetterListView.as_view(), name='outgoing_letter_list'),
    path('letters/incoming/', views.IncomingLetterListView.as_view(), name='incoming_letter_list'),
    path('letters/create/', views.LetterCreateView.as_view(), name='letter_create'),
    path('letters/create/incoming/', views.IncomingLetterCreateView.as_view(), name='incoming_letter_create'),
    path('letters/create/outgoing/', views.OutgoingLetterCreateView.as_view(), name='outgoing_letter_create'),
    path('letters/<int:pk>/', views.LetterDetailView.as_view(), name='letter_detail'),
    path('letters/<int:pk>/edit/', views.LetterUpdateView.as_view(), name='letter_edit'),
    path('letters/<int:pk>/delete/', views.LetterDeleteView.as_view(), name='letter_delete'),
    path('letters/bulk-action/', views.BulkActionView.as_view(), name='bulk_action'),
    
    # Letter search API
    path('api/letters/search/', views.LetterSearchView.as_view(), name='letter_search'),
    
    # Saved searches
    path('letters/search/save/', views.SaveSearchView.as_view(), name='save_search'),
    path('letters/search/<int:pk>/delete/', views.DeleteSearchView.as_view(), name='delete_search'),

    # Action log & attachments
    path('letters/<int:pk>/action/', views.AddActionView.as_view(), name='add_action'),
    path('letters/<int:pk>/attach/', views.AddAttachmentView.as_view(), name='add_attachment'),
    path('letters/<int:letter_pk>/attachments/<int:attachment_pk>/delete/', views.AttachmentDeleteView.as_view(), name='delete_attachment'),
    path('letters/<int:pk>/actions/export/', views.ExportActionsView.as_view(), name='export_actions'),
    
    # Short URL for file sharing
    path('share/<str:short_code>/', views.ShortUrlRedirectView.as_view(), name='short_url_redirect'),

    # Overdue
    path('letters/overdue/', views.OverdueLettersView.as_view(), name='overdue_letters'),

    # Reports
    path('reports/', views.ReportsView.as_view(), name='reports'),
    path('reports/data/', views.ReportsDataView.as_view(), name='reports_data'),

    # Admin settings panel
    path('admin-dashboard/', views.AdminDashboardView.as_view(), name='admin_dashboard'),

    # Admin department CRUD
    path('admin-dashboard/departments/', views.DepartmentListView.as_view(), name='admin_department_list'),
    path('admin-dashboard/departments/create/', views.DepartmentCreateView.as_view(), name='admin_department_create'),
    path('admin-dashboard/departments/<int:pk>/edit/', views.DepartmentUpdateView.as_view(), name='admin_department_edit'),
    path('admin-dashboard/departments/<int:pk>/delete/', views.DepartmentDeleteView.as_view(), name='admin_department_delete'),

    # Admin category CRUD
    path('admin-dashboard/categories/', views.CategoryListView.as_view(), name='admin_category_list'),
    path('admin-dashboard/categories/create/', views.CategoryCreateView.as_view(), name='admin_category_create'),
    path('admin-dashboard/categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='admin_category_edit'),
    path('admin-dashboard/categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='admin_category_delete'),

    # Admin staff CRUD
    path('admin-dashboard/staff/', views.StaffListView.as_view(), name='admin_staff_list'),
    path('admin-dashboard/staff/create/', views.StaffCreateView.as_view(), name='admin_staff_create'),
    path('admin-dashboard/staff/<int:pk>/edit/', views.StaffUpdateView.as_view(), name='admin_staff_edit'),
    path('admin-dashboard/staff/<int:pk>/delete/', views.StaffDeleteView.as_view(), name='admin_staff_delete'),

    # User profile
    path('profile/', views.UserProfileView.as_view(), name='user_profile'),

    # Notifications
    path('notifications/', views.NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:pk>/', views.NotificationDetailView.as_view(), name='notification_detail'),
    path('notifications/<int:pk>/mark-read/', views.MarkAsReadView.as_view(), name='mark_notification_read'),
    path('notifications/<int:pk>/delete/', views.NotificationDeleteView.as_view(), name='notification_delete'),
    path('notifications/mark-all-read/', views.MarkAllAsReadView.as_view(), name='mark_all_notifications_read'),
    path('api/notifications/', views.NotificationAPIView.as_view(), name='notification_api'),
    
    # Push Notifications
    path('push/subscribe/', views.PushSubscriptionView.as_view(), name='push_subscribe'),
    path('push/unsubscribe/', views.PushUnsubscribeView.as_view(), name='push_unsubscribe'),
]
