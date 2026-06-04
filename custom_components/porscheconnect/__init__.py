"""The Porsche Connect integration."""

from __future__ import annotations

import copy
import logging
import operator
from datetime import timedelta
from functools import reduce

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from pyporscheconnectapi.account import PorscheConnectAccount
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

HTTP_UNAUTHORIZED = 401

_AUTH_FAILED_MSG = "Authentication failed for Porsche Connect"
_API_ERROR_MSG = "Error communicating with Porsche Connect API"

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


def get_from_dict(datadict, keystring):
    """Safely get value from dict."""
    maplist = keystring.split(".")

    def safe_getitem(latest_value, key):
        if latest_value is None or key not in latest_value:
            return None
        return operator.getitem(latest_value, key)

    return reduce(safe_getitem, maplist, datadict)


@callback
def _async_save_token(hass, config_entry, access_token):
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_ACCESS_TOKEN: access_token,
        },
    )


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


async def _async_migrate_entity_unique_ids(
    hass: HomeAssistant,
    entry: PorscheConnectConfigEntry,
    vehicles: list[PorscheVehicle],
) -> None:
    """Migrate pre-VIN unique_ids (``{name}-{key}``) to the VIN scheme.

    Older releases keyed entities off the (mutable) vehicle name; entities are
    now keyed off the immutable VIN. Rewrite the registry in place so an upgrade
    reuses the existing entities instead of orphaning them as duplicates.
    """
    prefixes = [
        (f"{vehicle.data['name']}-", f"{vehicle.vin}-")
        for vehicle in vehicles
        if vehicle.data.get("name") and vehicle.vin
    ]
    if not prefixes:
        return

    @callback
    def _migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        for old_prefix, new_prefix in prefixes:
            if entity_entry.unique_id.startswith(old_prefix):
                suffix = entity_entry.unique_id[len(old_prefix):]
                return {"new_unique_id": f"{new_prefix}{suffix}"}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def async_setup_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> bool:
    """Set up this integration using UI."""
    async_client = get_async_client(hass)
    connection = Connection(
        entry.data.get("email"),
        entry.data.get("password"),
        async_client=async_client,
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

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        # The coordinator already wrapped the auth error appropriately; let HA
        # surface the reauth flow.
        raise
    except PorscheWrongCredentialsError as exc:
        msg = f"{_AUTH_FAILED_MSG}: {exc}"
        raise ConfigEntryAuthFailed(msg) from exc
    except PorscheExceptionError as exc:
        if _is_auth_error(exc):
            msg = f"{_AUTH_FAILED_MSG}: {exc}"
            raise ConfigEntryAuthFailed(msg) from exc
        msg = f"{_API_ERROR_MSG}: {exc}"
        raise ConfigEntryNotReady(msg) from exc

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

    # Track that this entry is using our domain-global services so that the
    # last unload can release them. We keep this in hass.data only as a small
    # bookkeeping set; entity state lives on entry.runtime_data.
    hass.data.setdefault(DOMAIN, set()).add(entry.entry_id)

    return True


class PorscheConnectDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Porsche data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, controller):
        """Initialise the controller."""
        self.controller = controller
        self.vehicles = []
        self.hass = hass

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

    def get_vehicle_data_leaf(self, vehicle, node, leaf):
        """Get data value leaf from dict."""
        return get_from_dict(get_from_dict(vehicle.data, node), leaf)

    # Backwards-compat alias (historic typo kept so external references don't
    # break mid-upgrade). New code should use get_vehicle_data_leaf.
    get_vechicle_data_leaf = get_vehicle_data_leaf

    async def _async_fetch_pictures(self, vehicle: PorscheVehicle) -> None:
        """Fetch picture locations best-effort — cosmetic, must not fail a cycle."""
        try:
            await vehicle.get_picture_locations()
        except PorscheExceptionError as exc:
            _LOGGER.debug(
                "Could not fetch picture locations for %s: %s", vehicle.vin, exc,
            )

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            if len(self.vehicles) == 0:
                self.vehicles = await self.controller.get_vehicles()

                for vehicle in self.vehicles:
                    await vehicle.get_stored_overview()
                    # Pictures are cosmetic — best-effort, must not abort setup.
                    await self._async_fetch_pictures(vehicle)

            else:
                async with async_timeout.timeout(30):
                    for vehicle in self.vehicles:
                        await vehicle.get_stored_overview()
                        # Retry pictures if the initial fetch came back empty
                        # (e.g. a transient failure at setup); the image platform
                        # adds the entities once they appear.
                        if not vehicle.picture_locations:
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
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        list(PLATFORMS),
    )

    if unload_ok:
        tracked: set[str] = hass.data.get(DOMAIN, set())
        tracked.discard(entry.entry_id)

        # If this was the last entry, release the domain-global services so
        # subsequent reloads don't accumulate stale registrations.
        if not tracked:
            from .services import async_unload_services

            async_unload_services(hass)
            hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: PorscheConnectConfigEntry
) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


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
        self._vin = vehicle.vin

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
