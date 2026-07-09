from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage
from django.core.files.storage import FileSystemStorage
import os


class R2Storage(S3Boto3Storage):
    """Custom storage backend for Cloudflare R2"""
    
    def __init__(self, *args, **kwargs):
        USE_R2_STORAGE = os.environ.get('USE_R2_STORAGE', 'False').lower() in ('true', '1', 'yes')
        
        if USE_R2_STORAGE:
            AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
            AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
            AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
            AWS_S3_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
            
            if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME, AWS_S3_ENDPOINT_URL]):
                print("WARNING: R2 storage enabled but missing required environment variables. Falling back to local storage.")
                # Fall back to FileSystemStorage
                self._use_r2 = False
            else:
                self._use_r2 = True
                super().__init__(
                    bucket_name=AWS_STORAGE_BUCKET_NAME,
                    endpoint_url=AWS_S3_ENDPOINT_URL,
                    access_key=AWS_ACCESS_KEY_ID,
                    secret_key=AWS_SECRET_ACCESS_KEY,
                    region_name='auto',
                    addressing_style='path',
                    file_overwrite=False,
                )
                print(f"R2 Storage initialized: Bucket={AWS_STORAGE_BUCKET_NAME}")
        else:
            self._use_r2 = False
    
    def _save(self, name, content):
        if not self._use_r2:
            # Fall back to local storage
            fs = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
            return fs._save(name, content)
        return super()._save(name, content)
    
    def url(self, name):
        if not self._use_r2:
            fs = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
            return fs.url(name)
        return super().url(name)
    
    def exists(self, name):
        if not self._use_r2:
            fs = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
            return fs.exists(name)
        return super().exists(name)
    
    def delete(self, name):
        if not self._use_r2:
            fs = FileSystemStorage(location=str(settings.BASE_DIR / 'media'), base_url='/media/')
            return fs.delete(name)
        return super().delete(name)
