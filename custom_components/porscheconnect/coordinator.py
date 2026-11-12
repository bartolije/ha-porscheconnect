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
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
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

# Picture locations are cosmetic: when the API has none for a car, ask again
# once a day rather than on every refresh of a rate-limited API.
_PICTURE_RETRY_INTERVAL = timedelta(days=1)

# One refresh: the vehicle list, then one overview per car (seconds).
_UPDATE_TIMEOUT = 60

# Type alias for the runtime data attached to each config entry.
PorscheConnectConfigEntry = ConfigEntry["PorscheConnectDataUpdateCoordinator"]


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
        # Every car seen since setup: entities keep their vehicle object, so a
        # car that comes back to the account must get the same one.
        self._seen_vehicles: dict[str, PorscheVehicle] = {}
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            async with asyncio.timeout(_UPDATE_TIMEOUT):
                await self._async_refresh_vehicle_list()
                for vehicle in self.vehicles:
                    await vehicle.get_stored_overview()
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
            return {}
