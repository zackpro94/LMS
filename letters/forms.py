from django import forms
from django.contrib.auth.models import User, Group, Permission
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Field, Submit, Div, HTML
from .models import Letter, ActionLog, Attachment, Department, Category


class LetterForm(forms.ModelForm):
    """Form for creating and editing letters."""

    class Meta:
        model = Letter
        fields = [
            'direction', 'letter_type', 'date', 'sender', 'recipient', 'subject',
            'category', 'priority', 'assigned_department', 'assigned_person',
            'status', 'related_letter', 'due_date', 'remarks',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'remarks': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('direction', css_class='col-md-3'),
                Column('letter_type', css_class='col-md-3'),
                Column('date', css_class='col-md-3'),
                Column('priority', css_class='col-md-3'),
            ),
            Row(
                Column('sender', css_class='col-md-6'),
                Column('recipient', css_class='col-md-6'),
            ),
            'subject',
            Row(
                Column('category', css_class='col-md-4'),
                Column('assigned_department', css_class='col-md-4'),
                Column('assigned_person', css_class='col-md-4'),
            ),
            Row(
                Column('status', css_class='col-md-4'),
                Column('due_date', css_class='col-md-4'),
                Column('related_letter', css_class='col-md-4'),
            ),
            'remarks',
            Div(
                Submit('submit', 'Save Letter', css_class='btn btn-primary btn-lg me-2'),
                HTML('<a href="{% url \'letters:letter_list\' %}" class="btn btn-outline-secondary btn-lg">Cancel</a>'),
                css_class='d-flex mt-3',
            ),
        )

        # If user is not admin/superuser, restrict status choices for Front Desk
        if user and not user.is_superuser:
            is_admin = user.groups.filter(name='Admin').exists()
            if not is_admin:
                # Front Desk users cannot set CLOSED or ARCHIVED directly
                restricted = [
                    (val, label) for val, label in Letter.STATUS_CHOICES
                    if val not in ('CLOSED', 'ARCHIVED')
                ]
                self.fields['status'].choices = restricted

    def clean(self):
        cleaned_data = super().clean()
        direction = cleaned_data.get('direction')
        sender = cleaned_data.get('sender')
        recipient = cleaned_data.get('recipient')
        subject = cleaned_data.get('subject')
        due_date = cleaned_data.get('due_date')
        date = cleaned_data.get('date')

        if direction == Letter.INCOMING and not sender:
            self.add_error('sender', 'Sender is required for incoming letters. Please specify who sent this letter.')
        if direction == Letter.OUTGOING and not recipient:
            self.add_error('recipient', 'Recipient is required for outgoing letters. Please specify who will receive this letter.')
        
        if subject and len(subject.strip()) < 3:
            self.add_error('subject', 'Subject must be at least 3 characters long.')
        
        if due_date and date and due_date < date:
            self.add_error('due_date', 'Due date cannot be before the letter date.')

        return cleaned_data


class ActionLogForm(forms.ModelForm):
    """Form for adding an action to a letter's timeline."""

    new_status = forms.ChoiceField(
        choices=[('', '— Keep current status —')] + Letter.STATUS_CHOICES,
        required=False,
        label='Update Status',
    )

    class Meta:
        model = ActionLog
        fields = ['action', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Optional notes…'}),
            'action': forms.TextInput(attrs={
                'placeholder': 'e.g. Forwarded to Finance, Signed by GM, Dispatched',
            }),
        }

    def __init__(self, *args, can_close=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_close:
            restricted = [
                (val, label) for val, label in Letter.STATUS_CHOICES
                if val not in ('CLOSED', 'ARCHIVED')
            ]
            self.fields['new_status'].choices = [
                ('', '— Keep current status —'),
            ] + restricted

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            'action',
            Row(
                Column('new_status', css_class='col-md-6'),
                Column('notes', css_class='col-md-6'),
            ),
            Submit('submit', 'Log Action', css_class='btn btn-warning w-100'),
        )


class AttachmentForm(forms.ModelForm):
    """Form for uploading an attachment to a letter."""

    class Meta:
        model = Attachment
        fields = ['file']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.form_enctype = 'multipart/form-data'
        self.helper.layout = Layout(
            'file',
            Submit('submit', 'Upload', css_class='btn btn-success'),
        )

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if f:
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError('File size must be under 10 MB. Your file is {:.2f} MB.'.format(f.size / (1024 * 1024)))
            
            # Check file extension
            allowed_extensions = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.xls', '.xlsx']
            import os
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in allowed_extensions:
                raise forms.ValidationError('File type not allowed. Allowed types: PDF, DOC, DOCX, JPG, PNG, XLS, XLSX.')
        return f


class DepartmentForm(forms.ModelForm):
    """Form for creating and editing departments."""
    class Meta:
        model = Department
        fields = ['name', 'code', 'contact_person', 'email', 'phone', 'users']
        widgets = {
            'users': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('name', css_class='col-md-8'),
                Column('code', css_class='col-md-4'),
            ),
            Row(
                Column('contact_person', css_class='col-md-4'),
                Column('email', css_class='col-md-4'),
                Column('phone', css_class='col-md-4'),
            ),
            'users',
            Submit('submit', 'Save Department', css_class='btn btn-primary mt-3'),
        )


class CategoryForm(forms.ModelForm):
    """Form for creating and editing categories."""
    class Meta:
        model = Category
        fields = ['name', 'code']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Row(
                Column('name', css_class='col-md-8'),
                Column('code', css_class='col-md-4'),
            ),
            Submit('submit', 'Save Category', css_class='btn btn-primary mt-3'),
        )


