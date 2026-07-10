"""
ASGI config for lms_project project.
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lms_project.settings')

django_asgi_app = get_asgi_application()

class LazyWebSocketApp:
    """Lazy load WebSocket routing to avoid Django app loading issues."""
    def __init__(self):
        self._app = None
    
    async def __call__(self, scope, receive, send):
        if self._app is None:
            import letters.routing
            self._app = AuthMiddlewareStack(
                URLRouter(letters.routing.websocket_urlpatterns)
            )
        await self._app(scope, receive, send)

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": LazyWebSocketApp(),
})
