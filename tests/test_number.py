"""Unit tests for the Porsche Connect number platform.

These instantiate the entity directly with a mocked coordinator and a
lightweight vehicle stand-in, then exercise the action method — no full HA
setup, so the remote-service call and its error mapping are verified in
isolation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyporscheconnectapi.exceptions import PorscheExceptionError

from custom_components.porscheconnect.number import NUMBER_TYPES, PorscheNumber


def _vehicle(**overrides) -> SimpleNamespace:
    """A vehicle stand-in exposing the attrs the number platform reads."""
    remote_services = SimpleNamespace(
        set_target_soc=AsyncMock(),
    )
    attrs = {
        "vin": "VIN1",
        "model_name": "Taycan",
        "data": {"name": "Taycan", "modelName": "Taycan", "vin": "VIN1"},
        "remote_services": remote_services,
        "has_electric_drivetrain": True,
        "has_remote_services": True,
        "charging_target": 80,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _desc(key: str):
    return next(d for d in NUMBER_TYPES if d.key == key)


def _make(coordinator, vehicle, key: str) -> PorscheNumber:
    return PorscheNumber(coordinator, vehicle, _desc(key))


def test_available_gating_requires_electric_and_remote_services():
    """target_soc needs both an electric drivetrain and remote services."""
    desc = _desc("target_soc")

    assert desc.is_available(_vehicle()) is True

    assert desc.is_available(_vehicle(has_electric_drivetrain=False)) is False
    assert desc.is_available(_vehicle(has_remote_services=False)) is False
    assert (
        desc.is_available(
            _vehicle(has_electric_drivetrain=False, has_remote_services=False),
        )
        is False
    )


def test_native_value_reads_value_fn():
    coord = MagicMock()
    vehicle = _vehicle(charging_target=65)
    assert _make(coord, vehicle, "target_soc").native_value == 65


@pytest.mark.asyncio
async def test_set_native_value_invokes_remote_service_and_refresh():
    coord = MagicMock()
    vehicle = _vehicle()
    number = _make(coord, vehicle, "target_soc")

    await number.async_set_native_value(70.0)

    vehicle.remote_services.set_target_soc.assert_awaited_once_with(target_soc=70)
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_set_native_value_maps_api_error_to_home_assistant_error():
    coord = MagicMock()
    vehicle = _vehicle()
    vehicle.remote_services.set_target_soc = AsyncMock(
        side_effect=PorscheExceptionError(500),
    )
    number = _make(coord, vehicle, "target_soc")

    with pytest.raises(HomeAssistantError):
        await number.async_set_native_value(70.0)

    coord.async_update_listeners.assert_not_called()
