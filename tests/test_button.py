"""Unit tests for the Porsche Connect button platform.

These instantiate the entity directly with a mocked coordinator and a
lightweight vehicle stand-in, then exercise async_press — no full HA setup,
so the remote-service calls and their error mapping are verified in isolation.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError
from pyporscheconnectapi.exceptions import PorscheExceptionError

from custom_components.porscheconnect.button import BUTTON_TYPES, PorscheButton


def _vehicle(**overrides) -> SimpleNamespace:
    """A vehicle stand-in exposing the attrs the button platform reads."""
    remote_services = SimpleNamespace(
        flash_indicators=AsyncMock(),
        honk_and_flash_indicators=AsyncMock(),
    )
    attrs = {
        "vin": "VIN1",
        "model_name": "Taycan",
        "data": {"name": "Taycan", "modelName": "Taycan", "vin": "VIN1"},
        "remote_services": remote_services,
        "has_remote_services": True,
        "get_current_overview": AsyncMock(),
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _desc(key: str):
    return next(d for d in BUTTON_TYPES if d.key == key)


def _make(coordinator, vehicle, key: str) -> PorscheButton:
    return PorscheButton(coordinator, vehicle, _desc(key))


def test_available_gating_requires_remote_services():
    """All buttons default to needing remote services."""
    no_remote = _vehicle(has_remote_services=False)
    for key in ("get_current_overview", "flash_indicators", "honk_and_flash_indicators"):
        assert _desc(key).is_available(no_remote) is False

    ok = _vehicle()
    for key in ("get_current_overview", "flash_indicators", "honk_and_flash_indicators"):
        assert _desc(key).is_available(ok) is True


@pytest.mark.asyncio
async def test_press_flash_indicators_invokes_remote_service_and_refresh():
    coord = MagicMock()
    vehicle = _vehicle()
    button = _make(coord, vehicle, "flash_indicators")

    await button.async_press()

    vehicle.remote_services.flash_indicators.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_press_get_current_overview_invokes_vehicle_method_and_refresh():
    coord = MagicMock()
    vehicle = _vehicle()
    button = _make(coord, vehicle, "get_current_overview")

    await button.async_press()

    vehicle.get_current_overview.assert_awaited_once()
    coord.async_update_listeners.assert_called_once()


@pytest.mark.asyncio
async def test_press_maps_api_error_to_home_assistant_error():
    coord = MagicMock()
    vehicle = _vehicle()
    vehicle.remote_services.flash_indicators = AsyncMock(
        side_effect=PorscheExceptionError(500),
    )
    button = _make(coord, vehicle, "flash_indicators")

    with pytest.raises(HomeAssistantError):
        await button.async_press()

    # On error the coordinator must not be asked to refresh.
    coord.async_update_listeners.assert_not_called()
