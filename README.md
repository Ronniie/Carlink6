# Carlink6

A Home Assistant custom integration and standalone CLI for vehicles equipped with Carlink6 (CL6) / MyCar remote start systems.

Control your vehicle remotely — engine start/stop, door lock/unlock — and monitor status (engine, doors, battery voltage, GPS) directly from your Home Assistant dashboard or the command line.

## How It Works

Carlink6 communicates with the M2MSuite API, the same backend used by the official MyCar mobile app. Authentication uses your MyCar app credentials (email and password). The integration uses HTTP Basic Auth against the M2MSuite REST API — no OAuth, no cloud bridge, no third-party dependencies.

### Authentication Flow

1. **Login** — `GET https://api.m2msuite.com/v1.1/109.3/100007/Access` with `Basic base64(email:password)`
2. **Response** — Returns `AccountID`, `APIKey`, and `LastAccess`
3. **Subsequent requests** — Use `Basic base64(@apikey:<APIKey>)` for v1.1 endpoints
4. **Session expiry** — API keys expire after 24 hours; the client automatically re-authenticates
5. **Token persistence** — In Home Assistant, the API key is cached to disk so restarts don't require a fresh login

### Vehicle Commands

Commands are sent as `POST /{accountId}/Commands` with a JSON body:
```json
{"DeviceID": 123456, "Type": "EngineStart"}
```
The command is acknowledged immediately with a command ID. The client then polls `GET /{accountId}/Commands/{commandId}` until a terminal status is reached: `Success`, `Failed`, `TimedOut`, `Nak`, `HardwareTimeout`, or `Squelched`.

Supported commands: `EngineStart`, `EngineStop`, `DoorLock`, `DoorUnlock`, `TrunkRelease`, `Aux1Activate`, `Aux2Activate`, `Aux3Activate`, `Aux4Activate`, `WakeUp`, `Locate`.

---

## Home Assistant Integration

### Installation

1. Copy the `custom_components/carlink6/` folder to your Home Assistant config directory:
   ```
   /config/custom_components/carlink6/
   ```
   The folder should contain: `__init__.py`, `cl6_client.py`, `sensor.py`, `button.py`, `manifest.json`

2. Add to your `configuration.yaml`:
   ```yaml
   carlink6:
     email: "you@example.com"
     password: "your_mycar_password"
   ```

3. Restart Home Assistant.

### Configuration Options

```yaml
# Minimal — auto-discovers your vehicle from your account profile
carlink6:
  email: "you@example.com"
  password: "your_password"

# With a custom display name
carlink6:
  email: "you@example.com"
  password: "your_password"
  name: "My Car"

# Explicit vehicle by device ID
carlink6:
  email: "you@example.com"
  password: "your_password"
  vehicles:
    - device_id: 12345
      name: "My Car"

# Multiple vehicles
carlink6:
  email: "you@example.com"
  password: "your_password"
  poll_interval: 30
  vehicles:
    - device_id: 12345
      name: "Honda Accord"
    - device_id: 67890
      name: "Toyota Camry"
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `email` | Yes | — | Your MyCar / CL6 app login email |
| `password` | Yes | — | Your MyCar / CL6 app password |
| `name` | No | `"My Car"` | Display name for auto-discovered vehicle |
| `poll_interval` | No | `30` | Seconds between status polls |
| `vehicles` | No | auto-discover | Explicit list of vehicles by `device_id` and `name` |

If `vehicles` is omitted, the integration auto-discovers your vehicle using your account's default device. You can find your `device_id` using the CLI (see below).

### Entities Created

For each vehicle, the integration creates:

**Sensors** (update every `poll_interval` seconds):
| Entity | Example Value | Description |
|--------|---------------|-------------|
| `sensor.<name>_engine_status` | `off` / `running` | Engine state |
| `sensor.<name>_door_status` | `locked` / `unlocked` | Door lock state |
| `sensor.<name>_battery_voltage` | `12.1` | Battery voltage (V) |
| `sensor.<name>_gps` | `40.768,-75.364` | Latitude,Longitude |

**Buttons** (fire-and-forget commands):
| Entity | Command Sent |
|--------|-------------|
| `button.<name>_engine_start` | `EngineStart` |
| `button.<name>_engine_stop` | `EngineStop` |
| `button.<name>_door_lock` | `DoorLock` |
| `button.<name>_door_unlock` | `DoorUnlock` |

> **Note:** The `<name>` portion of entity IDs is determined by Home Assistant when entities are first registered. Check **Developer Tools > States** and search for `carlink6` to find your exact entity IDs.

### Lovelace Dashboard Card

A ready-to-use card is included in `custom_components/carlink6/lovelace_card.yml`. To use it:

1. Open your HA dashboard, click the three dots menu, and select **Edit Dashboard**
2. Click **+ Add Card** > **Manual** (YAML editor)
3. Paste the contents of `lovelace_card.yml`
4. Replace every `my_car` in the entity IDs with your actual entity prefix (check Developer Tools > States)

The card provides:
- Engine, door, and battery status at a glance
- Start/Stop/Lock/Unlock buttons
- Color-coded: green Start when engine is running, green Lock when doors are locked, red Unlock when doors are unlocked

### Troubleshooting

Enable debug logging by adding to `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.carlink6: debug
```

After restarting, check logs for:
- `Carlink6 starting setup` — component is loading
- `Restored saved token` / `Logged in as account` — authentication succeeded
- `Using profile default device: <id>` — vehicle discovered
- `status OK` — vehicle status is being fetched
- `first status fetch returned no data` — API call failed (check `Last error` in the same log line)

If entities show "Unknown", verify the component loaded by searching for the above log lines. If no carlink6 logs appear at all, check your `configuration.yaml` syntax.

---

## Standalone CLI

`main.py` is a standalone command-line tool for interacting with your vehicle outside of Home Assistant. It uses the same CL6 API.

### Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`):
```
CL6_EMAIL=you@example.com
CL6_PASSWORD=your_password_here
ENGINE_RUNTIME_MINUTES=15
POLL_INTERVAL_SECONDS=30
```

