import os
import sys
import json
import base64
import time
import argparse
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

ENGINE_RUNTIME_MINUTES = int(os.getenv("ENGINE_RUNTIME_MINUTES", 15))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", 30))


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
        "Squelched"
    }

    def __init__(self):
        self.email = os.getenv("CL6_EMAIL")
        self.password = os.getenv("CL6_PASSWORD")

        if not self.email or not self.password:
            print("Missing CL6_EMAIL or CL6_PASSWORD in .env file")
            sys.exit(1)

        self.session = requests.Session()
        self.account_id = None
        self.api_key = None
        self.last_access = None

        self.login()

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
            print("Login failed:")
            print(r.text)
            sys.exit(1)

        data = r.json()
        self.account_id = data["AccountID"]
        self.api_key = data["APIKey"]
        self.last_access = datetime.fromisoformat(
            data["LastAccess"].replace("+0000", "+00:00")
        )

    def _is_session_expired(self):
        if not self.last_access:
            return True
        now = datetime.now(timezone.utc)
        delta = now - self.last_access
        return delta.total_seconds() > 86400

    def _apikey_auth(self):
        if self._is_session_expired():
            print("Session expired — re-authenticating...")
            self.login()
        return self._basic_auth_header("@apikey", self.api_key)

    def _login_auth(self):
        return self._basic_auth_header(self.email.lower(), self.password)

    def _request(self, method, url, **kwargs):
        use_login = "/v1.3/" in url
        headers = kwargs.pop("headers", {})
        headers.update(self._login_auth() if use_login else self._apikey_auth())
        r = self.session.request(method, url, headers=headers, **kwargs)
        if r.status_code == 401:
            print("401 received — re-authenticating...")
            self.login()
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
        if len(vehicles) == 1:
            return vehicles[0].get("id") or vehicles[0].get("ID")

        print("\nMultiple vehicles found:")
        for v in vehicles:
            vid = v.get("id") or v.get("ID")
            vname = v.get("name") or v.get("Name", "?")
            print(f"  {vid} - {vname}")
        print("\nSpecify a device ID:")
        print("  python main.py --vehicle-status <DEVICE_ID>")
        print("  python main.py --command EngineStart <DEVICE_ID>")
        sys.exit(1)

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
            print(f"Status: {status}")
            if status in self.TERMINAL_STATUSES:
                return result
            time.sleep(interval)


# ----------------------
# CLI
# ----------------------
def main():
    parser = argparse.ArgumentParser(description="CL6 CLI")
    parser.add_argument("--get-vehicles", action="store_true", help="List all vehicles")
    parser.add_argument(
        "--vehicle-status", nargs="?", const=True, help="Get vehicle status (optional DEVICE_ID)"
    )
    parser.add_argument(
        "--command",
        nargs="+",
        help="Send command. Usage: --command TYPE [DEVICE_ID]"
    )
    args = parser.parse_args()
    client = CL6Client()

    if args.get_vehicles:
        vehicles = client.get_vehicles()
        print(json.dumps(vehicles, indent=2))
        return

    if args.vehicle_status is not None:
        device_id = None
        if args.vehicle_status is not True:
            device_id = int(args.vehicle_status)
        resolved_id = client.resolve_device_id(device_id)
        status = client.get_vehicle_status(resolved_id)
        print(json.dumps(status, indent=2))
        return

    if args.command:
        if len(args.command) == 0:
            parser.error("Specify a command type")
        command_type = args.command[0]
        device_id = None
        if len(args.command) > 1:
            device_id = int(args.command[1])
        resolved_id = client.resolve_device_id(device_id)

        # Send command
        command_id = client.send_command(resolved_id, command_type)
        print(f"Command sent. Command ID: {command_id}")
        result = client.poll_command(command_id)
        print("Final command status:")
        print(json.dumps(result, indent=2))

        # If EngineStart, poll status while running
        if command_type == "EngineStart" and result.get("Status") == "Success":
            start_time = time.time()
            while True:
                status = client.get_vehicle_status(resolved_id)
                engine_status = status.get("EngineStatus")
                battery = status.get("ExternalVoltage")
                doors = status.get("DoorStatus")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Engine: {engine_status}, Doors: {doors}, Battery: {battery}V")

                elapsed = time.time() - start_time
                if elapsed >= ENGINE_RUNTIME_MINUTES * 60:
                    print("Engine runtime exceeded. Send EngineStop manually or automate it.")
                    break
                time.sleep(POLL_INTERVAL)

        sys.exit(0 if result.get("Status") == "Success" else 1)

    parser.print_help()


if __name__ == "__main__":
    main()