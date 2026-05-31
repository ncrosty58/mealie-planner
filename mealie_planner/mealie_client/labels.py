class LabelsMixin:
    def get_labels(self):
        """Fetch all multi-purpose labels."""
        res = self._request("GET", "/api/groups/labels")
        if isinstance(res, dict):
            return res.get('items', [])
        return []

    def create_label(self, name, color="#959595"):
        """Create a new shopping label."""
        payload = {"name": name, "color": color}
        return self._request("POST", "/api/groups/labels", json=payload)
