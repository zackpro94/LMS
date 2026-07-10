from django.db import models, transaction
import os
from django.conf import settings
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import User
from .storage import R2Storage


class Category(models.Model):
    """Dynamic letter categories managed by superadmins."""
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text='Short uppercase code, e.g. LEGAL, FINANCIAL, HR',
    )

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """Company department that handles correspondence."""
    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=10,
        unique=True,
        help_text='Short abbreviation used in reference numbers, e.g. HR, FIN, LEG',
    )
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='departments',
        help_text='Staff members belonging to this department',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'


class ReferenceCounter(models.Model):
    """
    Tracks the last sequential number used per department per year.
    Uses select_for_update() to prevent race conditions.
    """
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='counters'
    )
    year = models.IntegerField()
    last_number = models.IntegerField(default=0)

    class Meta:
        unique_together = ['department', 'year']

    def __str__(self):
        return f'{self.department.code}/{self.year}: {self.last_number:04d}'


class Letter(models.Model):
    """Core model representing an incoming or outgoing letter."""

    # Direction choices
    INCOMING = 'INCOMING'
    OUTGOING = 'OUTGOING'
    DIRECTION_CHOICES = [
        (INCOMING, 'Incoming'),
        (OUTGOING, 'Outgoing'),
    ]

    # Letter type choices
    HARDCOPY = 'HARDCOPY'
    DIGITAL = 'DIGITAL'
    LETTER_TYPE_CHOICES = [
        (HARDCOPY, 'Hardcopy'),
        (DIGITAL, 'Digital'),
    ]

    # Priority choices
    NORMAL = 'NORMAL'
    URGENT = 'URGENT'
    CONFIDENTIAL = 'CONFIDENTIAL'
    PRIORITY_CHOICES = [
        (NORMAL, 'Normal'),
        (URGENT, 'Urgent'),
        (CONFIDENTIAL, 'Confidential'),
    ]

    # Status choices
    # Incoming: RECEIVED, IN_REVIEW, ACTIONED, RESPONDED, CLOSED, ARCHIVED
    # Outgoing: DRAFTED, IN_REVIEW, SUBMITTED, RESPONDED, ARCHIVED
    RECEIVED = 'RECEIVED'
    DRAFTED = 'DRAFTED'
    IN_REVIEW = 'IN_REVIEW'
    ACTIONED = 'ACTIONED'
    SUBMITTED = 'SUBMITTED'
    RESPONDED = 'RESPONDED'
    CLOSED = 'CLOSED'
    ARCHIVED = 'ARCHIVED'
    STATUS_CHOICES = [
        (RECEIVED, 'Received'),
        (DRAFTED, 'Drafted'),
        (IN_REVIEW, 'In Review'),
        (ACTIONED, 'Actioned'),
        (SUBMITTED, 'Submitted'),
        (RESPONDED, 'Responded'),
        (CLOSED, 'Closed'),
        (ARCHIVED, 'Archived'),
    ]

    reference_no = models.CharField(
        max_length=50, unique=True, blank=True,
        help_text='For incoming letters: enter manually. For outgoing letters: auto-generated as AE/{DEPT}/{SEQ}/{YY}',
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    letter_type = models.CharField(
        max_length=10,
        choices=LETTER_TYPE_CHOICES,
        default=HARDCOPY,
        help_text='Format of the letter (Hardcopy or Digital)',
    )
    date = models.DateField(help_text='Date received or sent')
    sender = models.CharField(
        max_length=200, blank=True,
        help_text='For incoming letters',
    )
    recipient = models.CharField(
        max_length=200, blank=True,
        help_text='For outgoing letters',
    )
    subject = models.CharField(max_length=300)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='letters',
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default=NORMAL,
    )
    assigned_department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, related_name='letters',
    )
    assigned_person = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_letters',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=DRAFTED,
    )
    related_letter = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='replies',
        help_text='Link to original letter (for replies)',
    )
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_letters',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('can_view_all_letters', 'Can view all letters across all departments'),
            ('can_view_outgoing_letters', 'Can view outgoing letters'),
            ('can_view_incoming_letters', 'Can view incoming letters'),
        ]

    def __str__(self):
        ref = self.reference_no or 'DRAFT'
        return f'{ref} — {self.subject[:60]}'

    def get_absolute_url(self):
        return reverse('letters:letter_detail', kwargs={'pk': self.pk})

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------
    @property
    def is_overdue(self):
        """Return True if past due_date and not archived."""
        if self.due_date and self.status != self.ARCHIVED:
            return self.due_date < timezone.now().date()
        return False

    @property
    def days_until_due(self):
        """Return days until due (negative = overdue)."""
        if self.due_date:
            return (self.due_date - timezone.now().date()).days
        return None

    # ------------------------------------------------------------------
    # Reference number generation
    # ------------------------------------------------------------------
    def generate_reference_number(self):
        """
        Generate a reference number using the ReferenceCounter table.
        Pattern: AE/{DEPT_CODE}/{0001-9999}/{YY}
        Uses select_for_update() inside a transaction for concurrency safety.
        """
        if not self.assigned_department:
            return ''

        current_year = timezone.now().year
        year_short = current_year % 100

        with transaction.atomic():
            counter, _created = ReferenceCounter.objects.select_for_update().get_or_create(
                department=self.assigned_department,
                year=current_year,
                defaults={'last_number': 0},
            )
            counter.last_number += 1
            counter.save()

            return f'AE/{self.assigned_department.code}/{counter.last_number:04d}/{year_short:02d}'

    def save(self, *args, **kwargs):
        # Set default status based on direction if not set
        if not self.pk and not self.status:
            if self.direction == self.INCOMING:
                self.status = self.RECEIVED
            elif self.direction == self.OUTGOING:
                self.status = self.DRAFTED
        
        # Auto-generate reference number only for outgoing letters on first save when department is set
        if not self.reference_no and self.direction == self.OUTGOING and self.assigned_department:
            self.reference_no = self.generate_reference_number()
        super().save(*args, **kwargs)


