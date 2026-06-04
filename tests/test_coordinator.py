"""Tests for the Porsche Connect data update coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
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
    """A PorscheWrongCredentialsError during update triggers reauth.

    The coordinator catches `PorscheWrongCredentialsError` separately and
    re-raises it as `ConfigEntryAuthFailed`, which Home Assistant turns into
    a reauth flow.
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

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()


async def test_coordinator_persists_token_only_when_changed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
) -> None:
    """The token is re-persisted only when it differs from the stored one.

    Guards the change-detection in _async_update_data: the setup-time save
    snapshots the token (deep copy), so an unchanged token must not rewrite
    the entry, while a rotated token must.
    """
    mock_config_entry.add_to_hass(hass)

    account = MagicMock()
    account.token = {"access_token": "abc123", "expires_in": 3600}
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

        # Token unchanged since setup → no rewrite.
        with patch("custom_components.porscheconnect._async_save_token") as save:
            await coordinator._async_update_data()
            save.assert_not_called()

        # Token rotated → persisted exactly once.
        account.token = {"access_token": "rotated", "expires_in": 3600}
        with patch("custom_components.porscheconnect._async_save_token") as save:
            await coordinator._async_update_data()
            save.assert_called_once()


async def test_coordinator_captcha_required_triggers_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
) -> None:
    """A captcha required during polling surfaces as ConfigEntryAuthFailed.

    A captcha can only be answered through the reauth flow, so it must trigger
    reauth rather than a silent UpdateFailed retry.
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
            side_effect=PorscheCaptchaRequiredError(
                captcha="data:image/svg+xml;base64,x", state="ST",
            ),
        )

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()


async def test_picture_locations_retried_when_empty(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
) -> None:
    """A periodic refresh retries get_picture_locations while it stays empty.

    Guards against losing the image entities when the one-shot fetch at setup
    fails: picture_locations never populates here, so each refresh retries.
    """
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
        mock_vehicle.get_picture_locations.reset_mock()
        await coordinator._async_update_data()

        mock_vehicle.get_picture_locations.assert_awaited()
