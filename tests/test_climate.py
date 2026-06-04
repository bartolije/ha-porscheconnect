"""Unit tests for the Porsche Connect climate platform.

Direct entity instantiation with a mocked coordinator + vehicle stand-in (no
full HA setup), exercising the climate actions and their error mapping.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.climate import HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.exceptions import HomeAssistantError
from pyporscheconnectapi.exceptions import PorscheExceptionError

from custom_components.porscheconnect.climate import PorscheClimate


def _vehicle(**overrides) -> SimpleNamespace:
    """A vehicle stand-in exposing the attrs the climate platform reads."""
    remote_services = SimpleNamespace(
        climatise_on=AsyncMock(),
        climatise_off=AsyncMock(),
    )
    attrs = {
        "vin": "VIN1",
        "model_name": "Taycan",
        "data": {"name": "Taycan", "modelName": "Taycan", "vin": "VIN1"},
        "remote_services": remote_services,
        "has_remote_climatisation": True,
        "has_remote_services": True,
        "remote_climatise_on": False,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _make(coordinator, vehicle) -> PorscheClimate:
    return PorscheClimate(coordinator, vehicle)


def test_hvac_mode_reflects_climatise_state():
    coord = MagicMock()
    assert _make(coord, _vehicle(remote_climatise_on=False)).hvac_mode is HVACMode.OFF
    assert (
        _make(coord, _vehicle(remote_climatise_on=True)).hvac_mode is HVACMode.HEAT_COOL
    )


@pytest.mark.asyncio
async def test_turn_on_sends_climatise_on_with_kelvin_target():
    coord = MagicMock()
    vehicle = _vehicle()
    climate = _make(coord, vehicle)  # default target 20 °C

    await climate.async_turn_on()

    vehicle.remote_services.climatise_on.assert_awaited_once()
    kwargs = vehicle.remote_services.climatise_on.await_args.kwargs
    assert kwargs["target_temperature"] == pytest.approx(293.15)  # 20 + 273.15
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_turn_off_sends_climatise_off():
    coord = MagicMock()
    vehicle = _vehicle()
    climate = _make(coord, vehicle)

    await climate.async_turn_off()

    vehicle.remote_services.climatise_off.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_set_hvac_mode_maps_to_start_and_stop():
    coord = MagicMock()
    vehicle = _vehicle()
    climate = _make(coord, vehicle)

    await climate.async_set_hvac_mode(HVACMode.HEAT_COOL)
    vehicle.remote_services.climatise_on.assert_awaited_once()

    await climate.async_set_hvac_mode(HVACMode.OFF)
    vehicle.remote_services.climatise_off.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_temperature_while_on_reapplies_converted_target():
    coord = MagicMock()
    vehicle = _vehicle(remote_climatise_on=True)
    climate = _make(coord, vehicle)

    await climate.async_set_temperature(**{ATTR_TEMPERATURE: 22.0})

    assert climate.target_temperature == 22.0
    kwargs = vehicle.remote_services.climatise_on.await_args.kwargs
    assert kwargs["target_temperature"] == pytest.approx(295.15)  # 22 + 273.15


@pytest.mark.asyncio
async def test_set_temperature_while_off_stores_without_command():
    coord = MagicMock()
    vehicle = _vehicle(remote_climatise_on=False)
    climate = _make(coord, vehicle)
    # async_write_ha_state needs hass when off; stub it for the unit test.
    climate.async_write_ha_state = MagicMock()

    await climate.async_set_temperature(**{ATTR_TEMPERATURE: 18.0})

    assert climate.target_temperature == 18.0
    vehicle.remote_services.climatise_on.assert_not_awaited()
    climate.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_api_error_maps_to_home_assistant_error():
    coord = MagicMock()
    vehicle = _vehicle()
    vehicle.remote_services.climatise_on = AsyncMock(
        side_effect=PorscheExceptionError(500),
    )
    climate = _make(coord, vehicle)

    with pytest.raises(HomeAssistantError):
        await climate.async_turn_on()
