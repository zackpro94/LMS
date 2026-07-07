from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from letters.models import Department, Letter, ReferenceCounter


class ReferenceNumberGenerationTest(TestCase):
    """Tests for the AE/{DEPT}/{SEQ}/{YY} reference number system."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='testpass123',
        )
        self.hr_dept = Department.objects.create(
            name='Human Resources', code='HR',
        )
        self.fin_dept = Department.objects.create(
            name='Finance', code='FIN',
        )

    def _make_letter(self, department, **kwargs):
        """Helper to create a letter with sensible defaults."""
        defaults = {
            'direction': 'INCOMING',
            'date': timezone.now().date(),
            'sender': 'Test Sender',
            'subject': 'Test Subject',
            'assigned_department': department,
            'created_by': self.user,
        }
        defaults.update(kwargs)
        return Letter.objects.create(**defaults)

    # -------------------------------------------------------------------
    # Basic format
    # -------------------------------------------------------------------
    def test_reference_number_format(self):
        """Reference number follows AE/{DEPT}/{4-digit seq}/{2-digit year}."""
        letter = self._make_letter(self.hr_dept)
        year_short = timezone.now().year % 100
        self.assertEqual(letter.reference_no, f'AE/HR/0001/{year_short:02d}')

    def test_reference_number_sequential(self):
        """Consecutive letters in the same department get sequential numbers."""
        l1 = self._make_letter(self.hr_dept)
        l2 = self._make_letter(self.hr_dept)
        l3 = self._make_letter(self.hr_dept)

        year_short = timezone.now().year % 100
        self.assertEqual(l1.reference_no, f'AE/HR/0001/{year_short:02d}')
        self.assertEqual(l2.reference_no, f'AE/HR/0002/{year_short:02d}')
        self.assertEqual(l3.reference_no, f'AE/HR/0003/{year_short:02d}')

    # -------------------------------------------------------------------
    # Per-department independence
    # -------------------------------------------------------------------
    def test_different_departments_independent_counters(self):
        """Each department has its own sequence (HR/0001 and FIN/0001 coexist)."""
        hr_letter = self._make_letter(self.hr_dept)
        fin_letter = self._make_letter(self.fin_dept)

        year_short = timezone.now().year % 100
        self.assertEqual(hr_letter.reference_no, f'AE/HR/0001/{year_short:02d}')
        self.assertEqual(fin_letter.reference_no, f'AE/FIN/0001/{year_short:02d}')

    def test_interleaved_departments(self):
        """Interleaved creation across departments maintains correct sequences."""
        l1_hr = self._make_letter(self.hr_dept)
        l1_fin = self._make_letter(self.fin_dept)
        l2_hr = self._make_letter(self.hr_dept)
        l2_fin = self._make_letter(self.fin_dept)

        year_short = timezone.now().year % 100
        self.assertEqual(l1_hr.reference_no, f'AE/HR/0001/{year_short:02d}')
        self.assertEqual(l2_hr.reference_no, f'AE/HR/0002/{year_short:02d}')
        self.assertEqual(l1_fin.reference_no, f'AE/FIN/0001/{year_short:02d}')
        self.assertEqual(l2_fin.reference_no, f'AE/FIN/0002/{year_short:02d}')

    # -------------------------------------------------------------------
    # Year reset
    # -------------------------------------------------------------------
    def test_year_resets_counter(self):
        """Counter resets when the year changes."""
        # Create a letter in the "current" year
        l1 = self._make_letter(self.hr_dept)
        year_short = timezone.now().year % 100
        self.assertEqual(l1.reference_no, f'AE/HR/0001/{year_short:02d}')

        # Simulate next year by mocking timezone.now
        next_year = timezone.now().year + 1
        next_year_short = next_year % 100
        mock_dt = timezone.now().replace(year=next_year)

        with patch('letters.models.timezone.now', return_value=mock_dt):
            l2 = self._make_letter(self.hr_dept)
            self.assertEqual(l2.reference_no, f'AE/HR/0001/{next_year_short:02d}')

    # -------------------------------------------------------------------
    # No department → no reference number
    # -------------------------------------------------------------------
    def test_no_department_no_reference(self):
        """Letters without assigned_department get no reference number."""
        letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Test',
            subject='Draft Letter',
            assigned_department=None,
            created_by=self.user,
        )
        self.assertEqual(letter.reference_no, '')

    # -------------------------------------------------------------------
    # Reference assigned on department assignment
    # -------------------------------------------------------------------
    def test_reference_assigned_when_department_set_later(self):
        """Reference number is assigned when department is set on an existing letter."""
        letter = Letter.objects.create(
            direction='INCOMING',
            date=timezone.now().date(),
            sender='Test',
            subject='Draft Letter',
            assigned_department=None,
            created_by=self.user,
        )
        self.assertEqual(letter.reference_no, '')

        # Now assign department and save
        letter.assigned_department = self.hr_dept
        letter.save()
        letter.refresh_from_db()

        year_short = timezone.now().year % 100
        self.assertEqual(letter.reference_no, f'AE/HR/0001/{year_short:02d}')

    # -------------------------------------------------------------------
    # Reference not overwritten on re-save
    # -------------------------------------------------------------------
    def test_reference_not_overwritten_on_resave(self):
        """Re-saving a letter does not change its existing reference number."""
        letter = self._make_letter(self.hr_dept)
        original_ref = letter.reference_no

        letter.subject = 'Updated subject'
        letter.save()
        letter.refresh_from_db()

        self.assertEqual(letter.reference_no, original_ref)

    # -------------------------------------------------------------------
    # Both directions use same counter
    # -------------------------------------------------------------------
    def test_incoming_and_outgoing_share_counter(self):
        """Incoming and outgoing letters share the same department counter."""
        l_in = self._make_letter(self.hr_dept, direction='INCOMING', sender='X')
        l_out = self._make_letter(
            self.hr_dept, direction='OUTGOING', sender='', recipient='Y',
        )

        year_short = timezone.now().year % 100
        self.assertEqual(l_in.reference_no, f'AE/HR/0001/{year_short:02d}')
        self.assertEqual(l_out.reference_no, f'AE/HR/0002/{year_short:02d}')

    # -------------------------------------------------------------------
    # Counter model consistency
    # -------------------------------------------------------------------
    def test_counter_model_tracks_correctly(self):
        """ReferenceCounter.last_number matches the number of letters created."""
        for _ in range(5):
            self._make_letter(self.hr_dept)

        counter = ReferenceCounter.objects.get(
            department=self.hr_dept,
            year=timezone.now().year,
        )
        self.assertEqual(counter.last_number, 5)
