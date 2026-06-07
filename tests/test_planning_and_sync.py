import json
import unittest
from unittest.mock import MagicMock, patch

from mealie_planner.plan_generator import classify_early_late_dates
from mealie_planner.shopping_sync import ShoppingListSync
from mealie_planner.config import ACTIVE_LIST_ID


class TestClassifyEarlyLateDates(unittest.TestCase):
    """The perishability day-split that decides which days take fresh vs frozen recipes."""

    def _dates(self, n):
        return [f"2026-05-{30 + i:02d}" for i in range(n)]

    def test_single_day_uses_full_range_for_both(self):
        d = self._dates(1)
        early, late = classify_early_late_dates(d)
        self.assertEqual(early, d)
        self.assertEqual(late, d)

    def test_empty_range(self):
        early, late = classify_early_late_dates([])
        self.assertEqual(early, [])
        self.assertEqual(late, [])

    def test_two_days_split_one_and_one(self):
        d = self._dates(2)
        early, late = classify_early_late_dates(d)
        self.assertEqual(len(early), 1)
        self.assertEqual(len(late), 1)

    def test_three_days_split_two_and_one(self):
        d = self._dates(3)
        early, late = classify_early_late_dates(d)
        self.assertEqual(len(early), 2)
        self.assertEqual(len(late), 1)

    def test_full_week_reserves_last_three_for_late(self):
        d = self._dates(7)
        early, late = classify_early_late_dates(d)
        self.assertEqual(len(early), 4)
        self.assertEqual(len(late), 3)
        self.assertEqual(late, d[4:])

    def test_six_days_reserves_last_three(self):
        d = self._dates(6)
        early, late = classify_early_late_dates(d)
        self.assertEqual(len(early), 3)
        self.assertEqual(len(late), 3)

    def test_partitions_are_contiguous_and_complete(self):
        # For ranges of 2+ days, early + late must reconstruct the original ordered range
        # with no overlap and no gaps.
        for n in range(2, 8):
            d = self._dates(n)
            early, late = classify_early_late_dates(d)
            self.assertEqual(early + late, d, f"failed for n={n}")


