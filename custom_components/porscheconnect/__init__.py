"""The Porsche Connect integration."""

from __future__ import annotations

import asyncio
import copy
import logging
import operator
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import reduce
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util
from pyporscheconnectapi.account import PorscheConnectAccount
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS, TRANSIENT_AUTH_FIELDS

if TYPE_CHECKING:
    import httpx2

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

HTTP_UNAUTHORIZED = 401

_AUTH_FAILED_MSG = "Authentication failed for Porsche Connect"

# Entity keys of the upstream integration (CJNE/ha-porscheconnect) that are
# named differently here, so that switching from it keeps the entities.
_UPSTREAM_KEY_RENAMES = {
    "main_service_range": "main_service_distance",
    "oil_service_range": "oil_service_distance",
    "intermediate_service_range": "intermediate_service_distance",
}

# Picture locations are cosmetic: when the API has none for a car, ask again
# once a day rather than on every refresh of a rate-limited API.
_PICTURE_RETRY_INTERVAL = timedelta(days=1)

# Type alias for the runtime data attached to each config entry.
PorscheConnectConfigEntry = ConfigEntry["PorscheConnectDataUpdateCoordinator"]

# This integration is configured exclusively through the UI config flow and has
# no YAML configuration; declaring this satisfies the hassfest CONFIG_SCHEMA
# check for integrations that implement async_setup.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _is_auth_error(exc: PorscheExceptionError) -> bool:
    """Return True if the API error should trigger a reauth flow."""
    # A captcha challenge can only be answered through the (re)auth flow, so a
    # captcha required mid-polling must surface as a reauth, not a plain retry.
    if isinstance(exc, (PorscheWrongCredentialsError, PorscheCaptchaRequiredError)):
        return True
    return getattr(exc, "code", None) == HTTP_UNAUTHORIZED


def get_from_dict(datadict: dict[str, Any] | None, keystring: str) -> Any:
    """Safely get value from dict."""
    maplist = keystring.split(".")

    def safe_getitem(latest_value: Any, key: str) -> Any:
        if latest_value is None or key not in latest_value:
            return None
        return operator.getitem(latest_value, key)

    return reduce(safe_getitem, maplist, datadict)


def has_measurement(key: str) -> Callable[[PorscheVehicle], bool]:
    """Return a check that the vehicle reports the given measurement."""
    return lambda vehicle: key in vehicle.data


@callback
def _async_save_token(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    access_token: dict[str, Any],
) -> None:
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_ACCESS_TOKEN: access_token,
        },
    )


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
                key = entity_entry.unique_id[len(old_prefix):]
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
        async_client=async_create_porsche_client(hass),
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
    _async_save_token(hass, entry, copy.deepcopy(controller.token))

    return True


class PorscheConnectDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Porsche data."""

    config_entry: PorscheConnectConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        controller: PorscheConnectAccount,
    ) -> None:
        """Initialise the controller."""
        self.controller = controller
        self.vehicles: list[PorscheVehicle] = []
        self.hass = hass
        self._picture_attempts: dict[str, datetime] = {}

        scan_interval = timedelta(
            seconds=config_entry.options.get(
                CONF_SCAN_INTERVAL,
                config_entry.data.get(
                    CONF_SCAN_INTERVAL,
                    SCAN_INTERVAL.total_seconds(),
                ),
            ),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=config_entry,
        )

    def get_vehicle_data_leaf(
        self, vehicle: PorscheVehicle, node: str | None, leaf: str | None,
    ) -> Any:
        """Get data value leaf from dict."""
        if node is None or leaf is None:
            return None
        return get_from_dict(get_from_dict(vehicle.data, node), leaf)

    async def _async_fetch_pictures(self, vehicle: PorscheVehicle) -> None:
        """Fetch picture locations best-effort — cosmetic, must not fail a cycle."""
        self._picture_attempts[vehicle.vin] = dt_util.utcnow()
        try:
            await vehicle.get_picture_locations()
        except PorscheExceptionError as exc:
            _LOGGER.debug(
                "Could not fetch picture locations for %s: %s", vehicle.vin, exc,
            )

    def _picture_retry_due(self, vehicle: PorscheVehicle) -> bool:
        """Return True if empty picture locations should be fetched again."""
        if vehicle.picture_locations:
            return False
        last = self._picture_attempts.get(vehicle.vin)
        return last is None or dt_util.utcnow() - last >= _PICTURE_RETRY_INTERVAL

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            if len(self.vehicles) == 0:
                self.vehicles = await self.controller.get_vehicles()

                for vehicle in self.vehicles:
                    await vehicle.get_stored_overview()
                    # Pictures are cosmetic — best-effort, must not abort setup.
                    await self._async_fetch_pictures(vehicle)

            else:
                async with asyncio.timeout(30):
                    for vehicle in self.vehicles:
                        await vehicle.get_stored_overview()
                        # Retry pictures if the initial fetch came back empty
                        # (e.g. a transient failure at setup); the image platform
                        # adds the entities once they appear.
                        if self._picture_retry_due(vehicle):
                            await self._async_fetch_pictures(vehicle)

        except PorscheWrongCredentialsError as exc:
            msg = f"{_AUTH_FAILED_MSG}: {exc}"
            raise ConfigEntryAuthFailed(msg) from exc
        except PorscheExceptionError as exc:
            if _is_auth_error(exc):
                msg = f"{_AUTH_FAILED_MSG}: {exc}"
                raise ConfigEntryAuthFailed(msg) from exc
            msg = f"Error communicating with API: {exc}"
            raise UpdateFailed(msg) from exc
        else:
            # Only persist the token when it actually changed — the refresh
            # rotates it occasionally, but most cycles reuse the same one and an
            # unconditional write churns the config entry storage every poll.
            current_token = self.controller.token
            stored_token = self.config_entry.data.get(CONF_ACCESS_TOKEN)
            if current_token and current_token != stored_token:
                _async_save_token(
                    hass=self.hass,
                    config_entry=self.config_entry,
                    access_token=copy.deepcopy(current_token),
                )
            return {}


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
    coordinator = config_entry.runtime_data
    known_vins = {vehicle.vin for vehicle in coordinator.vehicles}
    device_vins = {
        identifier[1]
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    }
    # If none of the device's VINs are still active on the account, the user
    # is free to remove it.
    return device_vins.isdisjoint(known_vins)


class PorscheBaseEntity(CoordinatorEntity):
    """Common base for entities."""

    coordinator: PorscheConnectDataUpdateCoordinator
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)

        self.vehicle = vehicle
        # Cache the VIN locally so unique_ids and device identifiers stay
        # stable even if the user renames the car in the Porsche app.
        self._vin: str = vehicle.vin

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._vin)},
            name=vehicle.data.get("name") or vehicle.model_name,
            model=vehicle.data.get("modelName"),
            manufacturer="Porsche",
            serial_number=self._vin,
        )

    @property
    def vin(self) -> str:
        """Get the VIN (vehicle identification number) of the vehicle."""
        return self._vin

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Let Home Assistant rename the entity in place.

        Nothing here depends on the entity_id, so there is nothing to re-key.
        """
        super().async_entity_id_changed(old_entity_id)
