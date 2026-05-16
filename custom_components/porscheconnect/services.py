"""Porsche Connect services."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)

ATTR_VEHICLE = "vehicle"

ATTR_TEMPERATURE = "temperature"
ATTR_FRONT_LEFT = "front_left"
ATTR_FRONT_RIGHT = "front_right"
ATTR_REAR_LEFT = "rear_left"
ATTR_REAR_RIGHT = "rear_right"

SERVICE_VEHICLE_SCHEMA = vol.Schema(
    {
        vol.Required("vehicle"): cv.string,
    }
)

SERVICE_CLIMATISATION_START_SCHEMA = SERVICE_VEHICLE_SCHEMA.extend(
    {
        vol.Optional(ATTR_TEMPERATURE): cv.positive_float,
        vol.Optional(ATTR_FRONT_LEFT): cv.boolean,
        vol.Optional(ATTR_FRONT_RIGHT): cv.boolean,
        vol.Optional(ATTR_REAR_LEFT): cv.boolean,
        vol.Optional(ATTR_REAR_RIGHT): cv.boolean,
    }
)

SERVICE_CLIMATISATION_START = "climatisation_start"

SERVICES = (SERVICE_CLIMATISATION_START,)


def _resolve_vehicle(
    hass: HomeAssistant, service_call_data: Mapping
) -> PorscheVehicle:
    """Resolve a PorscheVehicle from the device id given in service data.

    Services are domain-global, so we have to map the device back to its
    config entry's coordinator at call time instead of capturing a single
    coordinator at registration.
    """
    device_registry = dr.async_get(hass)
    device_id = service_call_data[ATTR_VEHICLE]
    device_entry = device_registry.async_get(device_id)

    if device_entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    porsche_vins = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }

    for entry_id in device_entry.config_entries:
        config_entry = hass.config_entries.async_get_entry(entry_id)
        if config_entry is None or config_entry.domain != DOMAIN:
            continue
        coordinator = getattr(config_entry, "runtime_data", None)
        if coordinator is None:
            continue
        for vehicle in coordinator.vehicles:
            if vehicle.vin in porsche_vins:
                return vehicle

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="no_config_entry_for_device",
        translation_placeholders={"device_id": device_entry.name or device_id},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register Porsche Connect services at the domain level.

    Idempotent: re-registering an already-registered service is a no-op so
    that setup-on-second-entry doesn't blow up.
    """

    async def climatisation_start(service_call: ServiceCall) -> None:
        """Start climatisation."""
        temperature: float | None = service_call.data.get(ATTR_TEMPERATURE)
        front_left: bool = service_call.data.get(ATTR_FRONT_LEFT) or False
        front_right: bool = service_call.data.get(ATTR_FRONT_RIGHT) or False
        rear_left: bool = service_call.data.get(ATTR_REAR_LEFT) or False
        rear_right: bool = service_call.data.get(ATTR_REAR_RIGHT) or False

        LOGGER.debug(
            "Starting climatisation: %s, %s, %s, %s, %s",
            temperature,
            front_left,
            front_right,
            rear_left,
            rear_right,
        )
        vehicle = _resolve_vehicle(hass, service_call.data)
        try:
            await vehicle.remote_services.climatise_on(
                target_temperature=293.15
                if temperature is None
                else temperature + 273.15,
                front_left=front_left,
                front_right=front_right,
                rear_left=rear_left,
                rear_right=rear_right,
            )
        except PorscheExceptionError as ex:
            raise HomeAssistantError(ex) from ex

    if not hass.services.has_service(DOMAIN, SERVICE_CLIMATISATION_START):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLIMATISATION_START,
            climatisation_start,
            schema=SERVICE_CLIMATISATION_START_SCHEMA,
        )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove Porsche Connect services on last entry unload."""
    for service in SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
