"""Diagnostics support for Porsche Connect.

Produces a redacted snapshot of the config entry and its loaded vehicles so
users can attach useful state to bug reports without leaking credentials,
tokens, VINs, or precise location data.
"""

from __future__ import annotations

import contextlib
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import PorscheConnectConfigEntry

# Top-level entry-data keys we hand to async_redact_data. Anything stored
# under one of these is replaced with ``**REDACTED**``.
TO_REDACT_ENTRY: set[str] = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_ACCESS_TOKEN,
    "refresh_token",
    "token",
    "captcha",
    "captcha_code",
    "state",
    "code_verifier",
}

# Keys we recursively scrub from vehicle ``.data`` payloads before exposing
# them. Coordinates and addresses can pinpoint a user; we replace them with
# either a sentinel or a rounded value depending on the context.
TO_REDACT_VEHICLE_DATA: set[str] = {
    "address",
    "street",
    "houseNumber",
    "city",
    "postalCode",
    "zip",
    # GPS_LOCATION.location is a "lat,lon" string, not separate coordinates.
    "location",
    # Whole measurements that hold key-pairing secrets or places.
    "PAIRING_CODE",
    "MDK_PAIRING_PASSWORD",
    "BLEID_DDADATA",
    "DESTINATIONS",
    "LOCATION_ALARMS",
    "VTS_CERTIFICATE_LIST",
    # Places the car goes to and when: home, work, departure times.
    "CHARGING_PROFILES",
    "PRED_PRECON_LOCATION_EXCEPTIONS",
    "TIMERS",
    "DEPARTURES",
    # What the owner called the car.
    "customName",
    "name",
}

_COORDINATE_KEYS = {"latitude", "lat", "longitude", "lon", "lng"}

# VIN suffix length we keep visible (last N chars).
_VIN_SUFFIX_KEEP = 4


def _mask_vin(vin: str | None) -> str | None:
    """Keep only the last four characters of a VIN."""
    if not vin:
        return vin
    if len(vin) <= _VIN_SUFFIX_KEEP:
        return "***" + vin
    return "***" + vin[-_VIN_SUFFIX_KEEP:]


def _redact_vehicle_data(data: object) -> object:
    """Walk a vehicle ``.data`` payload, redacting sensitive fields."""
    if isinstance(data, dict):
        result: dict[str, object] = {}
        for key, value in data.items():
            lower_key = key.lower()
            if key in TO_REDACT_VEHICLE_DATA or lower_key in _COORDINATE_KEYS:
                result[key] = "**REDACTED**"
            elif lower_key == "vin":
                result[key] = _mask_vin(value if isinstance(value, str) else None)
            else:
                result[key] = _redact_vehicle_data(value)
        return result
    if isinstance(data, list):
        return [_redact_vehicle_data(item) for item in data]
    return data


def _vehicle_capability_flags(vehicle: object) -> dict[str, bool]:
    """Collect the ``has_*`` capability booleans exposed by PorscheVehicle."""
    flags: dict[str, bool] = {}
    for attr in dir(vehicle):
        if not attr.startswith("has_"):
            continue
        # Some has_* members may be properties that hit the API or raise on
        # incomplete payloads. Diagnostics must never throw, so swallow the
        # specific lookup failure rather than aborting the whole report.
        value: object = None
        with contextlib.suppress(Exception):
            value = getattr(vehicle, attr)
        if isinstance(value, bool):
            flags[attr] = value
    return flags


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: PorscheConnectConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "created_at": entry.created_at.isoformat(),
            "modified_at": entry.modified_at.isoformat(),
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
        },
        "vehicle_count": len(coordinator.vehicles),
        "vehicles": [
            {
                "vin": _mask_vin(vehicle.vin),
                "model_name": vehicle.model_name,
                "privacy_mode": vehicle.privacy_mode,
                "capabilities": _vehicle_capability_flags(vehicle),
                "data": _redact_vehicle_data(vehicle.data),
            }
            for vehicle in coordinator.vehicles
        ],
    }
