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

# Mapping from service-call attribute (snake_case) to API zone key (camelCase),
# as exposed in `CLIMATIZER_STATE.climateZonesEnabled`. The set of keys actually
# present in that payload is per-vehicle: zones the car does not physically have
# are simply missing from the payload (not set to false). See issue #292.
_ZONE_ATTR_TO_API_KEY: dict[str, str] = {
    ATTR_FRONT_LEFT: "frontLeft",
    ATTR_FRONT_RIGHT: "frontRight",
    ATTR_REAR_LEFT: "rearLeft",
    ATTR_REAR_RIGHT: "rearRight",
}


def _resolve_climate_zone_kwargs(
    vehicle: PorscheVehicle,
    service_data: Mapping,
) -> dict[str, bool]:
    """Filter requested seat-heating zones against the vehicle's capabilities.

    Returns the kwargs dict to pass to `climatise_on`. Raises
    `ServiceValidationError` if the caller requested a zone the vehicle does
    not physically have (issue #292).
    """
    supported_zones: set[str] = set(
        vehicle.data.get("CLIMATIZER_STATE", {})
        .get("climateZonesEnabled", {})
        .keys()
    )

    zone_kwargs: dict[str, bool] = {}
    for attr_name, api_key in _ZONE_ATTR_TO_API_KEY.items():
        requested = service_data.get(attr_name)
        if requested is None:
            continue
        if api_key not in supported_zones:
            # Caller asked to control a zone the car doesn't have. Fail loudly
            # so the user can fix their automation rather than silently
            # dropping the parameter — but only when they asked to enable it.
            if requested:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="climate_zone_not_supported",
                    translation_placeholders={
                        "zone": attr_name,
                        "vehicle": vehicle.vin,
                    },
                )
            # `False` on an unsupported zone is harmless — just skip it.
            continue
        zone_kwargs[attr_name] = requested
    return zone_kwargs


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
        vehicle = _resolve_vehicle(hass, service_call.data)

        if not vehicle.has_remote_climatisation:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="climatisation_not_supported",
                translation_placeholders={"vehicle": vehicle.vin},
            )

        # The Porsche API only includes zones the car physically supports
        # in `CLIMATIZER_STATE.climateZonesEnabled`. A missing key means
        # "not available", not "false" — so derive the supported set from
        # the actual payload instead of hardcoding all four zones (#292).
        zone_kwargs = _resolve_climate_zone_kwargs(vehicle, service_call.data)

        LOGGER.debug(
            "Starting climatisation on %s: temperature=%s, zones=%s",
            vehicle.vin,
            temperature,
            zone_kwargs,
        )
        try:
            await vehicle.remote_services.climatise_on(
                target_temperature=293.15
                if temperature is None
                else temperature + 273.15,
                **zone_kwargs,
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
