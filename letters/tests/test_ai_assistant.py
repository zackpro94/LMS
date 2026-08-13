import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from letters.models import Department, UserProfile
from letters.ai_assistant import AIAssistantService, FAQ_FALLBACK_DATABASE

class AIAssistantTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='teststaff',
            password='testpassword123',
            first_name='Abebe',
            last_name='Bikila'
        )
        self.dept = Department.objects.create(name='Human Resources', code='HR')
        self.dept.users.add(self.user)
        self.profile = UserProfile.objects.create(user=self.user)

    def test_user_context_generation(self):
        """Test that user context includes username, role, and department."""
        context_str = AIAssistantService.get_user_context(self.user)
        self.assertIn('Abebe Bikila', context_str)
        self.assertIn('Human Resources (HR)', context_str)



    def test_smart_faq_fallback(self):
        """Test keyword-based Smart FAQ matching when offline."""
        result = AIAssistantService.ask_ai("How do reference numbers work?", user=self.user, provider_override='offline')
        self.assertTrue(result['is_fallback'])
        self.assertIn("Reference Number Format in AE LMS", result['response'])
        self.assertIn("AE/{DEPT_CODE}/{4-DIGIT_SEQ}/{2-DIGIT_YEAR}", result['response'])

    def test_ai_status_view(self):
        """Test the AI status API endpoint."""
        self.client.login(username='teststaff', password='testpassword123')
        url = reverse('letters:ai_assistant_status')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('active_engine', data)

    def test_ai_chat_view(self):
        """Test sending a prompt to the AI chat endpoint."""
        self.client.login(username='teststaff', password='testpassword123')
        url = reverse('letters:ai_assistant_chat')
        payload = {
            'prompt': 'How do I log an incoming letter?',
            'history': []
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('response', data)
        self.assertTrue(len(data['response']) > 20)

    def test_ai_page_view(self):
        """Test loading the full AI Assistant template page."""
        self.client.login(username='teststaff', password='testpassword123')
        url = reverse('letters:ai_assistant_page')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'letters/ai_assistant.html')
        self.assertIn('faq_database', response.context)

    def test_ai_action_execution(self):
        """Test that AI action execution creates letters and updates status in DB."""
        ai_response_with_action = """
I can help with that!

ACTION_EXECUTE: {
  "action": "REGISTER_LETTER",
  "direction": "INCOMING",
  "subject": "Tax Audit Clearance Request",
  "sender": "Ministry of Revenue",
  "department": "HR",
  "priority": "URGENT"
}
"""
        result_html = AIAssistantService.execute_action_from_response(ai_response_with_action, user=self.user)
        self.assertIn("Letter Registered Successfully!", result_html)
        self.assertIn("Tax Audit Clearance Request", result_html)

        from letters.models import Letter
        letter = Letter.objects.filter(subject="Tax Audit Clearance Request").first()
        self.assertIsNotNone(letter)
        self.assertEqual(letter.direction, "INCOMING")
        self.assertEqual(letter.priority, "URGENT")
        self.assertEqual(letter.assigned_department.code, "HR")
