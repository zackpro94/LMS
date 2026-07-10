from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage
from django.core.files.storage import FileSystemStorage
import os


class R2Storage:
    """Custom storage backend for Cloudflare R2 with local fallback"""
    
    def __init__(self, *args, **kwargs):
        USE_R2_STORAGE = os.environ.get('USE_R2_STORAGE', 'False').lower() in ('true', '1', 'yes')
        
        if USE_R2_STORAGE:
            AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
            AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
            AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
            AWS_S3_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
            
            if all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL]):
                # Use R2 storage
                self._storage = S3Boto3Storage(
                    bucket_name=AWS_STORAGE_BUCKET_NAME,
                    endpoint_url=AWS_S3_ENDPOINT_URL,
                    access_key=AWS_ACCESS_KEY_ID,
                    secret_key=AWS_SECRET_ACCESS_KEY,
                    region_name='auto',
                    addressing_style='path',
                    file_overwrite=False,
                )
                self._use_r2 = True
                print(f"R2 Storage initialized: Bucket={AWS_STORAGE_BUCKET_NAME}")
            else:
                # Fall back to local storage
                self._storage = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
                self._use_r2 = False
                print("WARNING: R2 storage enabled but missing required environment variables. Falling back to local storage.")
        else:
            # Use local storage
            self._storage = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
            self._use_r2 = False
    
    @property
    def location(self):
        """Return the storage location for compatibility."""
        return self._storage.location if hasattr(self._storage, 'location') else ''
    
    def size(self, name):
        """Return the storage size for compatibility."""
        if hasattr(self._storage, 'size'):
            return self._storage.size(name)
        return 0
    
    def generate_filename(self, filename):
        """Generate filename for Django FileField compatibility."""
        if hasattr(self._storage, 'generate_filename'):
            return self._storage.generate_filename(filename)
        return filename
    
    def save(self, name, content, max_length=None):
        """Save file for Django FileField compatibility."""
        if hasattr(self._storage, 'save'):
            return self._storage.save(name, content, max_length=max_length)
        return self._save(name, content)
    
    def get_available_name(self, name, max_length=None):
        """Get available name for Django FileField compatibility."""
        if hasattr(self._storage, 'get_available_name'):
            return self._storage.get_available_name(name, max_length=max_length)
        return name
    
    def _save(self, name, content):
        return self._storage._save(name, content)
    
    def url(self, name):
        return self._storage.url(name)
    
    def exists(self, name):
        return self._storage.exists(name)
    
    def delete(self, name):
        return self._storage.delete(name)
    
    def path(self, name):
        if hasattr(self._storage, 'path'):
            return self._storage.path(name)
        return name
