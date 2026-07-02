"""Route-level smoke tests using the app factory with fully mocked services."""
import unittest
from unittest.mock import MagicMock, patch

from mealie_planner.web import create_app
from mealie_planner.web.services import Services


def make_app(mealie=None, **overrides):
    mealie = mealie or MagicMock()
    services = Services(
        mealie=mealie,
        ai=overrides.get('ai', MagicMock()),
        crawler=overrides.get('crawler', MagicMock()),
        shopping=overrides.get('shopping', MagicMock()),
        notifier=overrides.get('notifier', MagicMock()),
        nutrition=overrides.get('nutrition', MagicMock()),
        plan_generator=overrides.get('plan_generator', MagicMock()),
    )
    app = create_app(services=services, start_scheduler=False)
    app.config['TESTING'] = True
    return app, services


class TestRoutes(unittest.TestCase):

    def setUp(self):
        patcher_load = patch('mealie_planner.web.routes.planning.load_state', return_value={})
        patcher_save = patch('mealie_planner.web.routes.planning.save_state')
        self.mock_load_state = patcher_load.start()
        self.addCleanup(patcher_load.stop)
        patcher_save.start()
        self.addCleanup(patcher_save.stop)

    def test_index_questionnaire_view_when_no_plans(self):
        mealie = MagicMock()
        mealie.get_meal_plan.return_value = []
        mealie.get_shopping_list_items_for_list.return_value = []
        mealie.get_all_recipes.return_value = []
        mealie.get_users.return_value = []
        app, _ = make_app(mealie)

        resp = app.test_client().get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Plan Next 7 Days', resp.data)

    def test_index_dashboard_view_when_plans_exist(self):
        mealie = MagicMock()
        mealie.get_meal_plan.return_value = [
            {"id": "e1", "date": "2026-06-27", "entryType": "dinner",
             "recipeId": "r1", "recipe": {"name": "Tacos", "slug": "tacos"}, "title": "", "text": ""},
        ]
        mealie.get_shopping_list_items_for_list.return_value = []
        mealie.get_all_recipes.return_value = [{"id": "r1", "name": "Tacos"}]
        mealie.get_users.return_value = []
        mealie.get_labels.return_value = []
        mealie.get_recipes_details_bulk.return_value = {"r1": {"name": "Tacos", "extras": {}}}

        nutrition = MagicMock()
        nutrition.calculate_nutrition_for_range.return_value = ({}, {})
        crawler = MagicMock()
        crawler.check_blackstone_compatibility.return_value = False

        app, _ = make_app(mealie, nutrition=nutrition, crawler=crawler)
        resp = app.test_client().get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Weekly Menu', resp.data)
        self.assertIn(b'Tacos', resp.data)

    def test_toggle_shopping_item(self):
        mealie = MagicMock()
        mealie.get_shopping_list_items_for_list.return_value = [
            {"id": "item-1", "note": "Milk", "checked": False},
        ]
        app, services = make_app(mealie)

        resp = app.test_client().post('/toggle-shopping-item', json={
            "item_id": "item-1", "checked": True, "week": "current",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"success": True})
        self.assertEqual(resp.content_type, 'application/json')
        services.mealie.update_shopping_list_item.assert_called_once()

    def test_toggle_shopping_item_not_found(self):
        mealie = MagicMock()
        mealie.get_shopping_list_items_for_list.return_value = []
        app, _ = make_app(mealie)

        resp = app.test_client().post('/toggle-shopping-item', json={
            "item_id": "nope", "checked": True,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["success"])

    @patch('mealie_planner.web.routes.admin.save_state')
    def test_update_admin_saves_disabled_recipients(self, mock_save):
        app, _ = make_app()
        resp = app.test_client().post('/update-admin', data={
            "emails_enabled": "1",
            "all_known_emails": "a@x.com,b@x.com",
            "enabled_recipients": ["a@x.com"],
        })
        self.assertEqual(resp.status_code, 302)
        saved = mock_save.call_args[0][0]
        self.assertTrue(saved["emails_enabled"])
        self.assertEqual(saved["disabled_recipient_emails"], ["b@x.com"])

    @patch('mealie_planner.web.routes.admin.wipe_mealie_data')
    @patch('mealie_planner.web.routes.admin.save_state')
    def test_clear_route_wipes_selected_week(self, mock_save, mock_wipe):
        app, services = make_app()
        resp = app.test_client().post('/clear', data={"week": "next", "what": "plan"})
        self.assertEqual(resp.status_code, 302)
        mock_wipe.assert_called_once_with(
            week='current', what='plan', clear_past=True, client=services.mealie
        )

    def test_sync_blocked_while_generation_running(self):
        mealie = MagicMock()
        app, services = make_app(mealie)
        lock = services.week_lock('current')
        lock.acquire()
        try:
            resp = app.test_client().post('/sync', data={"week": "current"})
            self.assertEqual(resp.status_code, 302)
            services.shopping.sync_shopping_list.assert_not_called()
        finally:
            lock.release()

    def test_chat_history_returns_json(self):
        app, _ = make_app()
        with patch('mealie_planner.web.routes.chat.load_chat_history',
                   return_value={"history": [], "messages": []}):
            resp = app.test_client().get('/chat-history')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, 'application/json')
        self.assertEqual(resp.get_json(), {"history": [], "messages": []})


if __name__ == "__main__":
    unittest.main()
