"""Tests for the vehicle device tracker."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def test_tracker_added_once_privacy_mode_is_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A car in privacy mode at startup gets its tracker when privacy ends."""
    mock_vehicle.privacy_mode = True
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, mock_vehicle.vin) is None

    mock_vehicle.privacy_mode = False
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert registry.async_get_entity_id("device_tracker", DOMAIN, mock_vehicle.vin)
