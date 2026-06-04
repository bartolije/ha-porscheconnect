"""Unit tests for the Porsche Connect lock platform.

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

from custom_components.porscheconnect.lock import PorscheLock


def _vehicle(**overrides) -> SimpleNamespace:
    """A vehicle stand-in exposing the attrs the lock platform reads."""
    remote_services = SimpleNamespace(
        lock_vehicle=AsyncMock(),
        unlock_vehicle=AsyncMock(),
    )
    attrs = {
        "vin": "VIN1",
        "model_name": "Taycan",
        "data": {"name": "Taycan", "modelName": "Taycan", "vin": "VIN1"},
        "remote_services": remote_services,
        "has_remote_services": True,
        "vehicle_locked": True,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _make(coordinator, vehicle) -> PorscheLock:
    return PorscheLock(coordinator, vehicle)


def test_door_lock_state_available_gating():
    """door_lock_state_available mirrors the vehicle's remote-service flag."""
    coord = MagicMock()
    assert _make(coord, _vehicle()).door_lock_state_available is True
    assert (
        _make(coord, _vehicle(has_remote_services=False)).door_lock_state_available
        is False
    )


@pytest.mark.asyncio
async def test_lock_invokes_remote_service_and_refreshes():
    coord = MagicMock()
    vehicle = _vehicle()
    lock = _make(coord, vehicle)

    await lock.async_lock()

    vehicle.remote_services.lock_vehicle.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_unlock_with_code_kwarg_invokes_remote_service():
    coord = MagicMock()
    vehicle = _vehicle()
    lock = _make(coord, vehicle)

    await lock.async_unlock(code="1234")

    vehicle.remote_services.unlock_vehicle.assert_awaited_once_with("1234")
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_unlock_without_code_and_empty_options_raises():
    coord = MagicMock()
    vehicle = _vehicle()
    lock = _make(coord, vehicle)
    # No code kwarg and no default code configured -> pin_code_missing.
    lock.registry_entry = SimpleNamespace(options={})

    with pytest.raises(HomeAssistantError):
        await lock.async_unlock()

    vehicle.remote_services.unlock_vehicle.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_maps_api_error_to_home_assistant_error():
    coord = MagicMock()
    vehicle = _vehicle()
    vehicle.remote_services.lock_vehicle = AsyncMock(
        side_effect=PorscheExceptionError(500),
    )
    lock = _make(coord, vehicle)
    # Error path writes state, which needs hass; stub it out for unit testing.
    lock.async_write_ha_state = MagicMock()

    with pytest.raises(HomeAssistantError):
        await lock.async_lock()

    lock.async_write_ha_state.assert_called_once()
    # The finally block still refreshes listeners.
    coord.async_update_listeners.assert_called_once()
