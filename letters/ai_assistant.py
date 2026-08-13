import json
import logging
import requests
from django.conf import settings
from django.db.models import Q, Count
from django.utils import timezone
from django.contrib.auth.models import User
from letters.models import Letter, Notification, Department, Category, Attachment, ActionLog, UserProfile
from letters.permissions import (
    user_can_view_all_letters,
    user_can_view_letter,
    user_can_close,
)

logger = logging.getLogger(__name__)

SYSTEM_KNOWLEDGE_BASE = """
You are "AE AI", a friendly, warm, and helpful AI assistant for Auction Ethiopia — Letter Management System (AE LMS).

### Personality & Tone Guidelines:
- **Be Warm, Friendly & Human**: Talk like a helpful, approachable colleague. Use a cheerful, polite, and encouraging tone!
- **Conversational Greetings**: Start responses with friendly phrasing when appropriate (e.g., "Hi there! I'd love to help with that 😊", "Great question!", "Sure thing! Here's how it works:").
- **Clear & Simple Language**: Explain steps simply and clearly. Avoid dry, robotic jargon. Break things down into easy bullet points or numbered steps.
- **Empathetic & Supportive**: If a user is confused or looking for help with overdue items or system tasks, reassure them and guide them step-by-step.
- **Always Include Sender & Recipient Names**: Whenever listing, summarizing, or answering questions about letters, ALWAYS include the **Sender Name** (for incoming letters) or **Recipient Name** (for outgoing letters) along with the Reference Number, Subject, Department, and Status!

### Key System Knowledge & Features:

1. **System Overview**:
   - AE LMS tracks incoming and outgoing company correspondence with automatic department-based reference numbering, action logs, file attachments, and analytical dashboards.

2. **Reference Numbering Format**:
   - Format: `AE/{DEPT_CODE}/{4-DIGIT_SEQ}/{2-DIGIT_YEAR}` (Example: `AE/HR/0001/26`).
   - `AE`: Fixed company prefix (Auction Ethiopia).
   - `{DEPT_CODE}`: Department code (e.g. HR, FIN, LEG, OPS, IT, MKT).
   - Sequence resets per department at the start of each calendar year.

3. **Letter Workflows & Statuses**:
   - `RECEIVED`: Letter registered into the system.
   - `IN_REVIEW`: Assigned department or staff member reviewing letter.
   - `ACTIONED`: Action taken, response drafted or processed.
   - `RESPONDED`: Official reply dispatched.
   - `CLOSED`: Letter complete and resolved.
   - `ARCHIVED`: Archived for long-term historical records.

4. **Incoming vs Outgoing Letters**:
   - **Incoming Letters**: External correspondence received by the company. Front Desk or staff logs sender details, subject, arrival date, due date, and assigns it to a target department.
   - **Outgoing Letters**: Official letters created by Auction Ethiopia to external organizations. Registered with outbound reference numbers, recipient info, and delivery tracking.

5. **Roles & Permissions**:
   - **Front Desk**: Can register incoming/outgoing letters, assign departments, upload attachments.
   - **Department Staff**: Can view department letters, update status, add action logs, upload responses.
   - **System Admin / Superuser**: Full access to create/edit departments, manage staff accounts, view system audit logs, configure system settings.

6. **Overdue Alerts & Due Dates**:
   - Each letter can have a response due date.
   - Letters past their due date that are not CLOSED or ARCHIVED appear under the "Overdue" navigation tab with warning badges.

7. **Document Scanning & OCR**:
   - AE LMS supports automatic text extraction (OCR) from uploaded letter image/PDF attachments to enable deep content search across scanned documents.

8. **Notifications & Telegram Integration**:
   - Real-time in-app bell notifications.
   - Web Push notifications in modern browsers.
   - Telegram Bot integration (`/start`) allowing users to connect their Telegram account to receive instant letter assignment alerts.

9. **Reports & Data Export**:
   - Analytics dashboard displaying monthly letter volume, department distribution, status breakdowns.
   - Action logs exportable to CSV/PDF.

### Strict Role & Permission Directives:
- **Strict Role-Based Execution**: You act STRICTLY on behalf of the signed-in user (@username). You MUST NEVER perform any management action (registering letters, updating status, reassigning departments, closing, archiving) or disclose restricted data if the user does NOT have the required role or permission!
- **Permission Enforcement**:
  - If a user asks to register a letter, change status, assign a department, close, or archive a letter, BUT their user role lacks permission for that action, YOU MUST REFUSE politely and state that their user account does not have permission to perform that task.
  - DO NOT generate an `ACTION_EXECUTE` block if the user lacks permission for that specific action.

### Direct Action Execution Capabilities (When Authorized):
When requested by an authorized user with valid permissions, include an ACTION_EXECUTE JSON block at the bottom of your response:
```json
ACTION_EXECUTE: {
  "action": "REGISTER_LETTER" | "CHANGE_STATUS" | "ASSIGN_LETTER" | "CLOSE_LETTER" | "ARCHIVE_LETTER",
  "direction": "INCOMING" | "OUTGOING",
  "subject": "...",
  "sender": "...",
  "recipient": "...",
  "reference_no": "...",
  "department": "HR",
  "status": "ACTIONED",
  "priority": "URGENT",
  "due_date": "YYYY-MM-DD"
}
```
"""

