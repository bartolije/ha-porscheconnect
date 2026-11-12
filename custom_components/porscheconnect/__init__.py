"""The Porsche Connect integration."""

from __future__ import annotations

import copy
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.typing import ConfigType
from pyporscheconnectapi.account import PorscheConnectAccount
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DOMAIN, PLATFORMS, TRANSIENT_AUTH_FIELDS
from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
    async_save_token,
)
from .services import async_setup_services

if TYPE_CHECKING:
    import httpx2

# Entity keys of the upstream integration (CJNE/ha-porscheconnect) that are
# named differently here, so that switching from it keeps the entities.
_UPSTREAM_KEY_RENAMES = {
    "main_service_range": "main_service_distance",
    "oil_service_range": "oil_service_distance",
    "intermediate_service_range": "intermediate_service_distance",
}

_MINOR_VERSION = 2

# Platforms with one entity per car: their unique ID is the VIN alone. Older
# releases appended the platform name, which the entity registry already knows.
_SINGLE_ENTITY_PLATFORMS = ("climate", "lock")

# This integration is configured exclusively through the UI config flow and has
# no YAML configuration; declaring this satisfies the hassfest CONFIG_SCHEMA
# check for integrations that implement async_setup.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@callback
def async_create_porsche_client(hass: HomeAssistant) -> httpx2.AsyncClient:
    """Return an HTTP client for the Porsche API, for the caller to close.

    A client of its own, because the Auth0 session lives in its cookies. The
    Porsche API returns zstd bodies that httpx2 (HA 2026.11+) cannot decode,
    so the client must not advertise zstd.
    """
    client = create_async_httpx_client(hass, auto_cleanup=False)
    client.headers["Accept-Encoding"] = "gzip, deflate"
    return client


async def async_close_porsche_client(client: httpx2.AsyncClient) -> None:
    """Close a client made by async_create_porsche_client.

    Not `client.aclose()`: Home Assistant makes that attribute refuse to run on
    every client it creates, also on those it leaves for the caller to close.
    """
    await type(client).aclose(client)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Porsche Connect integration: its actions."""
    async_setup_services(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
) -> None:
    """Migrate a config entry to the current schema.

    v1 → v2: drop the in-flight authentication secrets (captcha code, Auth0
    state, PKCE verifier) that older releases persisted alongside the token.
    They are single-use, so replaying them only breaks the next login.

    v2.1 → v2.2: the email, lower-cased, is the unique ID. Entries of the original
    integration kept the email as typed, or had no unique ID, so the same
    account could be set up twice. The polling interval is no longer a setting.
    """
    if config_entry.version == 1:
        data = {
            key: value
            for key, value in config_entry.data.items()
            if key not in TRANSIENT_AUTH_FIELDS
        }
        hass.config_entries.async_update_entry(
            config_entry, data=data, version=2, minor_version=1
        )

    if config_entry.minor_version < _MINOR_VERSION:
        email = config_entry.data[CONF_EMAIL].strip().lower()
        data = {
            key: value
            for key, value in config_entry.data.items()
            if key != CONF_SCAN_INTERVAL
        } | {CONF_EMAIL: email}
        options = {
            key: value
            for key, value in config_entry.options.items()
            if key != CONF_SCAN_INTERVAL
        }
        hass.config_entries.async_update_entry(
            config_entry, data=data, options=options, minor_version=_MINOR_VERSION
        )
        # Two entries for one account may already exist: only one gets the ID.
        if not hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, email):
            hass.config_entries.async_update_entry(config_entry, unique_id=email)


async def _async_migrate_entity_unique_ids(
    hass: HomeAssistant,
    entry: PorscheConnectConfigEntry,
    vehicles: list[PorscheVehicle],
) -> None:
    """Migrate pre-VIN unique_ids (``{name}-{key}``) to the VIN scheme.

    Older releases and the upstream integration keyed entities off the
    (mutable) vehicle name; entities are now keyed off the immutable VIN.
    Rewrite the registry in place so an upgrade, or a switch from upstream,
    reuses the existing entities instead of orphaning them as duplicates.
    """
    vins_by_name = {
        vehicle.data["name"]: vehicle.vin
        for vehicle in vehicles
        if vehicle.data.get("name") and vehicle.vin
    }
    ent_reg = er.async_get(hass)

    @callback
    def _migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        unique_id = entity_entry.unique_id
        for name, vin in vins_by_name.items():
            if unique_id.startswith(f"{name}-"):
                key = unique_id[len(name) + 1 :]
                unique_id = f"{vin}-{_UPSTREAM_KEY_RENAMES.get(key, key)}"
                break
        if entity_entry.domain in _SINGLE_ENTITY_PLATFORMS:
            unique_id = unique_id.removesuffix(f"-{entity_entry.domain}")
        # An entity left over from an earlier install may already hold the
        # target id: keep it, the old one stays an orphan.
        if unique_id == entity_entry.unique_id or ent_reg.async_get_entity_id(
            entity_entry.domain, DOMAIN, unique_id
        ):
            return None
        return {"new_unique_id": unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def async_setup_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> None:
    """Set up an account: log in, read its cars, create their entities."""
    client = async_create_porsche_client(hass)
    # Also runs when the setup fails, so no client outlives its entry.
    entry.async_on_unload(partial(async_close_porsche_client, client))

    controller = PorscheConnectAccount(
        connection=Connection(
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            async_client=client,
            token=entry.data.get(CONF_ACCESS_TOKEN),
        ),
    )
    coordinator = PorscheConnectDataUpdateCoordinator(
        hass,
        config_entry=entry,
        controller=controller,
    )

    # The coordinator turns API errors into ConfigEntryAuthFailed (reauth),
    # ConfigEntryError, or UpdateFailed, which the first refresh raises as
    # ConfigEntryNotReady.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Before the platforms create entities, so that an upgrade reuses the
    # existing entities instead of orphaning them as duplicates.
    await _async_migrate_entity_unique_ids(hass, entry, coordinator.vehicles)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Deep-copy so the persisted snapshot is decoupled from the live token the
    # coordinator keeps mutating in place — otherwise the change-detection in
    # _async_update_data can never see a difference and would stop persisting
    # rotated tokens.
    async_save_token(hass, entry, copy.deepcopy(controller.token))


async def async_unload_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> None:
    """Unload a config entry.

    The actions stay registered: they belong to the integration, not the entry.
    """
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    device_entry: dr.AnyDeviceEntry,
) -> bool:
    """Let the user remove the device of a car that is no longer on the account."""
    if config_entry.state is not ConfigEntryState.LOADED:
        # The account cannot be checked. A car still on it comes back at the
        # next setup.
        return True
    coordinator = config_entry.runtime_data
    device_vins = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }
    if not device_vins.isdisjoint(vehicle.vin for vehicle in coordinator.vehicles):
        return False
    for vin in device_vins:
        coordinator.async_forget_vehicle(vin)
    return True
