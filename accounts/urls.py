from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path(
        'login/',
        auth_views.LoginView.as_view(template_name='registration/login.html'),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),
    # SMS-based password reset
    path(
        'password-reset/',
        views.PasswordResetRequestView.as_view(),
        name='password_reset_request',
    ),
    path(
        'password-reset/verify/',
        views.PasswordResetVerifyView.as_view(),
        name='password_reset_verify',
    ),
    path(
        'password-reset/confirm/',
        views.PasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
]
