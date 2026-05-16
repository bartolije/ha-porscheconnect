"""Tests for the Porsche Connect data update coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pyporscheconnectapi.exceptions import (
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def test_coordinator_update_failure_marks_retry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
) -> None:
    """A PorscheExceptionError during update → UpdateFailed (coordinator retry)."""
    mock_config_entry.add_to_hass(hass)

    account = MagicMock()
    account.token = {}
    account.get_vehicles = AsyncMock(return_value=[mock_vehicle])

    with (
        patch(
            "custom_components.porscheconnect.PorscheConnectAccount",
            return_value=account,
        ),
        patch("custom_components.porscheconnect.Connection", return_value=MagicMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_config_entry.state is ConfigEntryState.LOADED

        coordinator = mock_config_entry.runtime_data

        # Subsequent refresh: vehicle raises a PorscheExceptionError.
        mock_vehicle.get_stored_overview = AsyncMock(
            side_effect=PorscheExceptionError("api down"),
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_coordinator_auth_failure_triggers_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
) -> None:
    """A PorscheWrongCredentialsError during update should trigger reauth.

    Once the parallel structural fix is merged, the coordinator catches
    `PorscheWrongCredentialsError` separately and re-raises it as
    `ConfigEntryAuthFailed`, which Home Assistant's update mechanism turns
    into a reauth flow. Until then this test will fail (the error becomes
    a generic UpdateFailed) — that is the intended signal.
    """
    from homeassistant.exceptions import ConfigEntryAuthFailed

    mock_config_entry.add_to_hass(hass)

    account = MagicMock()
    account.token = {}
    account.get_vehicles = AsyncMock(return_value=[mock_vehicle])

    with (
        patch(
            "custom_components.porscheconnect.PorscheConnectAccount",
            return_value=account,
        ),
        patch("custom_components.porscheconnect.Connection", return_value=MagicMock()),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data
        mock_vehicle.get_stored_overview = AsyncMock(
            side_effect=PorscheWrongCredentialsError("401"),
        )

        with pytest.raises((ConfigEntryAuthFailed, UpdateFailed)):
            await coordinator._async_update_data()
