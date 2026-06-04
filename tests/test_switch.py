"""Unit tests for the Porsche Connect switch platform.

These instantiate the entity directly with a mocked coordinator and a
lightweight vehicle stand-in, then exercise the action methods — no full HA
setup, so the remote-service calls and their error mapping are verified in
isolation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyporscheconnectapi.exceptions import PorscheExceptionError

from custom_components.porscheconnect.switch import SWITCH_TYPES, PorscheSwitch


def _vehicle(**overrides) -> SimpleNamespace:
    """A vehicle stand-in exposing the attrs the switch platform reads."""
    remote_services = SimpleNamespace(
        climatise_on=AsyncMock(),
        climatise_off=AsyncMock(),
        direct_charge_on=AsyncMock(),
        direct_charge_off=AsyncMock(),
    )
    attrs = {
        "vin": "VIN1",
        "model_name": "Taycan",
        "data": {"name": "Taycan", "modelName": "Taycan", "vin": "VIN1"},
        "remote_services": remote_services,
        "has_remote_climatisation": True,
        "has_remote_services": True,
        "has_direct_charge": True,
        "remote_climatise_on": False,
        "direct_charge_on": False,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _desc(key: str):
    return next(d for d in SWITCH_TYPES if d.key == key)


def _make(coordinator, vehicle, key: str) -> PorscheSwitch:
    return PorscheSwitch(coordinator, vehicle, _desc(key))


def test_available_gating_requires_remote_services():
    """Both switches need remote services; climatise also needs climatisation."""
    no_remote = _vehicle(has_remote_services=False)
    assert _desc("climatise").is_available(no_remote) is False
    assert _desc("direct_charging").is_available(no_remote) is False

    ok = _vehicle()
    assert _desc("climatise").is_available(ok) is True
    assert _desc("direct_charging").is_available(ok) is True

    no_climate = _vehicle(has_remote_climatisation=False)
    assert _desc("climatise").is_available(no_climate) is False


def test_is_on_reads_value_fn():
    coord = MagicMock()
    vehicle = _vehicle(remote_climatise_on=True, direct_charge_on=False)
    assert _make(coord, vehicle, "climatise").is_on is True
    assert _make(coord, vehicle, "direct_charging").is_on is False


@pytest.mark.asyncio
async def test_turn_on_off_invoke_remote_service_and_refresh():
    coord = MagicMock()
    vehicle = _vehicle()
    switch = _make(coord, vehicle, "direct_charging")

    await switch.async_turn_on()
    vehicle.remote_services.direct_charge_on.assert_awaited_once()

    await switch.async_turn_off()
    vehicle.remote_services.direct_charge_off.assert_awaited_once()

    # Each action asks the coordinator to refresh listeners.
    assert coord.async_update_listeners.call_count == 2


@pytest.mark.asyncio
async def test_turn_on_maps_api_error_to_home_assistant_error():
    coord = MagicMock()
    vehicle = _vehicle()
    vehicle.remote_services.direct_charge_on = AsyncMock(
        side_effect=PorscheExceptionError(500),
    )
    switch = _make(coord, vehicle, "direct_charging")

    with pytest.raises(HomeAssistantError):
        await switch.async_turn_on()