### Usage

```bash
# List all vehicles on your account
python main.py --get-vehicles

# Get vehicle status (auto-detects device if you only have one)
python main.py --vehicle-status

# Get status for a specific device
python main.py --vehicle-status 123456

# Send a command
python main.py --command EngineStart
python main.py --command EngineStop
python main.py --command DoorLock
python main.py --command DoorUnlock

# Send a command to a specific device
python main.py --command EngineStart 123456
```

When you send `EngineStart`, the CLI will:
1. Send the command and wait for confirmation
2. If successful, continuously poll and print engine status, door status, and battery voltage
3. Stop polling after `ENGINE_RUNTIME_MINUTES` (default: 15 minutes)

### Finding Your Device ID

```bash
python main.py --get-vehicles
```

This prints all vehicles on your account with their IDs. Use that ID in the `--vehicle-status` and `--command` flags, or in your Home Assistant `configuration.yaml` under `vehicles`.

---

## `testing.py`

A minimal scratch script for testing raw API calls. Useful for verifying your API key works or exploring new endpoints. Edit the `API_KEY` and `ACCOUNT_ID` values directly in the file and run:

```bash
python testing.py
```

---

## Project Structure

```
carlink6/
├── main.py                          # Standalone CLI
├── testing.py                       # Quick API test script
├── .env.example                     # Environment variables template
├── .gitignore
├── README.md
└── custom_components/
    └── carlink6/
        ├── __init__.py              # HA component setup, coordinator
        ├── cl6_client.py            # API client (shared by HA + CLI)
        ├── sensor.py                # HA sensor entities
        ├── button.py                # HA button entities
        ├── manifest.json            # HA integration metadata
        ├── example_configuration.yaml
        └── lovelace_card.yml        # Dashboard card template
```

## Why This Exists

I spent the better part of a year trying to get official API access from Carlink. No response. Their product still advertises Alexa and Google Home integration on the box and on their website, but neither actually works anymore — the skills have been pulled, the integrations are dead, and there's no public API or developer program to fill the gap.

So I reverse engineered the CL6 mobile app and built this myself. If Carlink ever decides to offer official API access or restore their smart home integrations, I'd happily switch to a supported solution. Until then, this is what we've got.

## Disclaimer

This project is not affiliated with, endorsed by, or associated with Carlink, MyCar, Automobility, or M2MSuite. All trademarks belong to their respective owners. Use at your own risk.
