"""Tests for the config entry diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redact_location_and_pairing_secrets(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Position, pairing codes and key data never reach the diagnostics file."""
    mock_vehicle.data.update(
        {
            "GPS_LOCATION": {"location": "48.85837,2.29448", "direction": 90},
            "PAIRING_CODE": {"value": "123456"},
            "BLEID_DDADATA": {"bleId": "AA:BB:CC", "ddaData": "key-material"},
        }
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    dump = json.dumps(
        await async_get_config_entry_diagnostics(hass, mock_config_entry),
        default=str,
    )

    for secret in ("48.85837", "2.29448", "123456", "AA:BB:CC", "key-material"):
        assert secret not in dump
    assert mock_vehicle.vin not in dump
