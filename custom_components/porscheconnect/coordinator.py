"""Data update coordinator for the Porsche Connect integration."""

from __future__ import annotations

import asyncio
import copy
import logging
import operator
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import reduce
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pyporscheconnectapi.account import PorscheConnectAccount
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheLoginThrottledError,
    PorscheWrongCredentialsError,
)
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

HTTP_UNAUTHORIZED = 401
# Mobile access disabled, account locked: Porsche will keep refusing until the
# owner acts, so retrying is pointless.
_HTTP_ACCOUNT_BLOCKED = (405, 423)

# Picture locations are cosmetic: when the API has none for a car, ask again
# once a day rather than on every refresh of a rate-limited API.
_PICTURE_RETRY_INTERVAL = timedelta(days=1)

# A car missing from this many refreshes in a row has left the account: one
# odd answer from Porsche must not delete a device and its entity settings.
_STALE_AFTER_REFRESHES = 2

# One refresh: the vehicle list, then one overview per car (seconds).
_UPDATE_TIMEOUT = 60

type PorscheConnectConfigEntry = ConfigEntry[PorscheConnectDataUpdateCoordinator]


def _error_code(exc: PorscheExceptionError) -> int | str | None:
    """Return the HTTP status of an API error, when the library has one."""
    return getattr(exc, "code", None)


def _is_auth_error(exc: PorscheExceptionError) -> bool:
    """Return True if the API error should trigger a reauth flow."""
    # A captcha challenge can only be answered through the (re)auth flow, so a
    # captcha required mid-polling must surface as a reauth, not a plain retry.
    if isinstance(exc, (PorscheWrongCredentialsError, PorscheCaptchaRequiredError)):
        return True
    return _error_code(exc) == HTTP_UNAUTHORIZED


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
def async_save_token(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    access_token: dict[str, Any] | None,
) -> None:
    """Store the token in the config entry."""
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_ACCESS_TOKEN: access_token,
        },
    )


class PorscheConnectDataUpdateCoordinator(DataUpdateCoordinator[None]):
    """Class to manage fetching Porsche data."""

    config_entry: PorscheConnectConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: PorscheConnectConfigEntry,
        controller: PorscheConnectAccount,
    ) -> None:
        """Initialise the controller."""
        self.controller = controller
        self.vehicles: list[PorscheVehicle] = []
        # Every car seen since setup: entities keep their vehicle object, so a
        # car that comes back to the account must get the same one.
        self._seen_vehicles: dict[str, PorscheVehicle] = {}
        self._picture_attempts: dict[str, datetime] = {}
        self._missed_refreshes: dict[str, int] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=config_entry,
        )

    def get_vehicle_data_leaf(
        self,
        vehicle: PorscheVehicle,
        node: str | None,
        leaf: str | None,
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
                "Could not fetch picture locations for %s: %s",
                vehicle.vin,
                exc,
            )

    def _picture_retry_due(self, vehicle: PorscheVehicle) -> bool:
        """Return True if empty picture locations should be fetched again."""
        if vehicle.picture_locations:
            return False
        last = self._picture_attempts.get(vehicle.vin)
        return last is None or dt_util.utcnow() - last >= _PICTURE_RETRY_INTERVAL

    async def _async_refresh_vehicle_list(self) -> None:
        """Follow the account: add newly paired cars, drop the ones that left."""
        # get_vehicles(force_init=True) appends to the list the account holds.
        self.controller.vehicles = []
        listed = await self.controller.get_vehicles(force_init=True)
        for vehicle in listed:
            self._seen_vehicles.setdefault(vehicle.vin, vehicle)
        self.vehicles = [self._seen_vehicles[vehicle.vin] for vehicle in listed]
        self._async_remove_stale_devices({vehicle.vin for vehicle in listed})

    @callback
    def _async_remove_stale_devices(self, listed_vins: set[str]) -> None:
        """Remove the devices of cars that left the account."""
        device_registry = dr.async_get(self.hass)
        missed: dict[str, int] = {}
        for device in dr.async_entries_for_config_entry(
            device_registry, self.config_entry.entry_id
        ):
            vins = {value for domain, value in device.identifiers if domain == DOMAIN}
            if not vins or vins & listed_vins:
                continue
            vin = next(iter(vins))
            missed[vin] = self._missed_refreshes.get(vin, 0) + 1
            if missed[vin] < _STALE_AFTER_REFRESHES:
                continue
            del missed[vin]
            _LOGGER.info("Removing %s: it is no longer on the account", device.name)
            self.async_forget_vehicle(vin)
            device_registry.async_remove_device(device.id)
        self._missed_refreshes = missed

    @callback
    def async_forget_vehicle(self, vin: str) -> None:
        """Forget a car whose device is removed; back later, it is set up again."""
        self._seen_vehicles.pop(vin, None)
        ir.async_delete_issue(self.hass, DOMAIN, self._contract_issue_id(vin))

    def _contract_issue_id(self, vin: str) -> str:
        """Return the issue of one car of this entry."""
        return f"connect_inactive_{self.config_entry.entry_id}_{vin}"

    @callback
    def _async_update_contract_issue(self, vehicle: PorscheVehicle) -> None:
        """Tell the user when a car has no active Porsche Connect contract."""
        issue_id = self._contract_issue_id(vehicle.vin)
        if vehicle.has_porsche_connect:
            if ir.async_get(self.hass).async_get_issue(DOMAIN, issue_id):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                # Entities are created from what the car reports at setup: set
                # it up again now that the contract is back.
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            config_entry_id=self.config_entry.entry_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="connect_inactive",
            translation_placeholders={
                "vehicle": vehicle.data.get("name") or vehicle.model_name
            },
        )

    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint."""
        try:
            async with asyncio.timeout(_UPDATE_TIMEOUT):
                await self._async_refresh_vehicle_list()
                for vehicle in self.vehicles:
                    await vehicle.get_stored_overview()
                    self._async_update_contract_issue(vehicle)
                    # Pictures are cosmetic and best-effort: fetched at setup,
                    # then once a day while still empty; the image platform
                    # adds the entities once they appear.
                    if self._picture_retry_due(vehicle):
                        await self._async_fetch_pictures(vehicle)

        except PorscheLoginThrottledError as exc:
            # Too many logins: the password is fine, try again at the next refresh.
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="login_throttled",
            ) from exc
        except PorscheExceptionError as exc:
            if _is_auth_error(exc):
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="auth_failed",
                    translation_placeholders={"error": str(exc)},
                ) from exc
            if _error_code(exc) in _HTTP_ACCOUNT_BLOCKED:
                raise ConfigEntryError(
                    translation_domain=DOMAIN,
                    translation_key="account_blocked",
                    translation_placeholders={"error": str(exc)},
                ) from exc
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(exc)},
            ) from exc
        except TimeoutError as exc:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_timeout",
            ) from exc
        else:
            # Only persist the token when it actually changed — the refresh
            # rotates it occasionally, but most cycles reuse the same one and an
            # unconditional write churns the config entry storage every poll.
            current_token = self.controller.token
            stored_token = self.config_entry.data.get(CONF_ACCESS_TOKEN)
            if current_token and current_token != stored_token:
                async_save_token(
                    hass=self.hass,
                    config_entry=self.config_entry,
                    access_token=copy.deepcopy(current_token),
                )
