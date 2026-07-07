"""
Email notification utilities for the LMS.
"""
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags


def send_notification_email(subject, template_name, context, recipient_email):
    """
    Send a notification email using a template.
    """
    html_message = render_to_string(f'emails/{template_name}.html', context)
    plain_message = strip_tags(html_message)
    
    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient_email],
        html_message=html_message,
        fail_silently=False
    )


def send_overdue_notification(letter):
    """
    Send notification when a letter becomes overdue.
    """
    if not letter.assigned_person or not letter.assigned_person.email:
        return
    
    context = {
        'letter': letter,
        'assigned_person': letter.assigned_person,
        'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000',
    }
    
    send_notification_email(
        subject=f'Overdue Letter Alert: {letter.reference_no}',
        template_name='overdue_notification',
        context=context,
        recipient_email=letter.assigned_person.email
    )


def send_status_change_notification(letter, old_status, new_status):
    """
    Send notification when letter status changes.
    """
    recipients = []
    
    # Notify assigned person
    if letter.assigned_person and letter.assigned_person.email:
        recipients.append(letter.assigned_person.email)
    
    # Notify department members
    if letter.assigned_department:
        for user in letter.assigned_department.users.all():
            if user.email and user.email not in recipients:
                recipients.append(user.email)
    
    # Notify creator
    if letter.created_by and letter.created_by.email and letter.created_by.email not in recipients:
        recipients.append(letter.created_by.email)
    
    if not recipients:
        return
    
    context = {
        'letter': letter,
        'old_status': old_status,
        'new_status': new_status,
        'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000',
    }
    
    for recipient in recipients:
        send_notification_email(
            subject=f'Status Update: {letter.reference_no}',
            template_name='status_change_notification',
            context=context,
            recipient_email=recipient
        )


def send_assignment_notification(letter):
    """
    Send notification when a letter is assigned to a person.
    """
    if not letter.assigned_person or not letter.assigned_person.email:
        return
    
    context = {
        'letter': letter,
        'assigned_person': letter.assigned_person,
        'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000',
    }
    
    send_notification_email(
        subject=f'New Letter Assignment: {letter.reference_no}',
        template_name='assignment_notification',
        context=context,
        recipient_email=letter.assigned_person.email
    )


def send_new_action_notification(letter, action, action_by):
    """
    Send notification when a new action is logged on a letter.
    """
    recipients = []
    
    # Notify assigned person if they're not the one who took the action
    if letter.assigned_person and letter.assigned_person.email and letter.assigned_person != action_by:
        recipients.append(letter.assigned_person.email)
    
    # Notify creator if they're not the one who took the action
    if letter.created_by and letter.created_by.email and letter.created_by != action_by:
        recipients.append(letter.created_by.email)
    
    if not recipients:
        return
    
    context = {
        'letter': letter,
        'action': action,
        'action_by': action_by,
        'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000',
    }
    
    for recipient in recipients:
        send_notification_email(
            subject=f'New Action Logged: {letter.reference_no}',
            template_name='action_notification',
            context=context,
            recipient_email=recipient
        )
