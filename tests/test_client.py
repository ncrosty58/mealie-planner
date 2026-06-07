import unittest
from unittest.mock import patch, MagicMock
from mealie_planner.unified_client import UnifiedMealieClient

class TestUnifiedMealieClient(unittest.TestCase):
    @patch("httpx.Client")
    def test_add_shopping_list_item(self, mock_httpx_client):
        # Mock the client instance's get method for the initial connection test
        mock_instance = MagicMock()
        mock_httpx_client.return_value = mock_instance
        
        # Reset singleton instance of UnifiedMealieClient to avoid interference
        UnifiedMealieClient._instance = None
        
        # Create client with dummy URL and token
        client = UnifiedMealieClient(base_url="http://mock-mealie", api_key="mock-key")
        
        # Mock _handle_request
        with patch.object(client, "_handle_request") as mock_handle:
            mock_handle.return_value = {"success": True}
            
            # Call add_shopping_list_item
            client.add_shopping_list_item("list-123", "Apples")
            
            # Assert that _handle_request was called with the correct method, URL, and json payload
            mock_handle.assert_called_once_with(
                "POST", 
                "/api/households/shopping/items", 
                json={"shoppingListId": "list-123", "note": "Apples"}
            )

    @patch("httpx.Client")
    def test_delete_shopping_list_item(self, mock_httpx_client):
        mock_instance = MagicMock()
        mock_httpx_client.return_value = mock_instance
        UnifiedMealieClient._instance = None
        client = UnifiedMealieClient(base_url="http://mock-mealie", api_key="mock-key")
        
        with patch.object(client, "_handle_request") as mock_handle:
            mock_handle.return_value = {"success": True}
            client.delete_shopping_list_item("item-abc")
            
            mock_handle.assert_called_once_with(
                "DELETE", 
                "/api/households/shopping/items/item-abc"
            )

if __name__ == "__main__":
    unittest.main()
