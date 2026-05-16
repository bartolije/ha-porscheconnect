"""Tests for `custom_components.porscheconnect.__init__`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pyporscheconnectapi.exceptions import (
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def test_async_setup_entry_success(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """`async_setup_entry` succeeds with a mocked Account → entry is LOADED."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.entry_id in hass.data[DOMAIN]
    # The coordinator must have collected exactly the vehicle we mocked.
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert len(coordinator.vehicles) == 1
    mock_account.get_vehicles.assert_awaited_once()


async def test_async_setup_entry_auth_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A wrong-credentials error during initial refresh → ConfigEntryAuthFailed.

    The integration only catches PorscheExceptionError today and re-raises
    it as UpdateFailed (which surfaces as SETUP_RETRY). Once the parallel
    structural fix lands, this should bubble up as ConfigEntryAuthFailed
    via reauth. We assert against the expected post-fix behaviour.
    """
    mock_config_entry.add_to_hass(hass)

    account = MagicMock()
    account.token = {}
    account.get_vehicles = AsyncMock(side_effect=PorscheWrongCredentialsError("nope"))

    with (
        patch(
            "custom_components.porscheconnect.PorscheConnectAccount",
            return_value=account,
        ),
        patch("custom_components.porscheconnect.Connection", return_value=MagicMock()),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_async_setup_entry_not_ready(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A generic PorscheExceptionError → SETUP_RETRY (ConfigEntryNotReady)."""
    mock_config_entry.add_to_hass(hass)

    account = MagicMock()
    account.token = {}
    account.get_vehicles = AsyncMock(side_effect=PorscheExceptionError("boom"))

    with (
        patch(
            "custom_components.porscheconnect.PorscheConnectAccount",
            return_value=account,
        ),
        patch("custom_components.porscheconnect.Connection", return_value=MagicMock()),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Unloading the entry tears it down and cleans hass.data[DOMAIN]."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})
