from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from letters.models import Letter, Department
from letters.forms import LetterForm
from letters.filters import LetterFilter


class LetterTypeTest(TestCase):
    """Tests for the letter format type (Hardcopy vs Digital) and associated functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass123',
        )
        self.dept = Department.objects.create(name='Human Resources', code='HR')

    def test_letter_type_default_is_digital(self):
        """A new letter should default to DIGITAL format."""
        letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='External Org',
            subject='Inbound digital check',
            assigned_department=self.dept,
            created_by=self.user,
        )
        self.assertEqual(letter.letter_type, Letter.DIGITAL)

    def test_letter_type_can_be_hardcopy(self):
        """A letter can be explicitly marked as HARDCOPY."""
        letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='External Org',
            subject='Inbound hardcopy package',
            letter_type=Letter.HARDCOPY,
            assigned_department=self.dept,
            created_by=self.user,
        )
        self.assertEqual(letter.letter_type, Letter.HARDCOPY)

    def test_letter_form_includes_letter_type(self):
        """The LetterForm should contain the letter_type field and choice values."""
        form = LetterForm()
        self.assertIn('letter_type', form.fields)
        
        choices = form.fields['letter_type'].choices
        choice_values = [val for val, label in choices]
        self.assertIn(Letter.DIGITAL, choice_values)
        self.assertIn(Letter.HARDCOPY, choice_values)

    def test_letter_filter_by_type(self):
        """LetterFilter should successfully filter letters by letter_type."""
        # Create a digital letter
        Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Org 1',
            subject='Digital letter',
            letter_type=Letter.DIGITAL,
            assigned_department=self.dept,
            created_by=self.user,
        )
        # Create a hardcopy letter
        Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Org 2',
            subject='Hardcopy letter',
            letter_type=Letter.HARDCOPY,
            assigned_department=self.dept,
            created_by=self.user,
        )

        # Filter for DIGITAL
        qs = Letter.objects.all()
        f_digital = LetterFilter(data={'letter_type': Letter.DIGITAL}, queryset=qs)
        self.assertEqual(f_digital.qs.count(), 1)
        self.assertEqual(f_digital.qs.first().subject, 'Digital letter')

        # Filter for HARDCOPY
        f_hardcopy = LetterFilter(data={'letter_type': Letter.HARDCOPY}, queryset=qs)
        self.assertEqual(f_hardcopy.qs.count(), 1)
        self.assertEqual(f_hardcopy.qs.first().subject, 'Hardcopy letter')

    def test_incoming_outgoing_list_views(self):
        """Test that the separated list views return correct subsets of letters."""
        # Create an incoming letter
        Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Org 1',
            subject='Incoming test letter',
            assigned_department=self.dept,
            created_by=self.user,
        )
        # Create an outgoing letter
        Letter.objects.create(
            direction='OUTGOING',
            date=timezone.now().date(),
            recipient='Recipient 1',
            subject='Outgoing test letter',
            assigned_department=self.dept,
            created_by=self.user,
        )

        self.client.force_login(self.user)

        # Query OutgoingLetterListView
        response_outgoing = self.client.get('/letters/outgoing/')
        self.assertEqual(response_outgoing.status_code, 200)
        self.assertEqual(len(response_outgoing.context['letters']), 1)
        self.assertEqual(response_outgoing.context['letters'][0].subject, 'Outgoing test letter')

        # Query IncomingLetterListView
        response_incoming = self.client.get('/letters/incoming/')
        self.assertEqual(response_incoming.status_code, 200)
        self.assertEqual(len(response_incoming.context['letters']), 1)
        self.assertEqual(response_incoming.context['letters'][0].subject, 'Incoming test letter')
