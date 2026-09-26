"""Views for SMS-based password reset via AfroMessage OTP."""
import logging
from django.contrib.auth.models import User
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.views import View

from letters.models import UserProfile, SMSVerificationCode
from letters.sms_utils import send_sms_with_result, normalize_phone_number

logger = logging.getLogger(__name__)


def _mask_phone(phone):
    """Mask phone number for display: +251***XXX889"""
    if not phone or len(phone) < 6:
        return '***'
    return phone[:4] + '***' + phone[-3:]


class PasswordResetRequestView(View):
    """Step 1: User enters username or phone number to receive an OTP via SMS."""
    template_name = 'registration/password_reset_request.html'

    def get(self, request):
        return render(request, self.template_name)

    def _find_user_by_phone(self, phone_input):
        """Look up a user by their phone number (stored in UserProfile)."""
        normalized = normalize_phone_number(phone_input)
        if not normalized:
            return None
        try:
            profile = UserProfile.objects.get(phone_number=normalized)
            return profile.user
        except UserProfile.DoesNotExist:
            return None

    def _is_phone_input(self, value):
        """Heuristic: treat input as phone if it starts with 0, +, or 251."""
        return (
            value.startswith('+') or
            value.startswith('0') and len(value) >= 10 or
            value.startswith('251') or
            value.replace(' ', '').replace('-', '').isdigit() and len(value) >= 9
        )

    def post(self, request):
        identifier = request.POST.get('identifier', '').strip()

        if not identifier:
            messages.error(request, 'Please enter your username or phone number.')
            return render(request, self.template_name)

        # Determine lookup method
        user = None
        if self._is_phone_input(identifier):
            user = self._find_user_by_phone(identifier)
        
        # Fallback to username lookup if phone didn't match or wasn't phone-like
        if user is None:
            try:
                user = User.objects.get(username=identifier)
            except User.DoesNotExist:
                # Also try phone lookup as a last resort
                user = self._find_user_by_phone(identifier)

        not_found_msg = (
            'No account found with a verified phone number for this credential. '
            'Please contact your administrator.'
        )

        if user is None:
            messages.error(request, not_found_msg)
            return render(request, self.template_name)

        # Check user has a phone number configured
        try:
            profile = user.profile
            phone = profile.phone_number
        except UserProfile.DoesNotExist:
            phone = None

        if not phone:
            messages.error(request, not_found_msg)
            return render(request, self.template_name)

        normalized = normalize_phone_number(phone)
        if not normalized:
            messages.error(
                request,
                'The phone number on file is invalid. Please contact your administrator.'
            )
            return render(request, self.template_name)

        # Rate limiting: prevent spam (max 3 codes in last 15 minutes)
        recent_codes = SMSVerificationCode.objects.filter(
            user=user,
            created_at__gte=timezone.now() - timezone.timedelta(minutes=15),
        ).count()
        if recent_codes >= 3:
            messages.error(
                request,
                'Too many reset attempts. Please wait 15 minutes before trying again.'
            )
            return render(request, self.template_name)

        # Generate OTP and send via SMS
        otp = SMSVerificationCode.generate_code(user, normalized)

        sms_message = (
            f'AE LMS Password Reset\n'
            f'Your verification code is: {otp.code}\n'
            f'This code expires in 5 minutes.\n'
            f'If you did not request this, please ignore.'
        )

        success, status_msg = send_sms_with_result(normalized, sms_message)

        if success:
            # Store user id and phone in session for next steps
            request.session['reset_user_id'] = user.pk
            request.session['reset_otp_id'] = otp.pk
            request.session['reset_phone_masked'] = _mask_phone(normalized)
            return redirect('accounts:password_reset_verify')
        else:
            logger.error(f'Failed to send OTP SMS to {normalized}: {status_msg}')
            messages.error(
                request,
                f'Failed to send verification SMS: {status_msg}'
            )
            return render(request, self.template_name)


class PasswordResetVerifyView(View):
    """Step 2: User enters the OTP code received via SMS."""
    template_name = 'registration/password_reset_verify.html'

    def _get_context(self, request):
        return {
            'masked_phone': request.session.get('reset_phone_masked', '***'),
        }

    def get(self, request):
        if 'reset_otp_id' not in request.session:
            messages.error(request, 'Please start the password reset process first.')
            return redirect('accounts:password_reset_request')
        return render(request, self.template_name, self._get_context(request))

    def post(self, request):
        if 'reset_otp_id' not in request.session:
            messages.error(request, 'Session expired. Please start again.')
            return redirect('accounts:password_reset_request')

        entered_code = request.POST.get('code', '').strip()

        if not entered_code:
            messages.error(request, 'Please enter the verification code.')
            return render(request, self.template_name, self._get_context(request))

        try:
            otp = SMSVerificationCode.objects.get(pk=request.session['reset_otp_id'])
        except SMSVerificationCode.DoesNotExist:
            messages.error(request, 'Invalid session. Please start the reset process again.')
            return redirect('accounts:password_reset_request')

        # Check if code is still valid
        if not otp.is_valid:
            messages.error(
                request,
                'Verification code has expired or reached maximum attempts. Please request a new code.'
            )
            # Clean session
            for key in ('reset_user_id', 'reset_otp_id', 'reset_phone_masked'):
                request.session.pop(key, None)
            return redirect('accounts:password_reset_request')

        # Verify code
        if entered_code != otp.code:
            otp.attempts += 1
            otp.save(update_fields=['attempts'])
            remaining = 5 - otp.attempts
            if remaining > 0:
                messages.error(
                    request,
                    f'Incorrect verification code. {remaining} attempt(s) remaining.'
                )
            else:
                messages.error(
                    request,
                    'Too many incorrect attempts. Please request a new code.'
                )
                for key in ('reset_user_id', 'reset_otp_id', 'reset_phone_masked'):
                    request.session.pop(key, None)
                return redirect('accounts:password_reset_request')
            return render(request, self.template_name, self._get_context(request))

        # Code is correct - mark as verified (but not fully used yet)
        request.session['reset_verified'] = True
        return redirect('accounts:password_reset_confirm')


class PasswordResetConfirmView(View):
    """Step 3: User sets a new password after OTP verification."""
    template_name = 'registration/password_reset_confirm.html'

    def get(self, request):
        if not request.session.get('reset_verified'):
            messages.error(request, 'Please verify your identity first.')
            return redirect('accounts:password_reset_request')
        return render(request, self.template_name)

    def post(self, request):
        if not request.session.get('reset_verified'):
            messages.error(request, 'Session expired. Please start again.')
            return redirect('accounts:password_reset_request')

        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        # Validate passwords
        if not password1:
            messages.error(request, 'Please enter a new password.')
            return render(request, self.template_name)

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, self.template_name)

        if len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, self.template_name)

        # Get user and update password
        user_id = request.session.get('reset_user_id')
        otp_id = request.session.get('reset_otp_id')

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, 'User not found. Please start again.')
            return redirect('accounts:password_reset_request')

        # Mark OTP as used
        try:
            otp = SMSVerificationCode.objects.get(pk=otp_id)
            otp.is_used = True
            otp.save(update_fields=['is_used'])
        except SMSVerificationCode.DoesNotExist:
            pass

        # Set new password
        user.set_password(password1)
        user.save()

        # Clean up session
        for key in ('reset_user_id', 'reset_otp_id', 'reset_phone_masked', 'reset_verified'):
            request.session.pop(key, None)

        logger.info(f'Password reset successful for user: {user.username}')

        messages.success(
            request,
            'Your password has been reset successfully! You can now sign in with your new password.'
        )
        return redirect('accounts:login')
