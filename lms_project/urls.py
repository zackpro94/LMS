from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import HttpResponse
import requests

# Customize admin site
admin.site.site_header = 'Auction Ethiopia - LMS Admin'
admin.site.site_title = 'AE LMS Admin'
admin.site.index_title = 'Letter Management System'

# Proxy view for R2 files to avoid CORB
def r2_media_proxy(request, path):
    """Proxy R2 files through Django to avoid CORB errors"""
    if settings.USE_R2_STORAGE:
        # Construct the R2 URL
        r2_url = f"{settings.MEDIA_URL}{path}"
        try:
            response = requests.get(r2_url, stream=True)
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            
            # Create Django response with proper headers
            django_response = HttpResponse(response.content, content_type=content_type)
            django_response['Content-Disposition'] = response.headers.get('Content-Disposition', f'inline; filename="{path.split("/")[-1]}"')
            return django_response
        except Exception as e:
            # Fallback to serving locally if R2 fails
            return serve(request, path, document_root=settings.MEDIA_ROOT)
    else:
        # Serve from local filesystem
        return serve(request, path, document_root=settings.MEDIA_ROOT)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('', include('letters.urls')),
]

# Serve media files in both development and production
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production, proxy R2 files through Django to avoid CORB
    if settings.USE_R2_STORAGE:
        urlpatterns += [
            path('media/<path:path>', r2_media_proxy),
        ]
    else:
        urlpatterns += [
            path('media/<path:path>', serve, {'document_root': settings.MEDIA_ROOT}),
        ]
