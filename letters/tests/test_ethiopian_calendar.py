import datetime
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from letters.models import Department, Letter, Category
from letters.forms import LetterForm, IncomingLetterForm, OutgoingLetterForm
from letters.filters import LetterFilter
from letters.ethiopian_calendar import (
    gregorian_to_ethiopian,
    ethiopian_to_gregorian,
    format_ethiopian_date,
    parse_ethiopian_date,
    is_ethiopian_leap_year,
    days_in_ethiopian_month,
    ethiopian_year_gregorian_range,
)


class EthiopianCalendarTestCase(TestCase):
    """Test suite for Ethiopian calendar conversion and integration across AE LMS."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='admin_tester',
            password='testpassword123',
            email='admin@example.com'
        )
        self.dept = Department.objects.create(name='Operations', code='OPS')
        self.category = Category.objects.create(name='Contracts', code='CON')

    # ------------------------------------------------------------------
    # 1. Mathematics & Leap Year Tests
    # ------------------------------------------------------------------
    def test_leap_year_detection(self):
        """Test Ethiopian leap years (Pagume has 6 days when year % 4 == 3)."""
        self.assertTrue(is_ethiopian_leap_year(2011))
        self.assertTrue(is_ethiopian_leap_year(2015))
        self.assertTrue(is_ethiopian_leap_year(2019))
        self.assertFalse(is_ethiopian_leap_year(2016))
        self.assertFalse(is_ethiopian_leap_year(2017))
        self.assertFalse(is_ethiopian_leap_year(2018))

        self.assertEqual(days_in_ethiopian_month(2015, 13), 6)
        self.assertEqual(days_in_ethiopian_month(2018, 13), 5)
        self.assertEqual(days_in_ethiopian_month(2018, 1), 30)

    def test_known_benchmark_dates(self):
        """Test conversion against verified historical and current benchmarks."""
        benchmarks = [
            # Gregorian (Y, M, D) -> Ethiopian (Y, M, D)
            (datetime.date(2026, 8, 21), (2018, 12, 15)),   # Today: 15 Nehase 2018
            (datetime.date(2025, 9, 11), (2018, 1, 1)),     # Enkutatash 2018
            (datetime.date(2023, 9, 12), (2016, 1, 1)),     # Enkutatash 2016 (after leap 2015)
            (datetime.date(2023, 9, 11), (2015, 13, 6)),    # Pagume 6, 2015 (leap day)
            (datetime.date(2024, 1, 1), (2016, 4, 22)),     # 22 Tahsas 2016
            (datetime.date(2020, 2, 29), (2012, 6, 21)),    # Gregorian leap day -> 21 Yakatit 2012
        ]
        for greg_d, expected_eth in benchmarks:
            converted_eth = gregorian_to_ethiopian(greg_d)
            self.assertEqual(converted_eth, expected_eth, f"Failed for {greg_d}")
            back_greg = ethiopian_to_gregorian(*expected_eth)
            self.assertEqual(back_greg, greg_d, f"Failed roundtrip for {expected_eth}")

    def test_full_roundtrip_range(self):
        """Verify 100% daily roundtrip consistency over 50 years."""
        cur = datetime.date(2000, 1, 1)
        end = datetime.date(2050, 12, 31)
        step = datetime.timedelta(days=1)
        while cur <= end:
            ey, em, ed = gregorian_to_ethiopian(cur)
            back_greg = ethiopian_to_gregorian(ey, em, ed)
            self.assertEqual(back_greg, cur)
            cur += step

    # ------------------------------------------------------------------
    # 2. Formatting & Parsing Tests
    # ------------------------------------------------------------------
    def test_date_formatting(self):
        """Test formatting in English and Amharic."""
        sample_date = datetime.date(2026, 8, 21)
        full_en = format_ethiopian_date(sample_date, fmt='full')
        self.assertIn("15 Nehase 2018 E.C.", full_en)

        full_am = format_ethiopian_date(sample_date, fmt='full', amharic=True)
        self.assertIn("ነሐሴ 15, 2018 ዓ.ም.", full_am)

        iso_str = format_ethiopian_date(sample_date, fmt='iso')
        self.assertEqual(iso_str, "2018-12-15")

        short_str = format_ethiopian_date(sample_date, fmt='short')
        self.assertEqual(short_str, "15/12/2018 E.C.")

    def test_date_parsing_various_formats(self):
        """Test flexible parsing of user Ethiopian date inputs."""
        expected_date = datetime.date(2026, 8, 21)  # 15 Nehase 2018

        self.assertEqual(parse_ethiopian_date("2018-12-15"), expected_date)
        self.assertEqual(parse_ethiopian_date("2018/12/15"), expected_date)
        self.assertEqual(parse_ethiopian_date("15/12/2018"), expected_date)
        self.assertEqual(parse_ethiopian_date("15-12-2018"), expected_date)
        self.assertEqual(parse_ethiopian_date("15 Nehase 2018"), expected_date)
        self.assertEqual(parse_ethiopian_date("15 Nehase 2018 E.C."), expected_date)
        self.assertEqual(parse_ethiopian_date("Nehase 15, 2018"), expected_date)
        self.assertEqual(parse_ethiopian_date("ነሐሴ 15, 2018 ዓ.ም."), expected_date)
        self.assertEqual(parse_ethiopian_date("ነሐሴ 15 2018"), expected_date)

    # ------------------------------------------------------------------
    # 3. Model Computed Properties
    # ------------------------------------------------------------------
    def test_letter_model_ethiopian_properties(self):
        """Test Letter model computed properties for Ethiopian dates."""
        letter = Letter.objects.create(
            direction=Letter.INCOMING,
            reference_no="TEST/ETH/001",
            date=datetime.date(2026, 8, 21),
            due_date=datetime.date(2026, 9, 1),
            subject="Test Ethiopian Calendar Integration",
            created_by=self.user,
            assigned_department=self.dept,
            category=self.category,
        )

        self.assertEqual(letter.ethiopian_date, "15 Nehase 2018 E.C.")
        self.assertEqual(letter.ethiopian_date_amharic, "ነሐሴ 15, 2018 ዓ.ም.")
        self.assertEqual(letter.ethiopian_due_date, "26 Nehase 2018 E.C.")
        self.assertEqual(letter.ethiopian_due_date_amharic, "ነሐሴ 26, 2018 ዓ.ም.")

    # ------------------------------------------------------------------
    # 4. Form Bidirectional Conversion Tests
    # ------------------------------------------------------------------
    def test_form_creation_with_ethiopian_date_input(self):
        """Test creating a letter by providing an Ethiopian date string."""
        form_data = {
            'direction': Letter.INCOMING,
            'letter_type': Letter.HARDCOPY,
            'ethiopian_date': '2018-12-15',   # Should convert to 2026-08-21
            'ethiopian_due_date': '2018-12-25', # Should convert to 2026-08-31
            'reference_no': 'IN/ETH/999',
            'sender': 'Addis Ababa City Admin',
            'attention_to': 'Legal Department',
            'subject': 'Procurement Clearance Request',
            'category': self.category.pk,
            'priority': Letter.NORMAL,
            'assigned_department': self.dept.pk,
            'assigned_person': self.user.pk,
            'status': Letter.RECEIVED,
        }

        form = IncomingLetterForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        letter = form.save(commit=False)
        letter.created_by = self.user
        letter.save()

        self.assertEqual(letter.date, datetime.date(2026, 8, 21))
        self.assertEqual(letter.due_date, datetime.date(2026, 8, 31))
        self.assertEqual(letter.ethiopian_date, "15 Nehase 2018 E.C.")

    def test_form_initial_ethiopian_values_on_edit(self):
        """Test that editing an existing letter pre-populates Ethiopian date fields."""
        letter = Letter.objects.create(
            direction=Letter.OUTGOING,
            reference_no="AE/OPS/0001/26",
            date=datetime.date(2026, 8, 21),
            due_date=datetime.date(2026, 8, 30),
            subject="Outgoing Memo",
            created_by=self.user,
            assigned_department=self.dept,
        )

        form = OutgoingLetterForm(instance=letter, user=self.user)
        self.assertEqual(form.initial['ethiopian_date'], '2018-12-15')
        self.assertEqual(form.initial['ethiopian_due_date'], '2018-12-24')

    # ------------------------------------------------------------------
    # 5. Filter & Search Tests
    # ------------------------------------------------------------------
    def test_filter_by_ethiopian_date_range(self):
        """Test LetterFilter using eth_date_from and eth_date_to."""
        l1 = Letter.objects.create(
            direction=Letter.INCOMING, reference_no="L1",
            date=datetime.date(2025, 9, 11),  # 2018-01-01 (Meskerem 1, 2018)
            subject="Letter in Meskerem 2018", created_by=self.user,
        )
        l2 = Letter.objects.create(
            direction=Letter.INCOMING, reference_no="L2",
            date=datetime.date(2026, 8, 21),  # 2018-12-15 (Nehase 15, 2018)
            subject="Letter in Nehase 2018", created_by=self.user,
        )
        l3 = Letter.objects.create(
            direction=Letter.INCOMING, reference_no="L3",
            date=datetime.date(2024, 1, 1),   # 2016-04-22 (Tahsas 22, 2016)
            subject="Letter in Tahsas 2016", created_by=self.user,
        )

        # Filter only 2018 EC letters
        f = LetterFilter(data={'eth_date_from': '2018-01-01', 'eth_date_to': '2018-13-05'}, queryset=Letter.objects.all())
        filtered = list(f.qs)
        self.assertIn(l1, filtered)
        self.assertIn(l2, filtered)
        self.assertNotIn(l3, filtered)

    def test_search_by_ethiopian_year(self):
        """Test global list view search when user searches by Ethiopian year."""
        self.client.login(username='admin_tester', password='testpassword123')
        l_2018 = Letter.objects.create(
            direction=Letter.INCOMING, reference_no="ETH/2018/1",
            date=datetime.date(2026, 8, 21),  # 2018 EC
            subject="Tax Report", created_by=self.user,
        )

        url = reverse('letters:letter_list') + '?search=2018'
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "ETH/2018/1")

    # ------------------------------------------------------------------
    # 6. JSON Conversion API Endpoint
    # ------------------------------------------------------------------
    def test_calendar_convert_api(self):
        """Test /api/calendar/convert/ endpoint."""
        self.client.login(username='admin_tester', password='testpassword123')
        
        # Test Gregorian -> Ethiopian
        url = reverse('letters:calendar_convert') + '?mode=greg_to_eth&date=2026-08-21'
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['ethiopian_iso'], '2018-12-15')
        self.assertIn('Nehase', data['ethiopian_full'])

        # Test Ethiopian -> Gregorian
        url = reverse('letters:calendar_convert') + '?mode=eth_to_greg&date=2018-12-15'
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['gregorian_iso'], '2026-08-21')
