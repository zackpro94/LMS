"""
ASGI config for lms_project project.
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import letters.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms_project.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            letters.routing.websocket_urlpatterns
        )
    ),
})
