import os
import json
import logging
import base64
import time
from datetime import datetime, timezone
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_LOGGER = logging.getLogger(__name__)

TOKEN_FILE_NAME = ".carlink6_token.json"


class CL6Client:
    BASE_V1_1 = "https://api.m2msuite.com/v1.1/109.3"
    BASE_V1_3 = "https://api.m2msuite.com/v1.3/109.2"
    DISTRIBUTOR_ID = "100007"

    TERMINAL_STATUSES = {
        "Success",
        "Nak",
        "HardwareTimeout",
        "TimedOut",
        "Failed",
        "Squelched",
    }

    def __init__(self, email=None, password=None, token_path=None):
        self.email = email or os.getenv("CL6_EMAIL")
        self.password = password or os.getenv("CL6_PASSWORD")

        if not self.email or not self.password:
            raise ValueError("Missing CL6 email or password")

        self._token_path = token_path
        self.session = requests.Session()
        self.account_id = None
        self.api_key = None
        self.last_access = None

        # Try to restore a saved token before hitting the API
        if self._load_token():
            _LOGGER.info("Restored saved token for account %s", self.account_id)
        else:
            self.login()

    # ----------------------
    # Token Persistence
    # ----------------------
    def _load_token(self):
        """Load a previously saved token from disk. Returns True if valid."""
        if not self._token_path or not os.path.exists(self._token_path):
            return False
        try:
            with open(self._token_path, "r") as f:
                data = json.load(f)
            self.account_id = data["account_id"]
            self.api_key = data["api_key"]
            self.last_access = datetime.fromisoformat(data["last_access"])
            if self._is_session_expired():
                _LOGGER.info("Saved token is expired, will re-login")
                return False
            return True
        except Exception as err:
            _LOGGER.debug("Could not load saved token: %s", err)
            return False

    def _save_token(self):
        """Persist the current token to disk."""
        if not self._token_path:
            return
        try:
            data = {
                "account_id": self.account_id,
                "api_key": self.api_key,
                "last_access": self.last_access.isoformat(),
            }
            os.makedirs(os.path.dirname(self._token_path), exist_ok=True)
            with open(self._token_path, "w") as f:
                json.dump(data, f)
            _LOGGER.debug("Token saved to %s", self._token_path)
        except Exception as err:
            _LOGGER.warning("Could not save token: %s", err)

    # ----------------------
    # Authentication
    # ----------------------
    def _basic_auth_header(self, username, password):
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def login(self):
        url = f"{self.BASE_V1_1}/{self.DISTRIBUTOR_ID}/Access"
        headers = self._basic_auth_header(self.email.lower(), self.password)
        r = self.session.get(url, headers=headers)
        if r.status_code != 200:
            raise ConnectionError(f"Login failed ({r.status_code}): {r.text}")

        data = r.json()
        self.account_id = data["AccountID"]
        self.api_key = data["APIKey"]
        self.last_access = datetime.fromisoformat(
            data["LastAccess"].replace("+0000", "+00:00")
        )
        _LOGGER.info("Logged in as account %s", self.account_id)
        self._save_token()

    def _is_session_expired(self):
        if not self.last_access:
            return True
        now = datetime.now(timezone.utc)
        delta = now - self.last_access
        return delta.total_seconds() > 86400

    def _apikey_auth(self):
        """Auth header for v1.1 endpoints: @apikey:<APIKey>."""
        if self._is_session_expired():
            _LOGGER.info("Session expired, re-authenticating")
            self.login()
        return self._basic_auth_header("@apikey", self.api_key)

    def _login_auth(self):
        """Auth header for v1.3 endpoints: email:password."""
        return self._basic_auth_header(self.email.lower(), self.password)

    def _request(self, method, url, **kwargs):
        # v1.3 endpoints use login credentials, v1.1 uses API key
        use_login = "/v1.3/" in url
        headers = kwargs.pop("headers", {})
        headers.update(self._login_auth() if use_login else self._apikey_auth())
        r = self.session.request(method, url, headers=headers, **kwargs)

        if r.status_code == 401:
            _LOGGER.info("401 received, re-authenticating")
            try:
                self.login()
            except ConnectionError:
                raise ConnectionError(
                    "Re-authentication failed. Your CL6 email or password "
                    "may have changed. Update your configuration.yaml and "
                    "restart Home Assistant."
                )
            headers.update(self._login_auth() if use_login else self._apikey_auth())
            r = self.session.request(method, url, headers=headers, **kwargs)

        r.raise_for_status()
        return r.json()

    # ----------------------
    # API Methods
    # ----------------------
    def get_profile(self):
        url = f"{self.BASE_V1_1}/{self.account_id}/UserAccount"
        return self._request("GET", url)

    def get_vehicles(self):
        url = f"{self.BASE_V1_3}/{self.account_id}/Assets"
        return self._request("GET", url)

    def get_vehicle_status(self, device_id):
        url = f"{self.BASE_V1_1}/{self.account_id}/DeviceStatus/{device_id}"
        return self._request("GET", url)

    # ----------------------
    # Device Resolution
    # ----------------------
    def resolve_device_id(self, provided_id=None):
        if provided_id:
            return provided_id

        try:
            profile = self.get_profile()
            default_id = profile.get("DefaultDeviceID")
            if default_id:
                return default_id
        except Exception:
            pass

        vehicles = self.get_vehicles()
        if isinstance(vehicles, list) and len(vehicles) == 1:
            # v1.3 Assets returns lowercase "id"
            return vehicles[0].get("id") or vehicles[0].get("ID")

        if isinstance(vehicles, list) and len(vehicles) > 1:
            ids = [f'{v.get("id", v.get("ID"))} ({v.get("name", "?")})' for v in vehicles]
            raise ValueError(f"Multiple vehicles found: {', '.join(ids)}. Set a default or provide an ID.")

        raise ValueError("No vehicles found on account")

    def discover_vehicles(self, default_name=None):
        """Return a list of {'device_id': ..., 'name': ...} for all vehicles on the account.

        Tries the v1.1 profile first (reliable), then v1.3 Assets for multi-vehicle accounts.
        """
        # Try profile's DefaultDeviceID first (v1.1, most reliable)
        try:
            profile = self.get_profile()
            default_id = profile.get("DefaultDeviceID")
            if default_id:
                _LOGGER.info("Using profile default device: %s", default_id)
                return [{"device_id": default_id, "name": default_name or "My Car"}]
        except Exception as err:
            _LOGGER.debug("Could not get profile: %s", err)

        # Fallback: v1.3 Assets (for multi-vehicle accounts or if profile has no default)
        try:
            vehicles = self.get_vehicles()
            if isinstance(vehicles, list) and len(vehicles) > 0:
                _LOGGER.info("Discovered %d vehicle(s) from Assets", len(vehicles))
                return [
                    {
                        "device_id": v.get("id") or v.get("ID"),
                        "name": v.get("name", v.get("Name", f"Vehicle {v.get('id', '?')}")),
                    }
                    for v in vehicles
                ]
        except Exception as err:
            _LOGGER.warning("Could not list vehicles from Assets: %s", err)

        raise ValueError("No vehicles found on account")

    # ----------------------
    # Command Methods
    # ----------------------
    def send_command(self, device_id, command_type, parameters=None):
        url = f"{self.BASE_V1_1}/{self.account_id}/Commands"
        payload = {"DeviceID": device_id, "Type": command_type}
        if parameters:
            payload["Parameters"] = parameters
        response = self._request("POST", url, json=payload)
        return response["ID"]

    def poll_command(self, command_id, interval=1):
        url = f"{self.BASE_V1_1}/{self.account_id}/Commands/{command_id}"
        while True:
            result = self._request("GET", url)
            status = result.get("Status")
            if status in self.TERMINAL_STATUSES:
                return result
            time.sleep(interval)
