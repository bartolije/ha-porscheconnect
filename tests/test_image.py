"""Tests for the vehicle image entities."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def test_image_follows_coordinator_updates(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """The image entity listens to the coordinator like the other entities."""
    mock_vehicle.picture_locations = {"sideView": "https://example.invalid/side.png"}
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "image", DOMAIN, f"{mock_vehicle.vin}-side_view"
    )
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    mock_vehicle.get_stored_overview.side_effect = PorscheExceptionError("Test")
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