class Attachment(models.Model):
    """File attachment linked to a letter."""
    letter = models.ForeignKey(
        Letter, on_delete=models.CASCADE, related_name='attachments',
    )
    file = models.FileField(
        upload_to='letters/attachments/%Y/%m/',
        storage=R2Storage()
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    short_code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    custom_short_code = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text='Custom short code for sharing (optional)')
    access_count = models.IntegerField(default=0, help_text='Number of times the shared link has been accessed')
    last_accessed = models.DateTimeField(null=True, blank=True, help_text='Last time the shared link was accessed')
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Expiration date for the shared link (optional)')

    def __str__(self):
        return f'Attachment: {self.filename} → {self.letter}'

    @property
    def filename(self):
        """Return just the filename portion of the upload path."""
        import os
        return os.path.basename(self.file.name)

    def save(self, *args, **kwargs):
        # Generate short code if not exists
        if not self.short_code:
            import secrets
            self.short_code = secrets.token_urlsafe(8)[:10]
            # Ensure uniqueness
            while Attachment.objects.filter(short_code=self.short_code).exists():
                self.short_code = secrets.token_urlsafe(8)[:10]
        super().save(*args, **kwargs)
    
    def get_short_url(self):
        """Return the short URL path for sharing"""
        code = self.custom_short_code if self.custom_short_code else self.short_code
        return f'/share/{code}/'
    
    def is_expired(self):
        """Check if the shared link has expired"""
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() > self.expires_at
        return False
    
    def generate_qr_code(self):
        """Generate QR code for the short URL"""
        import qrcode
        from io import BytesIO
        import base64
        
        from django.conf import settings
        
        # Get the full URL
        full_url = f"{settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://lms.pro.et'}{self.get_short_url()}"
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(full_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"

    @property
    def file_size_display(self):
        """Return human-readable file size."""
        try:
            size = self.file.size
        except (FileNotFoundError, ValueError):
            return '—'
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'


class ActionLog(models.Model):
    """Audit trail of actions taken on a letter."""
    letter = models.ForeignKey(
        Letter, on_delete=models.CASCADE, related_name='actions',
    )
    action = models.CharField(max_length=200)
    action_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
    )
    action_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-action_date']

    def __str__(self):
        return f'{self.action} — {self.letter}'


class UserProfile(models.Model):
    """User preferences and settings."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile'
    )
    avatar = models.ImageField(
        upload_to='avatars/%Y/%m/',
        blank=True,
        null=True,
        help_text='Profile picture'
    )
    dark_mode = models.BooleanField(default=False)
    email_notifications = models.BooleanField(default=True, help_text='Receive email notifications')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f'{self.user.username} Profile'


class Notification(models.Model):
    """User notifications for letter updates and assignments."""
    
    NOTIFICATION_TYPES = [
        ('letter_assigned', 'Letter Assigned'),
        ('status_changed', 'Status Changed'),
        ('action_added', 'Action Added'),
        ('attachment_added', 'Attachment Added'),
        ('overdue_warning', 'Overdue Warning'),
        ('comment_added', 'Comment Added'),
    ]
    
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=50, choices=NOTIFICATION_TYPES, default='letter_assigned'
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    related_letter = models.ForeignKey(
        'Letter', on_delete=models.CASCADE, related_name='notifications',
        null=True, blank=True
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} - {self.recipient.username}'
    
    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class SavedSearch(models.Model):
    """User-saved search queries for quick access."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='saved_searches'
    )
    name = models.CharField(max_length=100)
    query_string = models.TextField(help_text='URL query parameters')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Saved Search'
        verbose_name_plural = 'Saved Searches'
        ordering = ['-created_at']
        unique_together = ['user', 'name']

    def __str__(self):
        return f'{self.name} ({self.user.username})'