class TestShoppingListSyncMerge(unittest.TestCase):
    """The index-mapped merge that preserves Mealie UUIDs/checkmarks and deletes stale items."""

    def _make_syncer(self, active_items, ai_items):
        client = MagicMock()
        ai = MagicMock()
        crawler = MagicMock()

        # No scheduled meals / recipes -> focus the test purely on the merge logic.
        client.get_meal_plan.return_value = []
        client.get_all_recipes.return_value = []
        client.get_recipes_details_bulk.return_value = {}
        # First positional call in sync is staples (STAPLES_LIST_ID); none here.
        client.get_shopping_list_items.return_value = []
        client.get_shopping_list_items_for_list.return_value = active_items
        client.get_labels.return_value = [{"name": "Produce", "id": "lbl-produce"}]

        ai.call.return_value = json.dumps(ai_items)

        syncer = ShoppingListSync(client, ai, crawler)
        return syncer, client

    @patch("mealie_planner.shopping_sync.time.sleep", lambda *a, **k: None)
    def test_match_updates_new_adds_unmatched_deletes(self):
        active_items = [
            {"id": "item-A", "note": "Old Spinach", "checked": True, "labelId": "lbl-existing", "extras": {"is_synced": True}},
            {"id": "item-B", "note": "Stale Thing", "checked": False, "labelId": "lbl-stale", "extras": {"is_synced": True}},
        ]
        ai_items = [
            # matches active index 0 -> update item-A, preserve its checked state
            {"active_item_index": 0, "name": "Spinach", "quantity": 2.0,
             "unit": "oz", "checked": True, "category": "Produce"},
            # brand new item -> add
            {"active_item_index": None, "name": "Carrots", "quantity": 3.0,
             "unit": None, "checked": False, "category": "Produce"},
        ]
        syncer, client = self._make_syncer(active_items, ai_items)

        result = syncer.sync_shopping_list("2026-05-30", "2026-06-05")
        self.assertTrue(result)

        # item-A updated (matched by index), not deleted
        update_args = client.update_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(len(update_args), 1)
        updated = update_args[0]
        self.assertEqual(updated["id"], "item-A")
        self.assertEqual(updated["note"], "oz Spinach")
        self.assertTrue(updated["checked"])
        # existing labelId is preserved over the AI-suggested category label
        self.assertEqual(updated["labelId"], "lbl-existing")

        # new item added with the resolved category label
        add_args = client.add_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(len(add_args), 1)
        self.assertEqual(add_args[0]["note"], "Carrots")
        self.assertEqual(add_args[0]["labelId"], "lbl-produce")
        self.assertEqual(add_args[0]["shoppingListId"], ACTIVE_LIST_ID)

        # item-B was not referenced by the AI output -> deleted
        delete_args = client.delete_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(delete_args, ["item-B"])

    @patch("mealie_planner.shopping_sync.time.sleep", lambda *a, **k: None)
    def test_out_of_range_index_is_treated_as_new_not_a_crash(self):
        # If the LLM emits an index outside the active list, it must be added as a new
        # item rather than indexing out of bounds or silently corrupting another row.
        active_items = [{"id": "item-A", "note": "Eggs", "checked": False, "labelId": "lbl-existing", "extras": {"is_synced": True}}]
        ai_items = [
            {"active_item_index": 99, "name": "Tofu", "quantity": 1.0,
             "unit": None, "checked": False, "category": "Produce"},
        ]
        syncer, client = self._make_syncer(active_items, ai_items)

        result = syncer.sync_shopping_list("2026-05-30", "2026-06-05")
        self.assertTrue(result)

        add_args = client.add_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(len(add_args), 1)
        self.assertEqual(add_args[0]["note"], "Tofu")
        # item-A was never matched -> deleted
        delete_args = client.delete_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(delete_args, ["item-A"])

    @patch("mealie_planner.shopping_sync.time.sleep", lambda *a, **k: None)
    def test_manual_items_without_synced_flag_are_preserved(self):
        active_items = [
            {"id": "item-A", "note": "Old Spinach", "checked": True, "labelId": "lbl-existing", "extras": {"is_synced": True}},
            {"id": "item-manual", "note": "Toilet Paper", "checked": False, "labelId": None, "extras": {}},
        ]
        ai_items = [
            {"active_item_index": 0, "name": "Spinach", "quantity": 2.0,
             "unit": "oz", "checked": True, "category": "Produce"},
            {"active_item_index": 1, "name": "Toilet Paper", "quantity": 1.0,
             "unit": "default", "checked": False, "category": "Produce"},
        ]
        syncer, client = self._make_syncer(active_items, ai_items)

        result = syncer.sync_shopping_list("2026-05-30", "2026-06-05")
        self.assertTrue(result)

        # Both item-A and item-manual should be updated
        update_args = client.update_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(len(update_args), 2)
        
        # item-manual preserves its empty/non-synced extras, filters out 'default' unit, and gets properly categorized
        item_manual_update = next(item for item in update_args if item["id"] == "item-manual")
        self.assertEqual(item_manual_update["note"], "Toilet Paper")
        self.assertEqual(item_manual_update["extras"], {})
        self.assertEqual(item_manual_update["labelId"], "lbl-produce")

        # No items should be deleted
        delete_call = client.delete_shopping_list_items_bulk.call_args
        if delete_call:
            delete_args = delete_call[0][0]
            self.assertEqual(len(delete_args), 0)

    @patch("mealie_planner.shopping_sync.time.sleep", lambda *a, **k: None)
    def test_manual_items_preserved_when_ai_omits_or_misses_index(self):
        active_items = [
            {"id": "item-A", "note": "Old Spinach", "checked": True, "labelId": "lbl-existing", "extras": {"is_synced": True}},
            {"id": "item-manual-1", "note": "Toilet Paper", "checked": False, "labelId": None, "extras": {}},
            {"id": "item-manual-2", "note": "Shampoo", "checked": False, "labelId": None, "extras": {}},
        ]
        ai_items = [
            {"active_item_index": 0, "name": "Spinach", "quantity": 2.0,
             "unit": "oz", "checked": True, "category": "Produce"},
            # AI returns Toilet Paper but misses index (sets it to None)
            {"active_item_index": None, "name": "Toilet Paper", "quantity": 1.0,
             "unit": None, "checked": False, "category": "Produce"},
            # AI completely omits Shampoo
        ]
        syncer, client = self._make_syncer(active_items, ai_items)

        result = syncer.sync_shopping_list("2026-05-30", "2026-06-05")
        self.assertTrue(result)

        # Toilet Paper should be matched via name/semantic fallback in python and updated, keeping is_manual=True
        # Spinach is updated
        # Shampoo is omitted by AI but preserved in python (not deleted, not added as new synced item)
        update_args = client.update_shopping_list_items_bulk.call_args[0][0]
        self.assertEqual(len(update_args), 2)  # Spinach and Toilet Paper are updated
        
        # Toilet Paper was matched semantically
        toilet_paper_update = next(item for item in update_args if item["id"] == "item-manual-1")
        self.assertEqual(toilet_paper_update["note"], "Toilet Paper")
        self.assertEqual(toilet_paper_update["extras"], {})  # preserved manual status!

        # Check that Shampoo (item-manual-2) was NOT deleted
        delete_call = client.delete_shopping_list_items_bulk.call_args
        if delete_call:
            delete_args = delete_call[0][0]
            self.assertNotIn("item-manual-2", delete_args)
            self.assertEqual(len(delete_args), 0)

        # Check that no duplicate Toilet Paper or Shampoo was added as new
        add_call = client.add_shopping_list_items_bulk.call_args
        if add_call:
            add_args = add_call[0][0]
            self.assertEqual(len(add_args), 0)

    @patch("mealie_planner.shopping_sync.time.sleep", lambda *a, **k: None)
    def test_low_staples_preserved_when_ai_omits_them(self):
        # Active items has Eggs (synced, checked=False)
        active_items = [
            {"id": "item-eggs", "note": "Eggs", "checked": False, "labelId": "lbl-produce", "extras": {"is_synced": True}},
        ]
        # AI returns nothing (omitted both Eggs and Milk!)
        ai_items = []
        syncer, client = self._make_syncer(active_items, ai_items)
        
        # Mock staples: Eggs and Milk
        client.get_shopping_list_items.return_value = [
            {"id": "staple-eggs", "note": "Eggs", "quantity": 1.0, "labelId": "lbl-produce"},
            {"id": "staple-milk", "note": "Milk", "quantity": 1.0, "labelId": "lbl-produce"}
        ]
        
        # Sync with Eggs and Milk as low staples
        result = syncer.sync_shopping_list(
            "2026-05-30", "2026-06-05", 
            low_staples_ids=["staple-eggs", "staple-milk"]
        )
        self.assertTrue(result)
        
        # 1. Eggs should NOT be updated (it's not modified, just preserved because it's on active list)
        update_call = client.update_shopping_list_items_bulk.call_args
        if update_call:
            update_args = update_call[0][0]
            self.assertEqual(len(update_args), 0)
        
        # 2. Milk (staple-milk) is a low staple NOT on the active list -> should be added
        add_call = client.add_shopping_list_items_bulk.call_args
        self.assertIsNotNone(add_call)
        add_args = add_call[0][0]
        self.assertEqual(len(add_args), 1)
        self.assertEqual(add_args[0]["note"], "Milk")
        self.assertEqual(add_args[0]["extras"], {"is_synced": True})
        
        # 3. Eggs should NOT be deleted
        delete_call = client.delete_shopping_list_items_bulk.call_args
        if delete_call:
            delete_args = delete_call[0][0]
            self.assertNotIn("item-eggs", delete_args)
            self.assertEqual(len(delete_args), 0)


class TestWeekRanges(unittest.TestCase):
    def test_get_next_week_range(self):
        from datetime import timedelta
        from mealie_planner.utils import get_active_week_range, get_next_week_range
        
        curr_start, curr_end = get_active_week_range()
        next_start, next_end = get_next_week_range()
        
        self.assertEqual(next_start - curr_start, timedelta(days=7))
        self.assertEqual(next_end - curr_end, timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
