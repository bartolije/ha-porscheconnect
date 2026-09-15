"""Tests for `custom_components.porscheconnect.__init__`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pyporscheconnectapi.exceptions import (
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porscheconnect.const import (
    CONF_CAPTCHA_CODE,
    CONF_CODE_VERIFIER,
    CONF_OAUTH_STATE,
    DOMAIN,
    TRANSIENT_AUTH_FIELDS,
)


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
    # Coordinator now lives on entry.runtime_data (Silver pattern), not hass.data.
    coordinator = mock_config_entry.runtime_data
    assert coordinator is not None
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
    # runtime_data is cleared by HA once the entry is unloaded.
    assert getattr(mock_config_entry, "runtime_data", None) is None


async def test_unique_id_migration_renames_name_keyed_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """An old ``{name}-{key}`` unique_id is migrated to ``{vin}-{key}`` on setup.

    Older releases keyed entities off the vehicle name; the migration rewrites
    the registry so an upgrade reuses the entity instead of orphaning it.
    """
    from homeassistant.helpers import entity_registry as er

    mock_config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{mock_vehicle.data['name']}-mileage",
        config_entry=mock_config_entry,
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    migrated = ent_reg.async_get(old.entity_id)
    assert migrated is not None
    assert migrated.unique_id == f"{mock_vehicle.vin}-mileage"


async def test_migrate_entry_drops_transient_auth_fields(
    hass: HomeAssistant,
    mock_account,  # noqa: ARG001
    mock_connection_cls,  # noqa: ARG001
    mock_account_cls,  # noqa: ARG001
) -> None:
    """A v1 entry still holding an in-flight challenge is migrated to v2.

    Those secrets are single-use: replaying a stale captcha state on the next
    login only makes it fail.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="tester@example.com",
        unique_id="tester@example.com",
        version=1,
        data={
            CONF_EMAIL: "tester@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_ACCESS_TOKEN: {"access_token": "abc123", "expires_in": 3600},
            CONF_CAPTCHA_CODE: "STALE",
            CONF_OAUTH_STATE: "state-token-xyz",
            CONF_CODE_VERIFIER: "verifier-abc",
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert TRANSIENT_AUTH_FIELDS.isdisjoint(entry.data)
    assert entry.data[CONF_ACCESS_TOKEN] == {"access_token": "abc123", "expires_in": 3600}