FAQ_FALLBACK_DATABASE = [
    {
        "keywords": ["reference", "number", "format", "ae/"],
        "title": "Reference Numbering Scheme",
        "answer": """**Reference Number Format in AE LMS**:

All letters automatically receive a standard reference code:
`AE/{DEPT_CODE}/{4-DIGIT_SEQ}/{2-DIGIT_YEAR}`

- **AE**: Auction Ethiopia fixed prefix.
- **DEPT_CODE**: Department code (e.g., `HR` for Human Resources, `FIN` for Finance, `LEG` for Legal).
- **Sequence**: 4-digit sequential counter (e.g., `0001`, `0002`).
- **Year**: 2-digit current year (e.g., `26` for 2026).

*Note: Counters reset automatically for each department on January 1st.*"""
    },
    {
        "keywords": ["create", "add", "new", "incoming", "register"],
        "title": "Registering an Incoming Letter",
        "answer": """**How to Register an Incoming Letter**:

1. Click the **"+ New Incoming"** button in the top navigation bar or sidebar.
2. Fill in the letter details:
   - **Subject / Title** & **Sender Name/Organization**
   - **Date Received** & **Due Date** (optional)
   - **Assigned Department** (e.g., HR, Finance)
   - **Category** (e.g., Notice, Request, Invoice)
3. Upload scan/attachment file (PDF or image).
4. Click **Save Letter**. The system will assign the official reference number and notify department staff!"""
    },
    {
        "keywords": ["outgoing", "outbound", "send"],
        "title": "Creating an Outgoing Letter",
        "answer": """**How to Create an Outgoing Letter**:

1. Click **"+ New Outgoing"** in the top navigation bar.
2. Select your originating department.
3. Enter recipient name, organization, subject, and letter summary.
4. Attach the official signed letter copy.
5. Click **Save Letter**. Reference number `AE/{DEPT}/XXXX/YY` will be assigned instantly."""
    },
    {
        "keywords": ["overdue", "late", "deadline", "due date"],
        "title": "Overdue Letter Tracking",
        "answer": """**Overdue Letter Alert System**:

- Letters with a due date prior to today that remain open (`RECEIVED`, `IN_REVIEW`, or `ACTIONED`) are flagged as **Overdue**.
- You can view all pending overdue letters by clicking **Overdue** in the sidebar menu.
- Notifications are sent to assigned department members when a letter becomes overdue."""
    },
    {
        "keywords": ["telegram", "bot", "connect", "push", "mobile"],
        "title": "Connecting Telegram & Notifications",
        "answer": """**Setting Up Telegram Notifications**:

1. Go to your **Profile** (click your user name at the bottom of the sidebar).
2. Scroll to **Telegram Settings** and click **Generate Connection Code**.
3. Open the AE LMS Telegram Bot and send `/start <code>`.
4. Your account will instantly be linked to receive letter assignment alerts directly on mobile!"""
    },
    {
        "keywords": ["status", "workflow", "review", "closed", "archive"],
        "title": "Letter Status Transitions",
        "answer": """**Letter Status Lifecycle**:

1. **RECEIVED**: Freshly registered letter awaiting review.
2. **IN_REVIEW**: Department staff actively evaluating the document.
3. **ACTIONED**: Steps taken or response drafted.
4. **RESPONDED**: Outgoing response or resolution sent to sender.
5. **CLOSED**: Request completed.
6. **ARCHIVED**: Stored in permanent archive records."""
    },
    {
        "keywords": ["ocr", "scan", "extract", "search", "read"],
        "title": "Document Scanning & OCR Text Extraction",
        "answer": """**OCR Text Extraction Feature**:

AE LMS automatically extracts text from uploaded PDF and image attachments using OCR.
- Text from attachments is searchable via the global search bar (`/api/letters/search/`).
- When viewing a letter detail, click **Extract Text (OCR)** to view or edit extracted document contents."""
    },
    {
        "keywords": ["report", "chart", "export", "analytics", "csv", "excel"],
        "title": "Reports & Analytics",
        "answer": """**Reports & Exporting Data**:

- Click **Reports** in the sidebar navigation to view graphs showing monthly letter volume, department workload, and category distribution.
- You can filter reports by custom date ranges and export action audit trails to CSV/PDF."""
    },
    {
        "keywords": ["role", "permission", "admin", "frontdesk", "staff"],
        "title": "Roles & Access Control",
        "answer": """**AE LMS User Roles**:

- **Front Desk**: Registers incoming/outgoing mail and routes documents.
- **Department Staff**: Manages assigned letters for their department.
- **System Admin**: Manages departments, categories, staff user accounts, and system configuration."""
    }
]

