import logging

from homeassistant.components.button import ButtonEntity

_LOGGER = logging.getLogger(__name__)

DOMAIN = "carlink6"

BUTTONS = [
    {"key": "engine_start", "label": "Engine Start", "command": "EngineStart", "icon": "mdi:engine"},
    {"key": "engine_stop", "label": "Engine Stop", "command": "EngineStop", "icon": "mdi:engine-off"},
    {"key": "door_lock", "label": "Door Lock", "command": "DoorLock", "icon": "mdi:lock"},
    {"key": "door_unlock", "label": "Door Unlock", "command": "DoorUnlock", "icon": "mdi:lock-open"},
]


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Carlink6 button entities for all vehicles."""
    _LOGGER.info("Carlink6 button platform loading")
    data = hass.data.get(DOMAIN)
    if not data:
        _LOGGER.error("Carlink6 not initialized — cannot set up buttons")
        return

    client = data["client"]

    buttons = []
    for vehicle in data["vehicles"]:
        for bdef in BUTTONS:
            buttons.append(CL6Button(client, vehicle, hass, bdef))

    _LOGGER.info("Adding %d Carlink6 buttons", len(buttons))
    async_add_entities(buttons)


class CL6Button(ButtonEntity):
    """A button that sends a vehicle command."""

    def __init__(self, client, vehicle, hass, button_def):
        self._client = client
        self._device_id = vehicle["device_id"]
        self._coordinator = vehicle["coordinator"]
        self._hass = hass
        self._command = button_def["command"]

        self._attr_name = f"{vehicle['name']} {button_def['label']}"
        self._attr_unique_id = f"carlink6_{button_def['key']}_{self._device_id}"
        self._attr_icon = button_def["icon"]

    async def async_press(self):
        """Send the command and poll until terminal status."""
        _LOGGER.info("Sending %s to device %s", self._command, self._device_id)

        try:
            command_id = await self._hass.async_add_executor_job(
                self._client.send_command, self._device_id, self._command
            )
            _LOGGER.info("Command %s accepted (ID: %s)", self._command, command_id)

            result = await self._hass.async_add_executor_job(
                self._client.poll_command, command_id
            )
            final_status = result.get("Status", "Unknown")
            _LOGGER.info("Command %s finished: %s", self._command, final_status)

        except Exception as err:
            _LOGGER.error("Command %s failed: %s", self._command, err)
            return

        # Refresh sensors so dashboard reflects the new state immediately
        await self._coordinator.async_request_refresh()
