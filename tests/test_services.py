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
    """A vehicle stand-in whose HVAC_SUMMARY advertises the given zones.

    `zones` maps camelCase API keys (frontLeft/...) to their enabled flag; the
    KEYS are what the helper treats as "supported", regardless of value.
    """
    return SimpleNamespace(vin="VIN1", seat_heating=dict(zones))


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

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, mock_vehicle.vin), mock_config_entry.entry_id
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


async def _setup_and_get_device(hass, entry, vehicle):
    from homeassistant.helpers import device_registry as dr

    from custom_components.porscheconnect.const import DOMAIN

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, vehicle.vin), entry.entry_id
    )


async def test_climatisation_stop_service(
    hass, mock_config_entry, mock_vehicle, mock_account_cls, mock_connection_cls
):
    """climatisation_stop resolves the device and stops climatisation."""
    device = await _setup_and_get_device(hass, mock_config_entry, mock_vehicle)

    await hass.services.async_call(
        "porscheconnect", "climatisation_stop", {"vehicle": device.id}, blocking=True
    )

    mock_vehicle.remote_services.climatise_off.assert_awaited_once()


@pytest.mark.parametrize("service", ["climatisation_start", "climatisation_stop"])
async def test_climatisation_services_report_failures(
    hass, mock_config_entry, mock_vehicle, mock_account_cls, mock_connection_cls, service
):
    """An API error, a car without climatisation and an unknown device each
    give the caller an error, never a silent no-op.
    """
    from unittest.mock import AsyncMock

    from homeassistant.exceptions import HomeAssistantError
    from pyporscheconnectapi.exceptions import PorscheExceptionError

    device = await _setup_and_get_device(hass, mock_config_entry, mock_vehicle)

    async def call(vehicle_id: str) -> None:
        await hass.services.async_call(
            "porscheconnect", service, {"vehicle": vehicle_id}, blocking=True
        )

    failing = AsyncMock(side_effect=PorscheExceptionError("api down"))
    mock_vehicle.remote_services.climatise_on = failing
    mock_vehicle.remote_services.climatise_off = failing
    with pytest.raises(HomeAssistantError) as excinfo:
        await call(device.id)
    assert excinfo.value.translation_key == "remote_service_failed"

    mock_vehicle.has_remote_climatisation = False
    with pytest.raises(ServiceValidationError) as excinfo:
        await call(device.id)
    assert excinfo.value.translation_key == "climatisation_not_supported"

    with pytest.raises(ServiceValidationError) as excinfo:
        await call("not-a-device")
    assert excinfo.value.translation_key == "invalid_device_id"

    # The device exists but its account is not loaded any more.
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    with pytest.raises(ServiceValidationError) as excinfo:
        await call(device.id)
    assert excinfo.value.translation_key == "no_config_entry_for_device"