class AIAssistantService:
    """
    Service wrapper for Free AI Model Integration (Google Gemini REST API / Groq API)
    with smart local FAQ fallback when offline or no API key is provided.
    """

    @staticmethod
    def get_user_context(user):
        """Build user context string for test compatibility."""
        if not user or not user.is_authenticated:
            return "Guest User"
        user_depts = ", ".join([f"{d.name} ({d.code})" for d in user.departments.all()]) if hasattr(user, 'departments') else "None"
        return f"{user.get_full_name() or user.username} (Depts: {user_depts})"

    @staticmethod
    def get_live_platform_context(user=None, user_prompt=None):
        """
        Queries active Django database models in real time scoped to the authenticated user's role & permissions.
        If the user has global view permissions (Superuser, Admin, Front Desk, or can_view_all_letters),
        full metrics are provided. Otherwise, letter data is strictly filtered to letters assigned to the user,
        created by the user, or belonging to the user's assigned departments.
        """
        try:
            today = timezone.now().date()

            # Guest User Handling
            if not user or not user.is_authenticated:
                return """
### CURRENT USER PROFILE & PERMISSIONS:
- **Active User**: Guest (Unauthenticated)
- **Role**: Guest User
- **Permissions**: NONE (Cannot view internal letters, search database, or execute actions)
- **Instruction for AI**: Warn the user that they are unauthenticated. Decline to perform database actions or reveal specific letter details until they log in.
"""

            # Determine Permission Flags
            can_view_all = user_can_view_all_letters(user)
            groups = [g.name for g in user.groups.all()]
            role_str = ", ".join(groups) if groups else ("Superuser" if user.is_superuser else "Staff")
            user_depts_list = list(user.departments.all()) if hasattr(user, 'departments') else []
            user_depts_str = ", ".join([f"{d.name} ({d.code})" for d in user_depts_list]) if user_depts_list else "None"

            can_register = user.is_superuser or user.groups.filter(name__in=['Admin', 'Front Desk', 'Department Staff']).exists() or user.has_perm('letters.add_letter') or user.is_staff
            can_manage_all = user.is_superuser or user.groups.filter(name='Admin').exists()

            # Base Letter Queryset scoped by permission
            if can_view_all:
                letters_qs = Letter.objects.all()
            else:
                letters_qs = Letter.objects.filter(
                    Q(assigned_department__in=user_depts_list) |
                    Q(assigned_person=user) |
                    Q(created_by=user)
                ).distinct()

            total_letters = letters_qs.count()
            incoming_count = letters_qs.filter(direction=Letter.INCOMING).count()
            outgoing_count = letters_qs.filter(direction=Letter.OUTGOING).count()

            total_departments = Department.objects.count()
            total_categories = Category.objects.count()
            total_attachments = Attachment.objects.count()
            total_action_logs = ActionLog.objects.count()
            total_users = User.objects.count()

            # Status breakdown
            status_counts = {}
            for st_code, st_label in Letter.STATUS_CHOICES:
                cnt = letters_qs.filter(status=st_code).count()
                if cnt > 0:
                    status_counts[st_label] = cnt

            # Priority breakdown
            priority_counts = {}
            for pr_code, pr_label in Letter.PRIORITY_CHOICES:
                cnt = letters_qs.filter(priority=pr_code).count()
                if cnt > 0:
                    priority_counts[pr_label] = cnt

            # Overdue letters (scoped)
            overdue_qs = letters_qs.filter(
                due_date__lt=today
            ).exclude(status__in=['CLOSED', 'ARCHIVED']).select_related('assigned_department', 'assigned_person')
            overdue_count = overdue_qs.count()

            overdue_samples = []
            for ltr in overdue_qs[:10]:
                dept_code = ltr.assigned_department.code if ltr.assigned_department else "N/A"
                assignee = ltr.assigned_person.username if ltr.assigned_person else "Unassigned"
                sender_recip = f"Sender: '{ltr.sender}'" if ltr.sender else (f"Recipient: '{ltr.recipient}'" if ltr.recipient else "Party: N/A")
                overdue_samples.append(
                    f"  * Ref: [{ltr.reference_no}] | Subject: '{ltr.subject}' | {sender_recip} | Dir: {ltr.direction} | Priority: {ltr.priority} | Dept: {dept_code} | Assignee: {assignee} | Due: {ltr.due_date}"
                )
            overdue_str = "\n".join(overdue_samples) if overdue_samples else "  None! All pending tasks are up-to-date 🎉"

            # Urgent / Confidential pending items (scoped)
            urgent_qs = letters_qs.filter(
                Q(priority='URGENT') | Q(priority='CONFIDENTIAL')
            ).exclude(status__in=['CLOSED', 'ARCHIVED']).select_related('assigned_department')[:5]
            urgent_samples = []
            for u in urgent_qs:
                dept_code = u.assigned_department.code if u.assigned_department else "N/A"
                sender_recip = f"Sender: '{u.sender}'" if u.sender else (f"Recipient: '{u.recipient}'" if u.recipient else "Party: N/A")
                urgent_samples.append(f"  * [{u.reference_no}] '{u.subject}' ({sender_recip}, Priority: {u.priority}, Status: {u.get_status_display()}, Dept: {dept_code})")
            urgent_str = "\n".join(urgent_samples) if urgent_samples else "  No active urgent/confidential letters."

            # Recent letters logged (scoped)
            recent_letters = letters_qs.select_related('assigned_department', 'category', 'created_by').order_by('-created_at')[:10]
            recent_samples = []
            for ltr in recent_letters:
                dept_code = ltr.assigned_department.code if ltr.assigned_department else "N/A"
                creator = ltr.created_by.username if ltr.created_by else "System"
                sender_recip = f"Sender: '{ltr.sender}'" if ltr.sender else (f"Recipient: '{ltr.recipient}'" if ltr.recipient else "Party: N/A")
                recent_samples.append(
                    f"  * Ref: [{ltr.reference_no}] | Subject: '{ltr.subject}' | {sender_recip} | Dir: {ltr.direction} | Status: {ltr.get_status_display()} | Dept: {dept_code} | Created By: {creator} | Date: {ltr.date}"
                )
            recent_str = "\n".join(recent_samples) if recent_samples else "  No accessible letters logged yet."

            # Department & Category details
            dept_details = []
            for d in Department.objects.annotate(letter_cnt=Count('letters')):
                dept_details.append(f"{d.name} ({d.code}) - {d.letter_cnt} letters")
            dept_str = "\n  * ".join(dept_details) if dept_details else "None registered"

            cat_details = []
            for c in Category.objects.annotate(letter_cnt=Count('letters')):
                cat_details.append(f"{c.name} ({c.code}) - {c.letter_cnt} letters")
            cat_str = ", ".join(cat_details) if cat_details else "General"

            # Action logs audit trail
            if can_manage_all:
                recent_actions = ActionLog.objects.select_related('letter', 'action_by').order_by('-action_date')[:5]
            else:
                recent_actions = ActionLog.objects.filter(letter__in=letters_qs).select_related('letter', 'action_by').order_by('-action_date')[:5]
            
            action_samples = []
            for act in recent_actions:
                actor = act.action_by.username if act.action_by else "System"
                ref = act.letter.reference_no if act.letter else "N/A"
                action_samples.append(f"  * [{act.action_date.strftime('%Y-%m-%d %H:%M')}] User '{actor}' -> Action: '{act.action}' on Letter {ref} (Notes: {act.notes or 'None'})")
            action_str = "\n".join(action_samples) if action_samples else "  No recent action logs."

            user_assigned_str = ""
            my_assigned = Letter.objects.filter(assigned_person=user).exclude(status__in=['CLOSED', 'ARCHIVED'])[:5]
            if my_assigned.exists():
                my_lines = []
                for m in my_assigned:
                    s_r = f"Sender: '{m.sender}'" if m.sender else (f"Recipient: '{m.recipient}'" if m.recipient else "Party: N/A")
                    my_lines.append(f"  * [{m.reference_no}] '{m.subject}' | {s_r} | Status: {m.get_status_display()} | Due: {m.due_date or 'N/A'}")
                user_assigned_str = f"\n- **Letters Assigned Directly to User @{user.username}**:\n" + "\n".join(my_lines)

            # Dynamic Deep Search Match (scoped)
            search_match_str = ""
            if user_prompt and len(user_prompt.strip()) > 1:
                q = user_prompt.strip()

                matched_letters = letters_qs.filter(
                    Q(reference_no__icontains=q) |
                    Q(subject__icontains=q) |
                    Q(sender__icontains=q) |
                    Q(recipient__icontains=q) |
                    Q(attention_to__icontains=q) |
                    Q(category__name__icontains=q) |
                    Q(assigned_department__name__icontains=q) |
                    Q(assigned_department__code__icontains=q) |
                    Q(created_by__username__icontains=q)
                ).select_related('assigned_department', 'category', 'assigned_person', 'created_by').distinct()[:5]

                match_parts = []
                if matched_letters.exists():
                    l_lines = []
                    for m in matched_letters:
                        d_name = m.assigned_department.name if m.assigned_department else "N/A"
                        assignee = m.assigned_person.username if m.assigned_person else "Unassigned"
                        s_r = f"Sender: '{m.sender}'" if m.sender else (f"Recipient: '{m.recipient}'" if m.recipient else "Party: N/A")
                        l_lines.append(
                            f"  * [Ref: {m.reference_no}] Subject: '{m.subject}' | {s_r} | Dir: {m.direction} | Status: {m.get_status_display()} | Priority: {m.priority} | Dept: {d_name} | Assignee: {assignee} | Date: {m.date}"
                        )
                    match_parts.append("  🔍 Matching Accessible Letters:\n" + "\n".join(l_lines))

                if match_parts:
                    search_match_str = f"\n\n### SEARCH RESULTS FOR '{q}':\n" + "\n\n".join(match_parts)

            return f"""
### CURRENT USER ROLE & PERMISSION PROFILE:
- **Active User**: @{user.username} ({user.get_full_name() or user.username})
- **Roles / Groups**: {role_str}
- **Assigned Departments**: {user_depts_str}
- **Permission - Can View All Letters**: {can_view_all}
- **Permission - Can Register New Letters**: {can_register}
- **Permission - Can Manage / Close All Letters**: {can_manage_all}

### ROLE-SCOPED DATABASE CONTEXT:
- **Accessible Letters Count**: {total_letters} Total ({incoming_count} Incoming, {outgoing_count} Outgoing)
- **Status Breakdown**: {status_counts}
- **Priority Breakdown**: {priority_counts}
- **Overdue Letters Count**: {overdue_count}
- **Overdue Items List**:
{overdue_str}
- **Urgent / Confidential Items**:
{urgent_str}
- **Recent Letters**:
{recent_str}
- **Action Audit Logs**:
{action_str}{user_assigned_str}{search_match_str}
"""
        except Exception as e:
            logger.error(f"Error building live platform context: {e}")
            return "Live Database Context: Error accessing database records."

    @classmethod
    def check_user_permission_for_action(cls, user, action_type, letter=None):
        """
        Role-based access control checker for AE AI Assistant actions.
        Returns (is_allowed: bool, error_message: str)
        """
        if not user or not user.is_authenticated:
            return False, "Authentication required. Guest users cannot perform letter management actions."

        # Superusers have full admin access
        if user.is_superuser:
            return True, ""

        # 1. REGISTER_LETTER permission check
        if action_type == 'REGISTER_LETTER':
            if (
                user.is_superuser or
                user.groups.filter(name__in=['Admin', 'Front Desk', 'Department Staff']).exists() or
                user.has_perm('letters.add_letter') or
                user.is_staff or
                user.groups.exists() or
                hasattr(user, 'departments')
            ):
                return True, ""
            return False, f"User @{user.username} does not have permission to register letters."

        # 2. CLOSE_LETTER or ARCHIVE_LETTER check
        if action_type in ['CLOSE_LETTER', 'ARCHIVE_LETTER']:
            if letter:
                if user_can_close(user, letter):
                    return True, ""
                return False, f"User @{user.username} does not have permission to close or archive letter [{letter.reference_no}]."

        # 3. Letter modification actions (CHANGE_STATUS, ASSIGN_LETTER)
        if letter:
            if (
                user.is_superuser or
                user.groups.filter(name='Admin').exists() or
                letter.created_by == user or
                letter.assigned_person == user or
                user.has_perm('letters.change_letter')
            ):
                return True, ""

            if letter.assigned_department and hasattr(user, 'departments'):
                if letter.assigned_department in user.departments.all():
                    return True, ""

            dept_name = letter.assigned_department.name if letter.assigned_department else "another department"
            return False, f"User @{user.username} is not assigned to {dept_name} or authorized to modify letter [{letter.reference_no}]."

        return True, ""

    @classmethod
    def execute_action_from_response(cls, response_text, user=None):
        """
        Parses ACTION_EXECUTE json blocks from AI response text, checks signed-in user permissions,
        executes ORM writes under the authenticated user's identity, records audit logs, and formats
        a clear confirmation or permission warning card.
        """
        import re
        from django.db import transaction

        if not response_text or "ACTION_EXECUTE" not in response_text:
            return response_text

        try:
            # Match ACTION_EXECUTE: { ... }
            match = re.search(r'ACTION_EXECUTE:\s*(\{[\s\S]*?\})', response_text)
            if not match:
                return response_text

            json_str = match.group(1)
            action_data = json.loads(json_str)
            action_type = action_data.get('action', '').upper()

            # Require authenticated user
            if not user or not user.is_authenticated:
                denied_html = """
<div class="alert alert-warning border-warning shadow-sm my-3 p-3 rounded-3">
  <div class="d-flex align-items-center gap-2 mb-1">
    <i class="bi bi-shield-lock-fill text-warning fs-5"></i>
    <strong class="text-dark">Authentication Required</strong>
  </div>
  <p class="mb-0 small text-secondary">You must be logged in with a valid account to execute letter management actions.</p>
</div>
"""
                clean_text = re.sub(r'```json\s*ACTION_EXECUTE:\s*\{[\s\S]*?\}\s*```', '', response_text)
                clean_text = re.sub(r'ACTION_EXECUTE:\s*\{[\s\S]*?\}', '', clean_text)
                return clean_text.strip() + "\n\n" + denied_html

            confirmation_html = ""

            with transaction.atomic():
                # -----------------------------------------------------------
                # 1. REGISTER_LETTER
                # -----------------------------------------------------------
                if action_type == 'REGISTER_LETTER':
                    allowed, perm_msg = cls.check_user_permission_for_action(user, action_type)
                    if not allowed:
                        confirmation_html = f"""<div class="alert alert-danger border-danger p-3 rounded-3 my-3"><i class="bi bi-shield-slash-fill me-2 text-danger"></i><strong>Permission Denied:</strong> {perm_msg}</div>"""
                    else:
                        direction = action_data.get('direction', 'INCOMING').upper()
                        subject = action_data.get('subject', 'Untitled Letter via AE AI')
                        sender = action_data.get('sender', '')
                        recipient = action_data.get('recipient', '')
                        dept_code = action_data.get('department', '').upper()
                        priority = action_data.get('priority', 'NORMAL').upper()
                        due_date_str = action_data.get('due_date', None)

                        dept_obj = None
                        if dept_code:
                            dept_obj = Department.objects.filter(
                                Q(code__iexact=dept_code) | Q(name__icontains=dept_code)
                            ).first()

                        due_date = None
                        if due_date_str:
                            try:
                                due_date = timezone.datetime.strptime(due_date_str, '%Y-%m-%d').date()
                            except Exception:
                                pass

                        new_letter = Letter(
                            direction=direction,
                            subject=subject,
                            sender=sender,
                            recipient=recipient,
                            priority=priority if priority in ['NORMAL', 'URGENT', 'CONFIDENTIAL'] else 'NORMAL',
                            assigned_department=dept_obj,
                            due_date=due_date,
                            date=timezone.now().date(),
                            created_by=user,  # 100% Registered by the signed in user!
                            status='RECEIVED' if direction == 'INCOMING' else 'DRAFTED'
                        )
                        
                        if direction == 'OUTGOING' and dept_obj:
                            new_letter.reference_no = new_letter.generate_reference_number()
                        elif not new_letter.reference_no and dept_obj:
                            ref_code = new_letter.generate_reference_number()
                            new_letter.reference_no = ref_code if ref_code else f"AE/{dept_obj.code}/{timezone.now().strftime('%m%d%H%M')}/26"

                        new_letter.save()

                        # Audit Log registered strictly by the signed in user
                        ActionLog.objects.create(
                            letter=new_letter,
                            action='REGISTERED',
                            action_by=user,
                            notes=f'Letter registered via AE AI Assistant by @{user.username} ({user.get_full_name() or user.username}).'
                        )

                        ref_display = new_letter.reference_no or f"#{new_letter.id}"
                        user_display = f"@{user.username} ({user.get_full_name() or 'Staff'})"
                        confirmation_html = f"""
<div class="alert alert-success border-success shadow-sm my-3 p-3 rounded-3">
  <div class="d-flex align-items-center gap-2 mb-1">
    <i class="bi bi-check-circle-fill text-success fs-5"></i>
    <strong class="text-success">Letter Registered Successfully!</strong>
  </div>
  <ul class="mb-1 small text-secondary">
    <li><strong>Reference Code:</strong> <code>{ref_display}</code></li>
    <li><strong>Subject:</strong> {new_letter.subject}</li>
    <li><strong>Direction:</strong> {new_letter.direction}</li>
    <li><strong>Department:</strong> {dept_obj.name if dept_obj else 'General'}</li>
    <li><strong>Status:</strong> {new_letter.get_status_display()}</li>
    <li><strong>Registered By User:</strong> <span class="badge bg-secondary-subtle text-body border">{user_display}</span></li>
  </ul>
  <a href="/letters/{new_letter.id}/" class="btn btn-sm btn-outline-success mt-2" target="_blank">
    <i class="bi bi-eye me-1"></i> View Letter Details #{new_letter.id}
  </a>
</div>
"""

                # -----------------------------------------------------------
                # 2. CHANGE_STATUS / CLOSE_LETTER / ARCHIVE_LETTER
                # -----------------------------------------------------------
                elif action_type in ['CHANGE_STATUS', 'CLOSE_LETTER', 'ARCHIVE_LETTER']:
                    ref_no = action_data.get('reference_no', '').strip()
                    new_status = action_data.get('status', 'ACTIONED').upper()
                    if action_type == 'CLOSE_LETTER':
                        new_status = 'CLOSED'
                    elif action_type == 'ARCHIVE_LETTER':
                        new_status = 'ARCHIVED'

                    letter_obj = Letter.objects.filter(
                        Q(reference_no__iexact=ref_no) | Q(subject__icontains=ref_no)
                    ).first()

                    if letter_obj:
                        allowed, perm_msg = cls.check_user_permission_for_action(user, action_type, letter=letter_obj)
                        if not allowed:
                            confirmation_html = f"""<div class="alert alert-danger border-danger p-3 rounded-3 my-3"><i class="bi bi-shield-slash-fill me-2 text-danger"></i><strong>Permission Denied:</strong> {perm_msg}</div>"""
                        else:
                            old_status_disp = letter_obj.get_status_display()
                            letter_obj.status = new_status
                            letter_obj.save()

                            ActionLog.objects.create(
                                letter=letter_obj,
                                action=f'STATUS_CHANGED_{new_status}',
                                action_by=user,  # 100% Attributed to signed in user
                                notes=f'Status changed from {old_status_disp} to {letter_obj.get_status_display()} via AE AI Assistant by @{user.username}.'
                            )

                            user_display = f"@{user.username}"
                            confirmation_html = f"""
<div class="alert alert-info border-info shadow-sm my-3 p-3 rounded-3">
  <div class="d-flex align-items-center gap-2 mb-1">
    <i class="bi bi-arrow-repeat text-info fs-5"></i>
    <strong class="text-info">Letter Status Updated!</strong>
  </div>
  <p class="mb-1 small">Letter <strong>[{letter_obj.reference_no}]</strong> status updated from <em>{old_status_disp}</em> to <span class="badge bg-primary">{letter_obj.get_status_display()}</span> by <span class="badge bg-secondary-subtle text-body border">{user_display}</span>.</p>
  <a href="/letters/{letter_obj.id}/" class="btn btn-sm btn-outline-info mt-1" target="_blank">
    <i class="bi bi-eye me-1"></i> Open Letter #{letter_obj.id}
  </a>
</div>
"""
                    else:
                        confirmation_html = f"""<div class="alert alert-warning py-2 px-3 my-2 small"><i class="bi bi-exclamation-triangle me-1"></i> Could not locate letter with reference '{ref_no}' in the database.</div>"""

                # -----------------------------------------------------------
                # 3. ASSIGN_LETTER
                # -----------------------------------------------------------
                elif action_type == 'ASSIGN_LETTER':
                    ref_no = action_data.get('reference_no', '').strip()
                    dept_code = action_data.get('department', '').upper()

                    letter_obj = Letter.objects.filter(
                        Q(reference_no__iexact=ref_no) | Q(subject__icontains=ref_no)
                    ).first()

                    dept_obj = Department.objects.filter(
                        Q(code__iexact=dept_code) | Q(name__icontains=dept_code)
                    ).first()

                    if letter_obj and dept_obj:
                        allowed, perm_msg = cls.check_user_permission_for_action(user, action_type, letter=letter_obj)
                        if not allowed:
                            confirmation_html = f"""<div class="alert alert-danger border-danger p-3 rounded-3 my-3"><i class="bi bi-shield-slash-fill me-2 text-danger"></i><strong>Permission Denied:</strong> {perm_msg}</div>"""
                        else:
                            letter_obj.assigned_department = dept_obj
                            letter_obj.save()

                            ActionLog.objects.create(
                                letter=letter_obj,
                                action='ASSIGNED_DEPARTMENT',
                                action_by=user,  # 100% Attributed to signed in user
                                notes=f'Reassigned to department {dept_obj.name} ({dept_obj.code}) via AE AI Assistant by @{user.username}.'
                            )

                            user_display = f"@{user.username}"
                            confirmation_html = f"""
<div class="alert alert-primary border-primary shadow-sm my-3 p-3 rounded-3">
  <div class="d-flex align-items-center gap-2 mb-1">
    <i class="bi bi-building-gear text-primary fs-5"></i>
    <strong class="text-primary">Department Reassigned!</strong>
  </div>
  <p class="mb-1 small">Letter <strong>[{letter_obj.reference_no}]</strong> assigned to <strong>{dept_obj.name} ({dept_obj.code})</strong> by <span class="badge bg-secondary-subtle text-body border">{user_display}</span>.</p>
  <a href="/letters/{letter_obj.id}/" class="btn btn-sm btn-outline-primary mt-1" target="_blank">
    <i class="bi bi-eye me-1"></i> Open Letter
  </a>
</div>
"""
                    else:
                        confirmation_html = f"""<div class="alert alert-warning py-2 px-3 my-2 small"><i class="bi bi-exclamation-triangle me-1"></i> Could not find target letter or department.</div>"""

            # Clean response text by removing the raw json block and adding the confirmation card
            clean_text = re.sub(r'```json\s*ACTION_EXECUTE:\s*\{[\s\S]*?\}\s*```', '', response_text)
            clean_text = re.sub(r'ACTION_EXECUTE:\s*\{[\s\S]*?\}', '', clean_text)
            return clean_text.strip() + "\n\n" + confirmation_html

        except Exception as e:
            logger.error(f"Error executing AI action: {e}")
            return response_text + f"\n\n<div class='alert alert-danger py-2 px-3 my-2 small'><i class='bi bi-exclamation-octagon me-1'></i> Action Execution Error: {str(e)}</div>"

    @classmethod
    def ask_ai(cls, user_prompt, conversation_history=None, user=None, provider_override=None):
        """
        Sends the user prompt to configured AI Provider (Gemini, Groq, DeepSeek/OpenRouter, Cohere),
        or performs multi-provider failover in 'auto' mode before dropping to Smart FAQ.
        Then processes any requested database actions.
        """
        provider = (provider_override or getattr(settings, 'AI_MODEL_PROVIDER', 'auto')).lower()
        gemini_key = getattr(settings, 'GEMINI_API_KEY', '').strip()
        groq_key = getattr(settings, 'GROQ_API_KEY', '').strip()
        openrouter_key = getattr(settings, 'OPENROUTER_API_KEY', '').strip()
        cohere_key = getattr(settings, 'COHERE_API_KEY', '').strip()

        live_context_str = cls.get_live_platform_context(user, user_prompt)
        full_system_prompt = f"{SYSTEM_KNOWLEDGE_BASE}\n\n{live_context_str}"

        response = None
        provider_used = "Offline Smart FAQ"
        is_fallback = True
        notice = None

        # 1. Google Gemini API
        if (provider in ['gemini', 'auto']) and gemini_key and gemini_key != 'your_free_gemini_api_key_here':
            res, success = cls._call_gemini_api(gemini_key, full_system_prompt, user_prompt, conversation_history)
            if success:
                response = res
                provider_used = "Google Gemini (Live AI)"
                is_fallback = False

        # 2. Groq AI API (Ultra Fast Llama 3.3 70B)
        if not response and (provider in ['groq', 'auto']) and groq_key and groq_key != 'your_free_groq_api_key_here':
            res, success = cls._call_groq_api(groq_key, full_system_prompt, user_prompt, conversation_history)
            if success:
                response = res
                provider_used = "Groq Llama 3.3 (Live AI)"
                is_fallback = False

        # 3. OpenRouter / DeepSeek API (DeepSeek R1 / V3)
        if not response and (provider in ['deepseek', 'openrouter', 'auto']) and openrouter_key:
            res, success = cls._call_openrouter_api(openrouter_key, full_system_prompt, user_prompt, conversation_history)
            if success:
                response = res
                provider_used = "DeepSeek / OpenRouter (Live AI)"
                is_fallback = False

        # 4. Cohere AI API (Command R+)
        if not response and (provider in ['cohere', 'auto']) and cohere_key:
            res, success = cls._call_cohere_api(cohere_key, full_system_prompt, user_prompt, conversation_history)
            if success:
                response = res
                provider_used = "Cohere Command R+ (Live AI)"
                is_fallback = False

        # 5. Fallback Smart Local FAQ Engine
        if not response:
            response = cls._get_smart_faq_response(user_prompt)
            provider_used = "AE LMS Knowledge Base (Offline Smart FAQ)"
            is_fallback = True
            notice = "For live interactive AI responses, add a free GEMINI_API_KEY from Google AI Studio (https://aistudio.google.com/) or GROQ_API_KEY to your environment."

        # Execute any requested database actions seamlessly
        final_response = cls.execute_action_from_response(response, user=user)

        return {
            "response": final_response,
            "provider": provider_used,
            "is_fallback": is_fallback,
            "notice": notice
        }

    @classmethod
    def _call_gemini_api(cls, api_key, system_prompt, user_prompt, history=None):
        """Call Google Gemini REST API with automatic multi-model failover."""
        models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.5-flash"]
        
        contents = []
        contents.append({
            "role": "user",
            "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system_prompt}"}]
        })
        contents.append({
            "role": "model",
            "parts": [{"text": "Understood! I am AE AI — a warm, friendly, and helpful assistant for Auction Ethiopia LMS. I'm ready to assist!"}]
        })

        if history and isinstance(history, list):
            for turn in history[-6:]:
                role = "user" if turn.get("role") == "user" else "model"
                text = turn.get("content", "")
                if text:
                    contents.append({"role": role, "parts": [{"text": text}]})

        contents.append({
            "role": "user",
            "parts": [{"text": user_prompt}]
        })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024,
            }
        }

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data['candidates'][0]['content']['parts'][0]['text']
                    return text, True
                else:
                    logger.warning(f"Gemini API ({model_name}) returned status {resp.status_code}")
            except Exception as e:
                logger.error(f"Gemini API request failed for {model_name}: {e}")

        return None, False

    @classmethod
    def _call_groq_api(cls, api_key, system_prompt, user_prompt, history=None):
        """Call Groq REST API (Supports Llama 3.3 70B & Mixtral)"""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        
        messages = [{"role": "system", "content": system_prompt}]
        if history and isinstance(history, list):
            for turn in history[-6:]:
                role = "user" if turn.get("role") == "user" else "assistant"
                content = turn.get("content", "")
                if content:
                    messages.append({"role": role, "content": content})
        
        messages.append({"role": "user", "content": user_prompt})

        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024
            }

            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data['choices'][0]['message']['content']
                    return text, True
            except Exception as e:
                logger.error(f"Groq API ({model}) failed: {e}")

        return None, False

    @classmethod
    def _call_openrouter_api(cls, api_key, system_prompt, user_prompt, history=None):
        """Call OpenRouter REST API (Supports DeepSeek R1 / DeepSeek V3 / Llama 3.3)"""
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://lms.pro.et",
            "X-Title": "AE LMS"
        }
        
        models_to_try = [
            "deepseek/deepseek-r1:free",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct:free"
        ]

        messages = [{"role": "system", "content": system_prompt}]
        if history and isinstance(history, list):
            for turn in history[-6:]:
                role = "user" if turn.get("role") == "user" else "assistant"
                content = turn.get("content", "")
                if content:
                    messages.append({"role": role, "content": content})
        
        messages.append({"role": "user", "content": user_prompt})

        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024
            }

            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data['choices'][0]['message']['content']
                    return text, True
            except Exception as e:
                logger.error(f"OpenRouter API ({model}) failed: {e}")

        return None, False

    @classmethod
    def _call_cohere_api(cls, api_key, system_prompt, user_prompt, history=None):
        """Call Cohere REST API (Command R+)"""
        url = "https://api.cohere.com/v1/chat"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "command-r-plus",
            "preamble": system_prompt,
            "message": user_prompt,
            "temperature": 0.3
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get('text', '')
                if text:
                    return text, True
        except Exception as e:
            logger.error(f"Cohere API failed: {e}")

        return None, False

    @classmethod
    def _get_smart_faq_response(cls, query):
        """Smart offline FAQ lookup matching user query keywords"""
        query_lower = query.lower()
        
        best_matches = []
        for faq in FAQ_FALLBACK_DATABASE:
            score = sum(1 for kw in faq["keywords"] if kw in query_lower)
            if score > 0:
                best_matches.append((score, faq))
        
        if best_matches:
            best_matches.sort(key=lambda x: x[0], reverse=True)
            top_faq = best_matches[0][1]
            return f"### {top_faq['title']}\n\n{top_faq['answer']}\n\n---\n*Need more details? Try asking about letters, overdue tracking, reference numbers, or Telegram alerts.*"

        # General helpful fallback when query doesn't match specific FAQ keywords
        return """Hello! I am **AE AI**, your platform guide for Auction Ethiopia LMS.

Here are quick actions you can perform or ask me about:

- 📩 **Register Letters**: Click `+ New Incoming` or `+ New Outgoing` in the top bar.
- 🔢 **Reference Numbers**: Standard format is `AE/{DEPT}/0001/26`.
- ⚠️ **Overdue Letters**: Check the `Overdue` section in the sidebar for pending tasks.
- 📱 **Telegram Notifications**: Connect your Telegram account in your Profile.
- 📊 **Reports**: Access analytical charts under the `Reports` menu.

*How can I help you today?*"""
