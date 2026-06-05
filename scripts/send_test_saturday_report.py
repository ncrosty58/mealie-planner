import os
import sys
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mealie_planner.unified_client import UnifiedMealieClient
from mealie_planner.ai_client import AIClient
from mealie_planner.email_notifier import EmailNotifier
from mealie_planner.utils import get_active_week_strings

def send_test_report():
    print("Initializing test Saturday report email...")
    client = UnifiedMealieClient()
    ai = AIClient()
    notifier = EmailNotifier(client, ai)
    
    start_str, end_str = get_active_week_strings()
    print(f"Active week strings: {start_str} to {end_str}")
    
    # Trigger the Saturday report email
    success = notifier.send_saturday_report_email(
        start_date_str="2026-06-05",
        end_date_str=end_str,
        exclude_text="none",
        freezer_items="none",
        low_staples_ids=[],
        special_requests="none"
    )
    if success:
        print("Test Saturday report email sent successfully!")
    else:
        print("Failed to send test Saturday report email.")

if __name__ == '__main__':
    send_test_report()
