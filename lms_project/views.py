from django.shortcuts import render
import logging

logger = logging.getLogger(__name__)


def custom_404(request, exception):
    """Custom 404 error handler."""
    logger.warning(f"404 Not Found: {request.path}")
    return render(request, '404.html', status=404)


def custom_403(request, exception):
    """Custom 403 error handler."""
    logger.warning(f"403 Forbidden: {request.path} - User: {request.user}")
    return render(request, '403.html', status=403)


def custom_500(request):
    """Custom 500 error handler."""
    logger.error(f"500 Server Error: {request.path}")
    return render(request, '500.html', status=500)
