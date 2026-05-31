import os
import requests
from ..exceptions import MealieAPIError, ConfigurationError

def get_mealie_token():
    """Retrieve the API token from the MEALIE_TOKEN env var."""
    token = os.getenv('MEALIE_TOKEN')
    if token and token != 'your_mealie_api_token_here':
        return token
    return None

class BaseMealieClient:
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.api_url = os.getenv('MEALIE_API_URL', 'http://mealie:9000')
        self.token = get_mealie_token()
        if not self.token:
            raise ConfigurationError("Mealie API Token (MEALIE_TOKEN) is missing or invalid.")
            
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        })
        self._recipe_details_cache = {}
        self._initialized = True

    @property
    def headers(self):
        """Expose session headers for backwards compatibility."""
        return self.session.headers

    def _request(self, method, path, **kwargs):
        """Internal helper to handle requests and raise custom exceptions."""
        url = f"{self.api_url}{path}"
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 15
        try:
            r = self.session.request(method, url, **kwargs)
            r.raise_for_status()
            if r.status_code == 204 or not r.content:
                return {}
            try:
                return r.json()
            except ValueError:
                return r.text
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if e.response is not None else None
            text = e.response.text if e.response is not None else str(e)
            raise MealieAPIError(f"Mealie API {method} {path} failed: {str(e)}", 
                               status_code=status_code, response_text=text) from e
