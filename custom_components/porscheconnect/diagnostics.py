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

from . import PorscheConnectConfigEntry

# Top-level entry-data keys we hand to async_redact_data. Anything stored
# under one of these is replaced with ``**REDACTED**``.
TO_REDACT_ENTRY: set[str] = {
    CONF_PASSWORD,
    CONF_ACCESS_TOKEN,
    "refresh_token",
    "token",
    "captcha",
    "state",
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
}

# Local-part of an email is masked once it gets longer than this threshold.
_EMAIL_LOCAL_KEEP = 2

# VIN suffix length we keep visible (last N chars).
_VIN_SUFFIX_KEEP = 4

# Coordinates are rounded to this many decimals (≈ 11 km precision at the
# equator) — enough to debug geofencing without leaking the user's home.
_COORD_DECIMALS = 1


def _mask_email(email: str | None) -> str | None:
    """Mask an email's local part, keeping the first two characters."""
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    if len(local) <= _EMAIL_LOCAL_KEEP:
        masked_local = local + "***"
    else:
        masked_local = local[:_EMAIL_LOCAL_KEEP] + "***"
    return f"{masked_local}@{domain}"


def _mask_vin(vin: str | None) -> str | None:
    """Keep only the last four characters of a VIN."""
    if not vin:
        return vin
    if len(vin) <= _VIN_SUFFIX_KEEP:
        return "***" + vin
    return "***" + vin[-_VIN_SUFFIX_KEEP:]


def _round_coord(value: object) -> object:
    """Round a latitude/longitude to one decimal place."""
    try:
        return round(float(value), _COORD_DECIMALS)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return value


def _redact_vehicle_data(data: object) -> object:
    """Walk a vehicle ``.data`` payload, redacting sensitive fields.

    Coordinates are blurred to one decimal instead of being fully redacted —
    that's enough to break geolocation but still useful for debugging
    "is the API returning a sensible position at all?".
    """
    if isinstance(data, dict):
        result: dict[str, object] = {}
        for key, value in data.items():
            lower_key = key.lower()
            if lower_key in {"latitude", "lat", "longitude", "lon"}:
                result[key] = _round_coord(value)
            elif key in TO_REDACT_VEHICLE_DATA:
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

    redacted_entry_data = async_redact_data(dict(entry.data), TO_REDACT_ENTRY)
    if CONF_EMAIL in redacted_entry_data:
        redacted_entry_data[CONF_EMAIL] = _mask_email(redacted_entry_data[CONF_EMAIL])

    vehicles: list[dict[str, Any]] = []
    for vehicle in getattr(coordinator, "vehicles", []) or []:
        raw_data = getattr(vehicle, "data", {}) or {}
        vehicles.append(
            {
                "vin": _mask_vin(getattr(vehicle, "vin", None)),
                "model_name": getattr(vehicle, "model_name", None)
                or raw_data.get("modelName"),
                "privacy_mode": getattr(vehicle, "privacy_mode", None),
                "capabilities": _vehicle_capability_flags(vehicle),
                "data": _redact_vehicle_data(raw_data),
            },
        )

    last_success_time = getattr(coordinator, "last_update_success_time", None)
    update_interval = getattr(coordinator, "update_interval", None)

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": _mask_email(entry.title) if entry.title else entry.title,
            "version": entry.version,
            "domain": entry.domain,
            "created_at": getattr(entry, "created_at", None)
            and entry.created_at.isoformat(),
            "modified_at": getattr(entry, "modified_at", None)
            and entry.modified_at.isoformat(),
            "data": redacted_entry_data,
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "last_update_success_time": (
                last_success_time.isoformat() if last_success_time is not None else None
            ),
            "update_interval_seconds": (
                update_interval.total_seconds() if update_interval is not None else None
            ),
        },
        "vehicle_count": len(vehicles),
        "vehicles": vehicles,
    }
