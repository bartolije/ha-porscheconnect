"""The Porsche Connect integration."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey
from pyporscheconnectapi.account import PorscheConnectAccount
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DOMAIN, PLATFORMS, TRANSIENT_AUTH_FIELDS
from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
    async_save_token,
)

if TYPE_CHECKING:
    import httpx2

# Entity keys of the upstream integration (CJNE/ha-porscheconnect) that are
# named differently here, so that switching from it keeps the entities.
_UPSTREAM_KEY_RENAMES = {
    "main_service_range": "main_service_distance",
    "oil_service_range": "oil_service_distance",
    "intermediate_service_range": "intermediate_service_distance",
}

# This integration is configured exclusively through the UI config flow and has
# no YAML configuration; declaring this satisfies the hassfest CONFIG_SCHEMA
# check for integrations that implement async_setup.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@callback
def async_create_porsche_client(hass: HomeAssistant) -> httpx2.AsyncClient:
    """Return an HTTP client for the Porsche API.

    The Porsche API returns zstd bodies that httpx2 (HA 2026.11+) cannot
    decode, so the client must not advertise zstd. The header is set on the
    client because create_async_httpx_client only merges headers= since 2026.2.
    """
    client = create_async_httpx_client(hass)
    client.headers["Accept-Encoding"] = "gzip, deflate"
    return client


_ENTRY_CLIENTS: HassKey[dict[str, httpx2.AsyncClient]] = HassKey(
    f"{DOMAIN}_entry_clients"
)


def _async_get_entry_client(hass: HomeAssistant, entry_id: str) -> httpx2.AsyncClient:
    """Return the entry's client, created once per account.

    HA only closes these clients at shutdown, so setup retries and reloads reuse
    it. One per entry: the Auth0 session lives in the cookies, and a new setup
    starts without the previous one, as a new client would.
    """
    clients = hass.data.setdefault(_ENTRY_CLIENTS, {})
    if (client := clients.get(entry_id)) is None:
        client = clients[entry_id] = async_create_porsche_client(hass)
    client.cookies.clear()
    return client


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Porsche Connect integration (domain-level).

    Services are domain-global, so they are registered exactly once here
    rather than per-entry in async_setup_entry — registering per entry would
    overwrite the same handler on every reload and leak references to the
    previously-active coordinator.
    """
    from .services import async_setup_services

    async_setup_services(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
) -> bool:
    """Migrate a config entry to the current schema.

    v1 → v2: drop the in-flight authentication secrets (captcha code, Auth0
    state, PKCE verifier) that older releases persisted alongside the token.
    They are single-use, so replaying them only breaks the next login.
    """
    if config_entry.version == 1:
        data = {
            key: value
            for key, value in config_entry.data.items()
            if key not in TRANSIENT_AUTH_FIELDS
        }
        hass.config_entries.async_update_entry(config_entry, data=data, version=2)
    return True


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
    prefixes = [
        (f"{vehicle.data['name']}-", f"{vehicle.vin}-")
        for vehicle in vehicles
        if vehicle.data.get("name") and vehicle.vin
    ]
    if not prefixes:
        return
    ent_reg = er.async_get(hass)

    @callback
    def _migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        for old_prefix, new_prefix in prefixes:
            if entity_entry.unique_id.startswith(old_prefix):
                key = entity_entry.unique_id[len(old_prefix) :]
                new_unique_id = f"{new_prefix}{_UPSTREAM_KEY_RENAMES.get(key, key)}"
                # An entity left over from an earlier install may already hold
                # the target id: keep it, the old one stays an orphan.
                if ent_reg.async_get_entity_id(
                    entity_entry.domain, DOMAIN, new_unique_id
                ):
                    return None
                return {"new_unique_id": new_unique_id}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def async_setup_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> bool:
    """Set up this integration using UI."""
    connection = Connection(
        entry.data.get("email"),
        entry.data.get("password"),
        async_client=_async_get_entry_client(hass, entry.entry_id),
        token=entry.data.get(CONF_ACCESS_TOKEN, None),
    )

    controller = PorscheConnectAccount(
        connection=connection,
    )

    coordinator = PorscheConnectDataUpdateCoordinator(
        hass,
        config_entry=entry,
        controller=controller,
    )

    # The coordinator turns API errors into ConfigEntryAuthFailed (reauth) or
    # UpdateFailed, which the first refresh raises as ConfigEntryNotReady.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Migrate pre-VIN unique_ids before the platforms create entities, so an
    # upgrade from an older version reuses existing entities instead of
    # orphaning them as duplicates.
    await _async_migrate_entity_unique_ids(hass, entry, coordinator.vehicles)

    await hass.config_entries.async_forward_entry_setups(
        entry,
        list(PLATFORMS),
    )

    # Deep-copy so the persisted snapshot is decoupled from the live token the
    # coordinator keeps mutating in place — otherwise the change-detection in
    # _async_update_data can never see a difference and would stop persisting
    # rotated tokens.
    async_save_token(hass, entry, copy.deepcopy(controller.token))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> bool:
    """Unload a config entry.

    The domain-wide services stay registered: they are set up once in
    async_setup, and a reload (e.g. after reauth) does not register them again.
    """
    return await hass.config_entries.async_unload_platforms(
        entry,
        list(PLATFORMS),
    )


async def async_remove_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> None:
    """Forget the HTTP client of a deleted entry."""
    hass.data.get(_ENTRY_CLIENTS, {}).pop(entry.entry_id, None)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Remove a device from a config entry.

    Allowed when the device's VIN is no longer present in the account's
    vehicle list (e.g. the car was sold, returned, or otherwise unpaired in
    the Porsche app).
    """
    coordinator = getattr(config_entry, "runtime_data", None)
    if coordinator is None:
        # Entry not loaded: the account cannot be checked. A car still on it
        # comes back at the next setup.
        return True
    known_vins = {vehicle.vin for vehicle in coordinator.vehicles}
    device_vins = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }
    # If none of the device's VINs are still active on the account, the user
    # is free to remove it.
    return device_vins.isdisjoint(known_vins)
