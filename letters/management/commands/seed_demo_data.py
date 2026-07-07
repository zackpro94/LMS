import random
from datetime import timedelta

from django.contrib.auth.models import Group, User, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from letters.models import ActionLog, Category, Department, Letter


class Command(BaseCommand):
    help = 'Populate the database with sample departments, users, and ~30 letters for testing.'

    def handle(self, *args, **options):
        self.stdout.write('Seeding demo data…')

        # ---- Groups -------------------------------------------------------
        front_desk_group, _ = Group.objects.get_or_create(name='Front Desk')
        dept_staff_group, _ = Group.objects.get_or_create(name='Department Staff')
        admin_group, _ = Group.objects.get_or_create(name='Admin')

        # ---- Group Permissions ---------------------------------------------
        content_type = ContentType.objects.get_for_model(Letter)
        view_all_perm, _ = Permission.objects.get_or_create(
            codename='can_view_all_letters',
            content_type=content_type,
            defaults={'name': 'Can view all letters across all departments'}
        )
        front_desk_group.permissions.add(view_all_perm)
        admin_group.permissions.add(view_all_perm)

        # ---- Departments ---------------------------------------------------
        dept_data = [
            ('Human Resources', 'HR', 'Hana Tadesse', 'hr@auctionethiopia.com', '+251 11 123 0001'),
            ('Finance', 'FIN', 'Dawit Bekele', 'finance@auctionethiopia.com', '+251 11 123 0002'),
            ('Legal', 'LEG', 'Sara Mekonnen', 'legal@auctionethiopia.com', '+251 11 123 0003'),
            ('Operations', 'OPS', 'Yonas Alemu', 'ops@auctionethiopia.com', '+251 11 123 0004'),
            ('Information Technology', 'IT', 'Bereket Hailu', 'it@auctionethiopia.com', '+251 11 123 0005'),
            ('Marketing', 'MKT', 'Meron Girma', 'marketing@auctionethiopia.com', '+251 11 123 0006'),
        ]
        departments = []
        for name, code, contact, email, phone in dept_data:
            dept, _ = Department.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'contact_person': contact,
                    'email': email,
                    'phone': phone,
                },
            )
            departments.append(dept)
            self.stdout.write(f'  Department: {dept}')

        # ---- Users ---------------------------------------------------------
        # Admin user
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'first_name': 'Admin',
                'last_name': 'User',
                'email': 'admin@auctionethiopia.com',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
        admin_user.groups.add(admin_group)

        # Front desk user
        frontdesk_user, created = User.objects.get_or_create(
            username='frontdesk',
            defaults={
                'first_name': 'Tigist',
                'last_name': 'Assefa',
                'email': 'frontdesk@auctionethiopia.com',
            },
        )
        if created:
            frontdesk_user.set_password('frontdesk123')
            frontdesk_user.save()
        frontdesk_user.groups.add(front_desk_group)

        # Department staff users (one per department)
        staff_users = []
        staff_names = [
            ('hana', 'Hana', 'Tadesse'),
            ('dawit', 'Dawit', 'Bekele'),
            ('sara', 'Sara', 'Mekonnen'),
            ('yonas', 'Yonas', 'Alemu'),
            ('bereket', 'Bereket', 'Hailu'),
            ('meron', 'Meron', 'Girma'),
        ]
        for (uname, first, last), dept in zip(staff_names, departments):
            user, created = User.objects.get_or_create(
                username=uname,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': f'{uname}@auctionethiopia.com',
                },
            )
            if created:
                user.set_password(f'{uname}123')
                user.save()
            user.groups.add(dept_staff_group)
            dept.users.add(user)
            staff_users.append((user, dept))

        all_users = [admin_user, frontdesk_user] + [u for u, _ in staff_users]
        self.stdout.write(f'  Users created/verified: {len(all_users)}')

        # ---- Sample Letters ------------------------------------------------
        subjects_incoming = [
            'Request for Bid Bond Release',
            'Tax Clearance Certificate Submission',
            'Complaint Regarding Lot #4521',
            'Government Directive on Import Regulations',
            'Invoice from Ethio Telecom',
            'Legal Notice — Contract Dispute',
            'Employee Leave Request — Batch',
            'Insurance Renewal Quotation',
            'Vendor Registration Application',
            'Customer Inquiry — Auction Schedule',
            'Bank Guarantee Extension Request',
            'Ministry of Trade Compliance Notice',
            'IT Equipment Procurement Proposal',
            'Office Lease Renewal Offer',
            'Audit Report from External Auditor',
        ]
        subjects_outgoing = [
            'Bid Award Notification — Lot #4522',
            'Response to Tax Authority Query',
            'Customer Payment Confirmation',
            'Staff Memo — Office Closure Schedule',
            'Purchase Order #2026-089',
            'Legal Response — Contract Clarification',
            'Monthly Financial Report — June 2026',
            'Marketing Campaign Approval',
            'IT Security Policy Update',
            'Vendor Payment Confirmation',
            'Response to Government Inquiry',
            'Employee Promotion Letters',
            'Invitation to Tender — Office Supplies',
            'Quarterly Performance Report',
            'Insurance Claim Submission',
        ]
        senders = [
            'Ministry of Trade', 'Ethio Telecom', 'Commercial Bank of Ethiopia',
            'Addis Ababa City Administration', 'Federal Tax Authority',
            'Ethiopian Insurance Corporation', 'National Bank of Ethiopia',
            'Various Customers', 'Vendor X', 'External Audit Firm',
        ]
        recipients = [
            'Ministry of Trade', 'Ethio Telecom', 'Commercial Bank of Ethiopia',
            'Bidders — Lot #4522', 'Federal Tax Authority',
            'All Staff', 'Various Vendors', 'Board of Directors',
        ]
        # ---- Categories (dynamic) ------------------------------------------
        category_data = [
            ('LEGAL', 'Legal'),
            ('FINANCIAL', 'Financial'),
            ('CUSTOMER', 'Customer'),
            ('GOVERNMENT', 'Government'),
            ('INTERNAL', 'Internal'),
            ('HR', 'Human Resources'),
            ('VENDOR', 'Vendor'),
            ('OTHER', 'Other'),
        ]
        categories = []
        for code, name in category_data:
            cat, _ = Category.objects.get_or_create(
                code=code, defaults={'name': name}
            )
            categories.append(cat)
            self.stdout.write(f'  Category: {cat}')
        priorities = ['NORMAL', 'NORMAL', 'NORMAL', 'URGENT', 'CONFIDENTIAL']
        statuses = ['RECEIVED', 'IN_REVIEW', 'ACTIONED', 'RESPONDED', 'CLOSED']

        today = timezone.now().date()
        letters_created = 0

        for i in range(30):
            direction = 'INCOMING' if i < 15 else 'OUTGOING'
            subj = (subjects_incoming if direction == 'INCOMING' else subjects_outgoing)[i % 15]
            dept = random.choice(departments)
            staff_user = next((u for u, d in staff_users if d == dept), admin_user)
            creator = random.choice([frontdesk_user, admin_user])
            status = random.choice(statuses)
            date = today - timedelta(days=random.randint(0, 90))
            due_date = date + timedelta(days=random.randint(3, 30)) if random.random() > 0.3 else None

            # Avoid duplicate reference numbers — let the model handle it
            letter = Letter(
                direction=direction,
                date=date,
                sender=random.choice(senders) if direction == 'INCOMING' else '',
                recipient=random.choice(recipients) if direction == 'OUTGOING' else '',
                subject=subj,
                category=random.choice(categories),  # Now a Category FK
                priority=random.choice(priorities),
                assigned_department=dept,
                assigned_person=staff_user,
                status=status,
                due_date=due_date,
                remarks=f'Sample letter #{i + 1} for demo purposes.' if random.random() > 0.5 else '',
                created_by=creator,
            )
            letter.save()
            letters_created += 1

            # Add a creation action log
            ActionLog.objects.create(
                letter=letter,
                action=f'Letter created ({letter.get_direction_display()})',
                action_by=creator,
            )

            # Random additional action logs
            if status in ('IN_REVIEW', 'ACTIONED', 'RESPONDED', 'CLOSED'):
                ActionLog.objects.create(
                    letter=letter,
                    action=f'Forwarded to {dept.name}',
                    action_by=frontdesk_user,
                )
            if status in ('ACTIONED', 'RESPONDED', 'CLOSED'):
                ActionLog.objects.create(
                    letter=letter,
                    action='Reviewed and actioned',
                    action_by=staff_user,
                )
            if status == 'CLOSED':
                ActionLog.objects.create(
                    letter=letter,
                    action='Letter closed',
                    action_by=admin_user,
                )

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Seeding complete: {len(departments)} departments, '
            f'{len(all_users)} users, {letters_created} letters.'
        ))
        self.stdout.write(self.style.SUCCESS(
            '\nDemo accounts:\n'
            '  admin / admin123        (superuser, full access)\n'
            '  frontdesk / frontdesk123 (Front Desk group)\n'
            '  hana / hana123          (Department Staff — HR)\n'
            '  dawit / dawit123        (Department Staff — Finance)\n'
        ))
