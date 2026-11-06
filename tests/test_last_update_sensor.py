"""Tests for the "last update from the car" sensor."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def test_last_update_sensor_reports_when_the_car_sent_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """The sensor exists when the car reports GLOBAL_TIMESTAMP and shows it."""
    mock_vehicle.data["GLOBAL_TIMESTAMP"] = {"timestamp": "2026-11-06T06:30:00Z"}
    mock_vehicle.last_global_update = datetime(2026, 11, 6, 6, 30, tzinfo=UTC)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{mock_vehicle.vin}-last_update"
    )
    assert hass.states.get(entity_id).state == "2026-11-06T06:30:00+00:00"
