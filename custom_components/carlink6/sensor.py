import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

_LOGGER = logging.getLogger(__name__)

DOMAIN = "carlink6"

SENSOR_TYPES = {
    "engine_status": {"attr": "EngineStatus", "label": "Engine Status", "icon": "mdi:engine"},
    "door_status": {"attr": "DoorStatus", "label": "Door Status", "icon": "mdi:car-door"},
    "battery_voltage": {"attr": "ExternalVoltage", "label": "Battery Voltage", "icon": "mdi:car-battery", "unit": "V"},
    "gps": {"attr": ["Latitude", "Longitude"], "label": "GPS", "icon": "mdi:crosshairs-gps"},
    "engine_shutdown": {"attr": "EngineShutdownDateTime", "label": "Engine Shutdown", "icon": "mdi:timer-outline", "device_class": "timestamp"},
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Carlink6 sensor entities for all vehicles."""
    data = hass.data.get(DOMAIN)
    if not data:
        _LOGGER.error("Carlink6 not initialized")
        return

    sensors = []
    for vehicle in data["vehicles"]:
        for key, sdef in SENSOR_TYPES.items():
            sensors.append(CL6Sensor(vehicle, key, sdef))

    async_add_entities(sensors)


class CL6Sensor(CoordinatorEntity, SensorEntity):
    """A sensor that reads from a vehicle's shared status coordinator."""

    def __init__(self, vehicle, key, sensor_def):
        super().__init__(vehicle["coordinator"])
        self._vehicle_name = vehicle["name"]
        self._device_id = vehicle["device_id"]
        self._sensor_attr = sensor_def["attr"]
        self._is_gps = isinstance(self._sensor_attr, list)
        self._unit = sensor_def.get("unit")

        self._attr_name = f"{self._vehicle_name} {sensor_def['label']}"
        self._attr_unique_id = f"carlink6_{key}_{self._device_id}"
        self._attr_icon = sensor_def.get("icon")
        self._attr_device_class = sensor_def.get("device_class")

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        if self._is_gps:
            lat = self.coordinator.data.get(self._sensor_attr[0])
            lon = self.coordinator.data.get(self._sensor_attr[1])
            if lat is not None and lon is not None:
                return f"{lat},{lon}"
            return None
        value = self.coordinator.data.get(self._sensor_attr)
        if self._attr_device_class == "timestamp" and value:
            try:
                return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
            except (ValueError, TypeError):
                return None
        return value

    @property
    def native_unit_of_measurement(self):
        return self._unit

    @property
    def extra_state_attributes(self):
        return self.coordinator.data if self.coordinator.data else {}
