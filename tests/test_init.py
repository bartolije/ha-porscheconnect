"""Tests for `custom_components.porscheconnect.__init__`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client
from pyporscheconnectapi.exceptions import (
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant.common import MockConfigEntry

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



async def test_async_setup_entry_client_does_not_accept_zstd(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """The API client must not request zstd bodies, which httpx2 fails to decode."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.porscheconnect.Connection",
        return_value=mock_connection_cls.instance,
    ) as connection_cls:
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    client = connection_cls.call_args.kwargs["async_client"]
    assert client is not get_async_client(hass)
    assert client.headers["Accept-Encoding"] == "gzip, deflate"
    assert not client.is_closed

    # The client belongs to the entry: unloading closes it, and the next setup
    # starts with a new one, without the previous Auth0 session.
    with patch(
        "custom_components.porscheconnect.Connection",
        return_value=mock_connection_cls.instance,
    ) as connection_cls:
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert client.is_closed
    assert connection_cls.call_args.kwargs["async_client"] is not client


async def test_failed_setup_closes_its_http_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_account,
    mock_account_cls,
) -> None:
    """Home Assistant retries a failed setup: no client may pile up."""
    mock_account.get_vehicles.side_effect = PorscheExceptionError("down")
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.porscheconnect.Connection", return_value=MagicMock()
    ) as connection_cls:
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert connection_cls.call_args.kwargs["async_client"].is_closed


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



async def test_unique_id_migration_from_upstream_keys(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Upstream's service *_range keys map to *_distance, keeping the entity."""
    from homeassistant.helpers import entity_registry as er

    mock_vehicle.data["MAIN_SERVICE_RANGE"] = {"kilometers": 11200}
    mock_config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{mock_vehicle.data['name']}-main_service_range",
        config_entry=mock_config_entry,
        suggested_object_id="garage_next_service_in",
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    migrated = ent_reg.async_get(old.entity_id)
    assert migrated.unique_id == f"{mock_vehicle.vin}-main_service_distance"
    assert hass.states.get(old.entity_id).state == "11200"


async def test_unique_id_migration_skips_taken_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A leftover entity already holding the VIN id does not break the setup."""
    from homeassistant.helpers import entity_registry as er

    mock_config_entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{mock_vehicle.data['name']}-mileage",
        config_entry=mock_config_entry,
    )
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{mock_vehicle.vin}-mileage",
        config_entry=mock_config_entry,
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(old.entity_id).unique_id.startswith(
        mock_vehicle.data["name"]
    )

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

    assert (entry.version, entry.minor_version) == (2, 2)
    assert TRANSIENT_AUTH_FIELDS.isdisjoint(entry.data)
    assert entry.data[CONF_ACCESS_TOKEN] == {"access_token": "abc123", "expires_in": 3600}


async def test_services_survive_entry_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """A reload (e.g. after reauth) keeps the domain services registered."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, "climatisation_start")
    assert hass.services.has_service(DOMAIN, "climatisation_stop")


def test_library_pin_is_the_same_everywhere() -> None:
    """manifest.json and requirements_test.txt pin the same library version.

    Dependabot only raises the second, and the daily Porsche check reads it.
    """
    import json
    from pathlib import Path

    root = Path(__file__).parent.parent
    manifest = json.loads(
        (root / "custom_components/porscheconnect/manifest.json").read_text()
    )
    (pinned,) = (
        line
        for line in (root / "requirements_test.txt").read_text().splitlines()
        if line.startswith("pyporscheconnectapi")
    )
    assert manifest["requirements"] == [pinned]


@pytest.mark.parametrize("unique_id", ["Tester@Example.com", None])
async def test_migrate_entry_makes_the_lower_cased_email_the_unique_id(
    hass: HomeAssistant,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
    unique_id: str | None,
) -> None:
    """Entries of the original integration: email as typed, or no unique ID.

    The config flow could not recognise them, so the account could be added a
    second time.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        version=2,
        data={
            CONF_EMAIL: " Tester@Example.com",
            CONF_PASSWORD: "hunter2",
            "scan_interval": 60,
        },
        options={"scan_interval": 30},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (entry.version, entry.minor_version) == (2, 2)
    assert entry.unique_id == "tester@example.com"
    assert entry.data[CONF_EMAIL] == "tester@example.com"
    # The polling interval is not a setting: a left-over one is dropped.
    assert "scan_interval" not in entry.data
    assert not entry.options
    assert entry.runtime_data.update_interval.total_seconds() == 1920

    # The account is now recognised: a second setup is refused.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_EMAIL: "TESTER@example.com", CONF_PASSWORD: "x"},
    )
    assert result["reason"] == "already_configured"


async def test_migrate_entry_keeps_a_unique_id_that_is_already_taken(
    hass: HomeAssistant,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Two entries for one account may already exist: only one holds the ID."""
    mock_config_entry.add_to_hass(hass)
    duplicate = MockConfigEntry(
        domain=DOMAIN,
        unique_id="Tester@Example.com",
        version=2,
        data={CONF_EMAIL: "Tester@Example.com", CONF_PASSWORD: "hunter2"},
    )
    duplicate.add_to_hass(hass)

    await hass.config_entries.async_setup(duplicate.entry_id)
    await hass.async_block_till_done()

    assert (duplicate.version, duplicate.minor_version) == (2, 2)
    assert duplicate.unique_id == "Tester@Example.com"
    assert mock_config_entry.unique_id == "tester@example.com"


async def test_lock_and_climate_unique_ids_lose_the_platform_name(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    """Older releases used `<vin>-lock`: the entities are kept, not duplicated."""
    from homeassistant.helpers import entity_registry as er

    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    vin = mock_vehicle.vin
    old = {
        domain: registry.async_get_or_create(
            domain, DOMAIN, f"{vin}-{domain}", config_entry=mock_config_entry
        ).entity_id
        for domain in ("lock", "climate")
    }

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    for domain, entity_id in old.items():
        assert registry.async_get(entity_id).unique_id == vin
        assert registry.async_get_entity_id(domain, DOMAIN, vin) == entity_id
        assert registry.async_get_entity_id(domain, DOMAIN, f"{vin}-{domain}") is None