class StaffForm(forms.ModelForm):
    """Form for registering and customizing staff accounts, roles, and permissions."""
    password = forms.CharField(
        widget=forms.PasswordInput(),
        required=False,
        help_text="Leave blank to keep current password (only applicable for editing existing users)",
    )
    departments = forms.ModelMultipleChoiceField(
        queryset=Department.objects.all(),
        widget=forms.CheckboxSelectMultiple(),
        required=False,
        help_text="Select departments this staff member belongs to."
    )
    role = forms.ChoiceField(
        choices=[
            ('front_desk', 'Front Desk'),
            ('dept_staff', 'Department Staff'),
            ('admin', 'Admin')
        ],
        required=True,
        widget=forms.RadioSelect(),
        help_text="Primary system role."
    )
    can_view_all_letters = forms.BooleanField(
        required=False,
        help_text="Direct permission to view all letters across departments regardless of role."
    )
    can_view_outgoing_letters = forms.BooleanField(
        required=False,
        help_text="Permission to access the Outgoing Letters page."
    )
    can_view_incoming_letters = forms.BooleanField(
        required=False,
        help_text="Permission to access the Incoming Letters page."
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active', 'is_superuser']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        
        # If editing an existing user, pre-populate values
        if self.instance and self.instance.pk:
            self.fields['departments'].initial = self.instance.departments.all()
            
            # Find their group
            groups = self.instance.groups.values_list('name', flat=True)
            if 'Admin' in groups:
                self.fields['role'].initial = 'admin'
            elif 'Front Desk' in groups:
                self.fields['role'].initial = 'front_desk'
            else:
                self.fields['role'].initial = 'dept_staff'
                
            self.fields['can_view_all_letters'].initial = self.instance.has_perm('letters.can_view_all_letters')
            self.fields['can_view_outgoing_letters'].initial = self.instance.has_perm('letters.can_view_outgoing_letters')
            self.fields['can_view_incoming_letters'].initial = self.instance.has_perm('letters.can_view_incoming_letters')
            self.fields['password'].required = False
        else:
            self.fields['password'].required = True

        self.helper.layout = Layout(
            Row(
                Column('username', css_class='col-md-6'),
                Column('password', css_class='col-md-6'),
            ),
            Row(
                Column('first_name', css_class='col-md-6'),
                Column('last_name', css_class='col-md-6'),
            ),
            Row(
                Column('email', css_class='col-md-8'),
                Column('is_active', css_class='col-md-4 pt-4'),
            ),
            Row(
                Column('role', css_class='col-md-6'),
                Column('can_view_all_letters', css_class='col-md-6 pt-4'),
            ),
            Row(
                Column('can_view_outgoing_letters', css_class='col-md-6 pt-2'),
                Column('can_view_incoming_letters', css_class='col-md-6 pt-2'),
            ),
            Row(
                Column('is_superuser', css_class='col-md-12'),
            ),
            'departments',
            Submit('submit', 'Save Staff Member', css_class='btn btn-primary mt-3'),
        )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            if len(username) < 3:
                raise forms.ValidationError('Username must be at least 3 characters long.')
            if not username.isalnum():
                raise forms.ValidationError('Username can only contain letters and numbers.')
            # Check for existing username (excluding current user)
            existing = User.objects.filter(username=username).exclude(pk=self.instance.pk if self.instance.pk else None).first()
            if existing:
                raise forms.ValidationError('This username is already taken. Please choose another.')
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            # Check for existing email (excluding current user)
            existing = User.objects.filter(email=email).exclude(pk=self.instance.pk if self.instance.pk else None).first()
            if existing:
                raise forms.ValidationError('This email is already registered. Please use another.')
        return email
    
    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            if len(password) < 6:
                raise forms.ValidationError('Password must be at least 6 characters long.')
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            try:
                user.save()
                
                # Save role groups
                user.groups.clear()
                role = self.cleaned_data.get('role')
                group_name = None
                if role == 'admin':
                    group_name = 'Admin'
                elif role == 'front_desk':
                    group_name = 'Front Desk'
                elif role == 'dept_staff':
                    group_name = 'Department Staff'
                    
                if group_name:
                    group, _ = Group.objects.get_or_create(name=group_name)
                    user.groups.add(group)
                    
                # Direct permissions for view all letters
                can_view_all = self.cleaned_data.get('can_view_all_letters')
                can_view_outgoing = self.cleaned_data.get('can_view_outgoing_letters')
                can_view_incoming = self.cleaned_data.get('can_view_incoming_letters')
                from django.contrib.contenttypes.models import ContentType
                from letters.models import Letter
                content_type = ContentType.objects.get_for_model(Letter)

                perm_map = {
                    'can_view_all_letters': can_view_all,
                    'can_view_outgoing_letters': can_view_outgoing,
                    'can_view_incoming_letters': can_view_incoming,
                }
                for codename, granted in perm_map.items():
                    perm_obj, _ = Permission.objects.get_or_create(
                        codename=codename,
                        content_type=content_type,
                    )
                    if granted:
                        user.user_permissions.add(perm_obj)
                    else:
                        user.user_permissions.remove(perm_obj)
                    
                # Save departments
                user.departments.set(self.cleaned_data.get('departments'))
            except Exception as e:
                raise forms.ValidationError(f'Error saving user: {str(e)}')
                
        return user
