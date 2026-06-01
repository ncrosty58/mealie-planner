import unittest
import os
from unittest.mock import patch, MagicMock
from mealie_planner.email_notifier import EmailNotifier

class TestAdminSettings(unittest.TestCase):

    @patch("builtins.open")
    @patch("os.path.exists")
    @patch("smtplib.SMTP")
    @patch("mealie_planner.unified_client.UnifiedMealieClient")
    @patch("mealie_planner.gemini_client.GeminiClient")
    def test_send_email_when_enabled(self, mock_gemini, mock_mealie, mock_smtp, mock_exists, mock_open):
        # Setup mock Mealie users
        mock_mealie_instance = mock_mealie.return_value
        mock_mealie_instance.get_users.return_value = [{"email": "test@example.com"}]
        
        # Mock os.path.exists and open to simulate emails_enabled: True
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = '{"emails_enabled": true}'
            
        notifier = EmailNotifier(mock_mealie_instance, mock_gemini)
        
        # Set up SMTP mock
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value
        
        # Call send_email
        with patch.dict(os.environ, {"SMTP_USER": "test_user", "SMTP_PASSWORD": "test_password", "SMTP_FROM_EMAIL": "from@example.com"}):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")
            
        self.assertTrue(result)
        self.assertTrue(mock_smtp_instance.sendmail.called)

    @patch("builtins.open")
    @patch("os.path.exists")
    @patch("smtplib.SMTP")
    @patch("mealie_planner.unified_client.UnifiedMealieClient")
    @patch("mealie_planner.gemini_client.GeminiClient")
    def test_send_email_when_disabled(self, mock_gemini, mock_mealie, mock_smtp, mock_exists, mock_open):
        # Setup mock Mealie users
        mock_mealie_instance = mock_mealie.return_value
        mock_mealie_instance.get_users.return_value = [{"email": "test@example.com"}]
        
        # Mock os.path.exists and open to simulate emails_enabled: False
        mock_exists.return_value = True
        mock_open.return_value.__enter__.return_value.read.return_value = '{"emails_enabled": false}'
            
        notifier = EmailNotifier(mock_mealie_instance, mock_gemini)
        
        # Set up SMTP mock
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value
        
        # Call send_email
        with patch.dict(os.environ, {"SMTP_USER": "test_user", "SMTP_PASSWORD": "test_password", "SMTP_FROM_EMAIL": "from@example.com"}):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")
            
        # Should return False and not invoke SMTP
        self.assertFalse(result)
        self.assertFalse(mock_smtp_instance.sendmail.called)
