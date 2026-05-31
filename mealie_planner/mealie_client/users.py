class UsersMixin:
    def get_users(self):
        """Fetch all users registered in Mealie using the admin endpoint."""
        res = self._request("GET", "/api/admin/users")
        if isinstance(res, dict):
            return res.get('items', [])
        return []
