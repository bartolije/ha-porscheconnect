"""Unit tests for the Porsche Connect services.

Covers the pure helper `_resolve_climate_zone_kwargs` (issue #292 zone
filtering) in isolation, plus a full-setup integration test of the
`climatisation_start` handler verifying the device→vehicle resolution and the
Celsius→Kelvin temperature conversion.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.porscheconnect.services import (
    ATTR_FRONT_LEFT,
    ATTR_FRONT_RIGHT,
    ATTR_REAR_LEFT,
    ATTR_REAR_RIGHT,
    _resolve_climate_zone_kwargs,
)


def _vehicle(**zones) -> SimpleNamespace:
    """A vehicle stand-in whose CLIMATIZER_STATE advertises the given zones.

    `zones` maps camelCase API keys (frontLeft/...) to their enabled flag; the
    KEYS are what the helper treats as "supported", regardless of value.
    """
    return SimpleNamespace(
        vin="VIN1",
        data={"CLIMATIZER_STATE": {"climateZonesEnabled": dict(zones)}},
    )


def test_requested_and_supported_zone_is_returned():
    """A requested zone present in the payload comes back in the kwargs."""
    vehicle = _vehicle(frontLeft=False)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_LEFT: True})
    assert kwargs == {ATTR_FRONT_LEFT: True}


def test_unsupported_zone_requested_true_raises():
    """Enabling a zone the car doesn't have fails loudly."""
    vehicle = _vehicle(frontLeft=False)
    with pytest.raises(ServiceValidationError):
        _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_RIGHT: True})


def test_unsupported_zone_requested_false_is_skipped():
    """Disabling an unsupported zone is harmless: no error, not in kwargs."""
    vehicle = _vehicle(frontLeft=False)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_REAR_LEFT: False})
    assert kwargs == {}


def test_zone_not_requested_is_omitted():
    """A zone left unset (None) is omitted entirely from the kwargs."""
    vehicle = _vehicle(frontLeft=True, rearRight=True)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_LEFT: True})
    assert kwargs == {ATTR_FRONT_LEFT: True}
    assert ATTR_REAR_RIGHT not in kwargs
    assert ATTR_FRONT_RIGHT not in kwargs


@pytest.mark.asyncio
async def test_climatisation_start_service_converts_celsius_to_kelvin(
    hass,
    mock_config_entry,
    mock_vehicle,
    mock_account_cls,
    mock_connection_cls,
):
    """climatisation_start resolves the device to its vehicle and forwards the
    target temperature converted from Celsius to Kelvin.
    """
    from homeassistant.helpers import device_registry as dr

    from custom_components.porscheconnect.const import DOMAIN

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device = next(
        d
        for d in dr.async_get(hass).devices.values()
        if (DOMAIN, mock_vehicle.vin) in d.identifiers
    )

    await hass.services.async_call(
        DOMAIN,
        "climatisation_start",
        {"vehicle": device.id, "temperature": 21.0},
        blocking=True,
    )

    mock_vehicle.remote_services.climatise_on.assert_awaited_once()
    kwargs = mock_vehicle.remote_services.climatise_on.await_args.kwargs
    # 21 °C + 273.15 = 294.15 K — proves the conversion (not the 293.15 default).
    assert kwargs["target_temperature"] == pytest.approx(294.15)
