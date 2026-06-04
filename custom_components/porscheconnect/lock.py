"""Support for Porsche lock entity."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import CONF_DEFAULT_CODE, LockEntity
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pyporscheconnectapi.vehicle import PorscheVehicle

from . import (
    PorscheBaseEntity,
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Porsche Connect lock entity from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: set[str] = set()

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheLock] = []
        for vehicle in coordinator.vehicles:
            if vehicle.vin in known_vins:
                continue
            known_vins.add(vehicle.vin)
            new_entities.append(PorscheLock(coordinator, vehicle))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheLock(PorscheBaseEntity, LockEntity):
    """Representation of a Porsche vehicle lock."""

    _attr_translation_key = "lock"

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator, vehicle)

        self._attr_unique_id = f"{self._vin}-lock"
        self.door_lock_state_available = vehicle.has_remote_services

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the vehicle."""
        try:
            await self.vehicle.remote_services.lock_vehicle()
        except PorscheExceptionError as ex:
            self._attr_is_locked = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lock_failed",
                translation_placeholders={
                    "vin": self.vehicle.vin,
                    "error": str(ex),
                },
            ) from ex
        finally:
            self.coordinator.async_update_listeners()

    async def async_unlock(self, **kwargs: dict) -> None:
        """Unlock the vehicle."""
        pin = kwargs.get("code")

        if pin is None:
            lock_options = self.registry_entry.options.get(LOCK_DOMAIN) or {}
            pin = lock_options.get(CONF_DEFAULT_CODE)

        if pin:
            try:
                await self.vehicle.remote_services.unlock_vehicle(pin)
            except PorscheExceptionError as ex:
                self._attr_is_locked = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="unlock_failed",
                    translation_placeholders={
                        "vin": self.vehicle.vin,
                        "error": str(ex),
                    },
                ) from ex
            finally:
                self.coordinator.async_update_listeners()
        else:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="pin_code_missing",
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Updating lock data of %s", self.vehicle.vin)
        self._attr_is_locked = self.vehicle.vehicle_locked

        super()._handle_coordinator_update()
