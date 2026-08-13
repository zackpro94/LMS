"""
Auto-backup management command.

Dumps the PostgreSQL database and uploads the compressed backup to Cloudflare R2.
Supports one-shot and daemon (scheduled) modes.

Usage:
    python manage.py auto_backup                    # One-shot backup
    python manage.py auto_backup --daemon           # Run every 6 hours
    python manage.py auto_backup --daemon --interval 12  # Run every 12 hours
    python manage.py auto_backup --list             # List existing backups
    python manage.py auto_backup --restore latest   # Restore the latest backup
    python manage.py auto_backup --restore <filename>  # Restore a specific backup
    python manage.py auto_backup --cleanup          # Remove old backups (keep last 30)
"""

import gzip
import io
import os
import subprocess
import sys
import time
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger('letters')

# R2 backup prefix (folder inside the bucket)
BACKUP_PREFIX = 'backups/db/'


def get_r2_client():
    """Create and return a boto3 S3 client configured for Cloudflare R2."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise CommandError(
            'boto3 is required for R2 backups. Install it with: pip install boto3'
        )

    access_key = os.environ.get('R2_ACCESS_KEY_ID')
    secret_key = os.environ.get('R2_SECRET_ACCESS_KEY')
    endpoint = os.environ.get('R2_ENDPOINT_URL')
    bucket = os.environ.get('R2_BUCKET_NAME')

    if not all([access_key, secret_key, endpoint, bucket]):
        raise CommandError(
            'Missing R2 environment variables. Required:\n'
            '  R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_BUCKET_NAME'
        )

    if endpoint and not endpoint.startswith(('http://', 'https://')):
        endpoint = f'https://{endpoint}'

    client = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='auto',
        config=Config(signature_version='s3v4'),
    )
    return client, bucket


def get_db_config():
    """Extract database connection parameters from Django settings."""
    db = settings.DATABASES.get('default', {})
    engine = db.get('ENGINE', '')

    if 'postgresql' not in engine:
        raise CommandError(
            f'Auto-backup only supports PostgreSQL natively for pg_dump. Current engine: {engine}'
        )

    return {
        'host': db.get('HOST', 'localhost'),
        'port': str(db.get('PORT', '5432')),
        'name': db.get('NAME', ''),
        'user': db.get('USER', ''),
        'password': db.get('PASSWORD', ''),
    }


def create_django_dumpdata_backup():
    """
    Fallback backup method using Django's built-in dumpdata command.
    Generates a gzipped JSON export of the database and uploads to R2.
    """
    from django.core.management import call_command

    client, bucket = get_r2_client()

    timestamp = timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'lms_backup_{timestamp}.json.gz'
    r2_key = f'{BACKUP_PREFIX}{filename}'

    logger.info('Starting Django dumpdata JSON backup: %s', filename)

    out = io.StringIO()
    call_command('dumpdata', exclude=['contenttypes', 'auth.Permission', 'sessions.Session'], stdout=out)

    json_bytes = out.getvalue().encode('utf-8')
    compressed = gzip.compress(json_bytes, compresslevel=9)
    compressed_size = len(compressed)

    try:
        client.put_object(
            Bucket=bucket,
            Key=r2_key,
            Body=compressed,
            ContentType='application/gzip',
            Metadata={
                'backup-type': 'django-dumpdata',
                'created-at': timezone.now().isoformat(),
                'uncompressed-size': str(len(json_bytes)),
            },
        )
    except Exception as exc:
        raise CommandError(f'Failed to upload JSON backup to R2: {exc}')

    logger.info('Django dumpdata backup uploaded to R2: %s (%s)', r2_key, _human_size(compressed_size))
    return filename, compressed_size


def create_backup():
    """
    Run pg_dump, gzip the output, and upload to R2.
    If pg_dump is missing or fails, falls back to Django's dumpdata.
    Returns (filename, size_bytes) on success.
    """
    try:
        db = get_db_config()
    except CommandError:
        logger.info('Non-PostgreSQL engine detected. Falling back to Django dumpdata JSON backup...')
        return create_django_dumpdata_backup()

    client, bucket = get_r2_client()

    timestamp = timezone.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'lms_backup_{timestamp}.sql.gz'
    r2_key = f'{BACKUP_PREFIX}{filename}'

    logger.info('Starting database backup: %s', filename)

    # Build pg_dump command
    env = os.environ.copy()
    env['PGPASSWORD'] = db['password']

    cmd = [
        'pg_dump',
        '-h', db['host'],
        '-p', db['port'],
        '-U', db['user'],
        '-d', db['name'],
        '--no-owner',          # Don't dump ownership commands
        '--no-privileges',     # Skip access privilege commands
        '--clean',             # Include DROP statements before CREATE
        '--if-exists',         # Use IF EXISTS with DROP
        '--format=plain',      # Plain SQL for maximum compatibility
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            env=env,
            timeout=300,  # 5 minute timeout
        )
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            logger.warning('pg_dump returned non-zero code (%d): %s. Falling back to Django dumpdata...', result.returncode, stderr)
            return create_django_dumpdata_backup()

        sql_bytes = result.stdout
        compressed = gzip.compress(sql_bytes, compresslevel=9)
        compressed_size = len(compressed)

        client.put_object(
            Bucket=bucket,
            Key=r2_key,
            Body=compressed,
            ContentType='application/gzip',
            Metadata={
                'backup-type': 'postgresql',
                'database': db['name'],
                'created-at': timezone.now().isoformat(),
                'uncompressed-size': str(len(sql_bytes)),
            },
        )

        logger.info('Backup uploaded to R2: %s (%s)', r2_key, _human_size(compressed_size))
        return filename, compressed_size

    except (FileNotFoundError, PermissionError):
        logger.warning('pg_dump command not available in environment. Falling back to Django dumpdata JSON backup...')
        return create_django_dumpdata_backup()
    except subprocess.TimeoutExpired:
        logger.warning('pg_dump timed out after 5 minutes. Falling back to Django dumpdata JSON backup...')
        return create_django_dumpdata_backup()


def list_backups():
    """List all backups stored in R2. Returns a list of dicts."""
    client, bucket = get_r2_client()

    try:
        response = client.list_objects_v2(
            Bucket=bucket,
            Prefix=BACKUP_PREFIX,
        )
    except Exception as exc:
        raise CommandError(f'Failed to list backups from R2: {exc}')

    backups = []
    for obj in response.get('Contents', []):
        key = obj['Key']
        if key.endswith('.sql.gz') or key.endswith('.json.gz'):
            backups.append({
                'key': key,
                'filename': key.replace(BACKUP_PREFIX, ''),
                'size': obj['Size'],
                'last_modified': obj['LastModified'],
            })

    # Sort by date descending (newest first)
    backups.sort(key=lambda b: b['last_modified'], reverse=True)
    return backups


def cleanup_old_backups(keep=30):
    """Remove old backups, keeping only the most recent `keep` entries."""
    backups = list_backups()

    if len(backups) <= keep:
        logger.info('No cleanup needed. %d backups found (limit: %d).', len(backups), keep)
        return 0

    to_delete = backups[keep:]
    client, bucket = get_r2_client()

    deleted = 0
    for backup in to_delete:
        try:
            client.delete_object(Bucket=bucket, Key=backup['key'])
            logger.info('Deleted old backup: %s', backup['filename'])
            deleted += 1
        except Exception as exc:
            logger.warning('Failed to delete %s: %s', backup['filename'], exc)

    return deleted


def restore_backup(filename):
    """Download a backup from R2 and restore it to the database."""
    client, bucket = get_r2_client()

    # Resolve "latest"
    if filename == 'latest':
        backups = list_backups()
        if not backups:
            raise CommandError('No backups found in R2.')
        filename = backups[0]['filename']

    r2_key = f'{BACKUP_PREFIX}{filename}'

    logger.info('Downloading backup: %s', filename)

    try:
        response = client.get_object(Bucket=bucket, Key=r2_key)
        compressed = response['Body'].read()
    except client.exceptions.NoSuchKey:
        raise CommandError(f'Backup not found: {filename}')
    except Exception as exc:
        raise CommandError(f'Failed to download backup: {exc}')

    # Handle JSON backup restoration
    if filename.endswith('.json.gz'):
        from django.core.management import call_command
        import tempfile

        logger.info('Restoring JSON dumpdata backup: %s', filename)
        json_str = gzip.decompress(compressed).decode('utf-8')
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(json_str)
            tmp_path = tmp.name

        try:
            call_command('loaddata', tmp_path)
            logger.info('Database restored from JSON dump: %s', filename)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        return filename

    # Handle SQL backup restoration
    db = get_db_config()
    sql_bytes = gzip.decompress(compressed)
    logger.info('Backup decompressed: %s', _human_size(len(sql_bytes)))

    # Restore via psql
    env = os.environ.copy()
    env['PGPASSWORD'] = db['password']

    cmd = [
        'psql',
        '-h', db['host'],
        '-p', db['port'],
        '-U', db['user'],
        '-d', db['name'],
        '--single-transaction',
    ]

    try:
        result = subprocess.run(
            cmd,
            input=sql_bytes,
            capture_output=True,
            env=env,
            timeout=600,  # 10 minute timeout
        )
    except FileNotFoundError:
        raise CommandError('psql not found. Make sure PostgreSQL client tools are installed.')
    except subprocess.TimeoutExpired:
        raise CommandError('psql restore timed out after 10 minutes.')

    if result.returncode != 0:
        stderr = result.stderr.decode('utf-8', errors='replace')
        logger.warning('psql warnings:\n%s', stderr)

    logger.info('Database restored from: %s', filename)
    return filename


def _human_size(size_bytes):
    """Convert bytes to human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'


