import os
import unittest
from unittest.mock import MagicMock, patch

from mealie_planner.email_notifier import EmailNotifier

SMTP_ENV = {"SMTP_USER": "test_user", "SMTP_PASSWORD": "test_password", "SMTP_FROM_EMAIL": "from@example.com"}


class TestAdminSettings(unittest.TestCase):

    def _make_notifier(self):
        mock_mealie = MagicMock()
        mock_mealie.get_users.return_value = [
            {"email": "test@example.com"},
            {"email": "muted@example.com"},
        ]
        return EmailNotifier(mock_mealie, MagicMock())

    @patch("smtplib.SMTP")
    @patch("mealie_planner.database.load_state_from_db")
    def test_send_email_when_enabled(self, mock_state, mock_smtp):
        mock_state.return_value = {"emails_enabled": True}
        notifier = self._make_notifier()
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value

        with patch.dict(os.environ, SMTP_ENV):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")

        self.assertTrue(result)
        self.assertTrue(mock_smtp_instance.sendmail.called)

    @patch("smtplib.SMTP")
    @patch("mealie_planner.database.load_state_from_db")
    def test_send_email_when_disabled(self, mock_state, mock_smtp):
        mock_state.return_value = {"emails_enabled": False}
        notifier = self._make_notifier()
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value

        with patch.dict(os.environ, SMTP_ENV):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")

        self.assertFalse(result)
        self.assertFalse(mock_smtp_instance.sendmail.called)

    @patch("smtplib.SMTP")
    @patch("mealie_planner.database.load_state_from_db")
    def test_disabled_recipients_are_filtered(self, mock_state, mock_smtp):
        mock_state.return_value = {
            "emails_enabled": True,
            "disabled_recipient_emails": ["muted@example.com"],
        }
        notifier = self._make_notifier()
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value

        with patch.dict(os.environ, SMTP_ENV):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")

        self.assertTrue(result)
        sent_recipients = mock_smtp_instance.sendmail.call_args[0][1]
        self.assertEqual(sent_recipients, ["test@example.com"])

    @patch("smtplib.SMTP")
    @patch("mealie_planner.database.load_state_from_db")
    def test_all_recipients_disabled_sends_nothing(self, mock_state, mock_smtp):
        mock_state.return_value = {
            "emails_enabled": True,
            "disabled_recipient_emails": ["test@example.com", "muted@example.com"],
        }
        notifier = self._make_notifier()
        mock_smtp_instance = mock_smtp.return_value.__enter__.return_value

        with patch.dict(os.environ, SMTP_ENV):
            result = notifier.send_email("Test Subject", "<h1>Test</h1>")

        self.assertFalse(result)
        self.assertFalse(mock_smtp_instance.sendmail.called)


if __name__ == "__main__":
    unittest.main()
