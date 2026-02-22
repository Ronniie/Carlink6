import os
import logging
from datetime import timedelta
from functools import partial

import voluptuous as vol

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_NAME, CONF_DEVICE_ID
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cl6_client import CL6Client, TOKEN_FILE_NAME

_LOGGER = logging.getLogger(__name__)

DOMAIN = "carlink6"
CONF_VEHICLES = "vehicles"
CONF_POLL_INTERVAL = "poll_interval"

VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.positive_int,
        vol.Optional(CONF_NAME): cv.string,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_NAME): cv.string,
                vol.Optional(CONF_POLL_INTERVAL, default=30): cv.positive_int,
                vol.Optional(CONF_VEHICLES): vol.All(
                    cv.ensure_list, [VEHICLE_SCHEMA]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up the Carlink6 component."""
    _LOGGER.info("Carlink6 starting setup")
    conf = config[DOMAIN]
    email = conf[CONF_EMAIL]
    password = conf[CONF_PASSWORD]
    poll_interval = conf[CONF_POLL_INTERVAL]
    default_name = conf.get(CONF_NAME)

    # Token file lives in HA's config/.storage directory
    token_path = os.path.join(hass.config.path(".storage"), TOKEN_FILE_NAME)

    # Create a single shared client
    try:
        client = await hass.async_add_executor_job(
            partial(CL6Client, email=email, password=password, token_path=token_path)
        )
    except Exception as err:
        _LOGGER.error("Failed to initialize CL6 client: %s", err)
        return False

    # Resolve vehicles
    configured_vehicles = conf.get(CONF_VEHICLES)

    if configured_vehicles:
        # Use explicitly configured vehicles
        vehicles = []
        for v in configured_vehicles:
            vehicles.append({
                "device_id": v[CONF_DEVICE_ID],
                "name": v.get(CONF_NAME, f"Vehicle {v[CONF_DEVICE_ID]}"),
            })
    else:
        # Auto-discover vehicles
        try:
            vehicles = await hass.async_add_executor_job(
                client.discover_vehicles, default_name
            )
        except Exception as err:
            _LOGGER.error("Failed to discover vehicles: %s", err)
            return False

    # Create a coordinator per vehicle
    vehicle_entries = []
    for v in vehicles:
        dev_id = v["device_id"]
        name = v["name"]
        _LOGGER.info("Carlink6 setting up vehicle: %s (device_id=%s)", name, dev_id)

        async def _make_updater(did=dev_id):
            try:
                data = await hass.async_add_executor_job(
                    client.get_vehicle_status, did
                )
            except Exception as err:
                _LOGGER.error(
                    "Carlink6 failed to fetch status for device %s: %s", did, err
                )
                raise
            _LOGGER.debug("Vehicle %s status: %s", did, data)
            return data

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"carlink6_{dev_id}",
            update_method=_make_updater,
            update_interval=timedelta(seconds=poll_interval),
        )
        await coordinator.async_refresh()

        if coordinator.data:
            _LOGGER.info(
                "Carlink6 vehicle: %s (device %s) — status OK", name, dev_id
            )
        else:
            _LOGGER.error(
                "Carlink6 vehicle: %s (device %s) — first status fetch returned no data. "
                "Last error: %s",
                name, dev_id, coordinator.last_exception,
            )

        vehicle_entries.append({
            "device_id": dev_id,
            "name": name,
            "coordinator": coordinator,
        })

    # Store shared objects for platforms
    hass.data[DOMAIN] = {
        "client": client,
        "vehicles": vehicle_entries,
    }

    # Load platforms
    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )
    hass.async_create_task(
        discovery.async_load_platform(hass, "button", DOMAIN, {}, config)
    )

    return True