class Command(BaseCommand):
    help = 'Automated database backup to Cloudflare R2'

    def add_arguments(self, parser):
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run continuously with scheduled backups',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=6,
            help='Hours between backups in daemon mode (default: 6)',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all existing backups in R2',
        )
        parser.add_argument(
            '--restore',
            type=str,
            metavar='FILENAME',
            help='Restore a backup (use "latest" for most recent)',
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Remove old backups (keeps last --keep)',
        )
        parser.add_argument(
            '--keep',
            type=int,
            default=30,
            help='Number of backups to keep during cleanup (default: 30)',
        )

    def handle(self, *args, **options):
        if options['list']:
            return self._handle_list()

        if options['restore']:
            return self._handle_restore(options['restore'])

        if options['cleanup']:
            return self._handle_cleanup(options['keep'])

        if options['daemon']:
            return self._handle_daemon(options['interval'], options['keep'])

        # One-shot backup
        return self._handle_backup(options['keep'])

    def _handle_backup(self, keep=30):
        """Run a single backup and cleanup."""
        self.stdout.write(self.style.NOTICE('🔄 Starting database backup...'))

        try:
            filename, size = create_backup()
            self.stdout.write(self.style.SUCCESS(
                f'✅ Backup complete: {filename} ({_human_size(size)})'
            ))

            # Auto-cleanup
            deleted = cleanup_old_backups(keep=keep)
            if deleted:
                self.stdout.write(self.style.WARNING(
                    f'🧹 Cleaned up {deleted} old backup(s)'
                ))

        except CommandError:
            raise
        except Exception as exc:
            logger.exception('Backup failed')
            raise CommandError(f'Backup failed: {exc}')

    def _handle_list(self):
        """List all backups in R2."""
        backups = list_backups()

        if not backups:
            self.stdout.write(self.style.WARNING('No backups found in R2.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n📦 Found {len(backups)} backup(s):\n'))
        self.stdout.write(f'  {"#":<4} {"Filename":<45} {"Size":<12} {"Date":<22}')
        self.stdout.write(f'  {"─"*4} {"─"*45} {"─"*12} {"─"*22}')

        for i, backup in enumerate(backups, 1):
            self.stdout.write(
                f'  {i:<4} {backup["filename"]:<45} '
                f'{_human_size(backup["size"]):<12} '
                f'{backup["last_modified"].strftime("%Y-%m-%d %H:%M:%S"):<22}'
            )

        self.stdout.write('')

    def _handle_restore(self, filename):
        """Restore a backup from R2."""
        self.stdout.write(self.style.WARNING(
            f'\n⚠️  WARNING: This will overwrite the current database!'
        ))
        self.stdout.write(self.style.WARNING(
            f'   Restoring: {filename}'
        ))

        # Confirm in interactive mode
        if sys.stdin.isatty():
            confirm = input('\n   Type "yes" to confirm: ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.NOTICE('Restore cancelled.'))
                return

        self.stdout.write(self.style.NOTICE('🔄 Restoring database...'))

        try:
            restored = restore_backup(filename)
            self.stdout.write(self.style.SUCCESS(
                f'✅ Database restored from: {restored}'
            ))
        except CommandError:
            raise
        except Exception as exc:
            logger.exception('Restore failed')
            raise CommandError(f'Restore failed: {exc}')

    def _handle_cleanup(self, keep=30):
        """Manual cleanup of old backups."""
        deleted = cleanup_old_backups(keep=keep)
        if deleted:
            self.stdout.write(self.style.SUCCESS(
                f'🧹 Cleaned up {deleted} old backup(s) (keeping {keep})'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'✅ No cleanup needed (keeping {keep})'
            ))

    def _handle_daemon(self, interval_hours, keep):
        """Run backups on a schedule."""
        self.stdout.write(self.style.SUCCESS(
            f'\n🕐 Backup daemon started — running every {interval_hours} hour(s)\n'
            f'   Keeping last {keep} backups\n'
            f'   Press Ctrl+C to stop\n'
        ))

        interval_seconds = interval_hours * 3600

        while True:
            try:
                self._handle_backup(keep=keep)
                next_run = timezone.now() + timedelta(hours=interval_hours)
                self.stdout.write(self.style.NOTICE(
                    f'⏳ Next backup at: {next_run.strftime("%Y-%m-%d %H:%M:%S %Z")}'
                ))
            except CommandError as exc:
                self.stderr.write(self.style.ERROR(f'❌ Backup failed: {exc}'))
                self.stdout.write(self.style.NOTICE('   Will retry at next interval.'))
            except Exception as exc:
                logger.exception('Unexpected error in backup daemon')
                self.stderr.write(self.style.ERROR(f'❌ Unexpected error: {exc}'))

            try:
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                self.stdout.write(self.style.SUCCESS('\n👋 Backup daemon stopped.'))
                break
