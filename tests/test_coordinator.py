"""Tests for the Porsche Connect data update coordinator."""

from __future__ import annotations

from datetime import timedelta
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
from pytest_homeassistant.common import MockConfigEntry

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
        with patch("custom_components.porscheconnect.coordinator.async_save_token") as save:
            await coordinator._async_update_data()
            save.assert_not_called()

        # Token rotated → persisted exactly once.
        account.token = {"access_token": "rotated", "expires_in": 3600}
        with patch("custom_components.porscheconnect.coordinator.async_save_token") as save:
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


async def test_picture_locations_retried_daily_when_empty(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    freezer,
) -> None:
    """Empty picture locations are fetched again once a day, not every refresh.

    Guards against losing the image entities when the one-shot fetch at setup
    fails, without an extra call to a rate-limited API on every refresh.
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
        mock_vehicle.get_picture_locations.assert_not_awaited()

        freezer.tick(timedelta(days=1))
        await coordinator._async_update_data()
        mock_vehicle.get_picture_locations.assert_awaited_once()


def _second_vehicle(mock_vehicle):
    """A second car on the account, built like the shared mock vehicle."""
    from .conftest import _make_vehicle

    other = _make_vehicle()
    other.vin = "WP0ZZZY1ZLSA00002"
    other.data = {**mock_vehicle.data, "vin": other.vin, "name": "Macan"}
    return other


async def test_vehicle_added_to_account_gets_entities_without_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A car paired after setup shows up on the next refresh."""
    from homeassistant.helpers import entity_registry as er

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    other = _second_vehicle(mock_vehicle)
    mock_account.get_vehicles.return_value = [mock_vehicle, other]
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.vehicles == [mock_vehicle, other]
    other.get_stored_overview.assert_awaited_once()
    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{other.vin}-mileage"
    )


async def test_vehicle_removed_from_account_goes_unavailable_and_comes_back(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A car that leaves the account is unavailable and removable, not deleted."""
    from homeassistant.const import STATE_UNAVAILABLE
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from custom_components.porscheconnect import async_remove_config_entry_device

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{mock_vehicle.vin}-mileage"
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, mock_vehicle.vin), mock_config_entry.entry_id
    )
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
    assert not await async_remove_config_entry_device(hass, mock_config_entry, device)

    mock_account.get_vehicles.return_value = []
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    assert await async_remove_config_entry_device(hass, mock_config_entry, device)

    # Back on the account: the entities follow the same vehicle object again.
    mock_account.get_vehicles.return_value = [mock_vehicle]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.vehicles[0] is mock_vehicle
    assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_hanging_api_times_out_instead_of_blocking(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A Porsche API that never answers fails the setup for a later retry."""
    import asyncio

    async def _hang() -> None:
        await asyncio.sleep(3600)

    mock_vehicle.get_stored_overview = AsyncMock(side_effect=_hang)
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.porscheconnect.coordinator._UPDATE_TIMEOUT", 0.01):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_status_without_name_and_failed_pictures_do_not_break_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Neither a status missing the car's name nor a picture error stops setup."""
    from homeassistant.helpers import entity_registry as er

    del mock_vehicle.data["name"]
    mock_vehicle.get_picture_locations = AsyncMock(
        side_effect=PorscheExceptionError("no pictures"),
    )
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    for platform, key in (("sensor", "mileage"), ("binary_sensor", "doors_and_lids")):
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{mock_vehicle.vin}-{key}"
        )
        assert hass.states.get(entity_id) is not None


async def test_throttled_login_is_retried_not_reauthenticated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Porsche throttling logins says nothing about the password."""
    from pyporscheconnectapi.exceptions import PorscheLoginThrottledError

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    mock_vehicle.get_stored_overview = AsyncMock(
        side_effect=PorscheLoginThrottledError("too many attempts"),
    )

    with pytest.raises(UpdateFailed):
        await mock_config_entry.runtime_data._async_update_data()


async def test_update_errors_are_translated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Errors shown to the user come from the translation files."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data

    mock_vehicle.get_stored_overview = AsyncMock(
        side_effect=PorscheExceptionError("api down")
    )
    with pytest.raises(UpdateFailed) as failed:
        await coordinator._async_update_data()
    assert failed.value.translation_key == "update_failed"
    assert failed.value.translation_placeholders == {"error": "api down"}

    mock_vehicle.get_stored_overview = AsyncMock(
        side_effect=PorscheWrongCredentialsError("refused")
    )
    with pytest.raises(ConfigEntryAuthFailed) as refused:
        await coordinator._async_update_data()
    assert refused.value.translation_key == "auth_failed"


async def test_device_of_an_unloaded_entry_can_be_removed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Without a loaded entry there is no vehicle list to check against."""
    from custom_components.porscheconnect import async_remove_config_entry_device

    mock_config_entry.add_to_hass(hass)

    assert await async_remove_config_entry_device(
        hass, mock_config_entry, MagicMock()
    )
