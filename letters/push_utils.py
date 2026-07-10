"""Push notification utilities for web push notifications."""
import json
from django.conf import settings
from pywebpush import webpush, WebPushException
from .models import PushSubscription


def send_push_notification(user, title, body, url=None):
    """Send a push notification to a user."""
    subscriptions = PushSubscription.objects.filter(user=user, is_active=True)
    
    if not subscriptions:
        return
    
    # Prepare VAPID settings
    vapid_private_key = settings.VAPID_PRIVATE_KEY
    vapid_claims = getattr(settings, 'VAPID_CLAIMS', {'sub': 'mailto:admin@example.com'})
    
    if not vapid_private_key:
        return
    
    # Prepare notification data
    data = {
        'title': title,
        'body': body,
        'url': url or '/',
    }
    
    # Send to each subscription
    for subscription in subscriptions:
        subscription_info = {
            'endpoint': subscription.endpoint,
            'keys': {
                'p256dh': subscription.p256dh,
                'auth': subscription.auth
            }
        }
        
        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(data),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims
            )
        except WebPushException as e:
            # If subscription is invalid, deactivate it
            if e.response and e.response.status_code in [404, 410]:
                subscription.is_active = False
                subscription.save()
            else:
                print(f"Push notification failed: {e}")
        except Exception as e:
            print(f"Error sending push notification: {e}")
