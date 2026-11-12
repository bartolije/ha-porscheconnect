"""Device tracker for Porsche vehicles."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyporscheconnectapi.vehicle import PorscheVehicle

from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)
from .entity import PorscheBaseEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the device tracker from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: dict[str, object] = {}

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheDeviceTracker] = []
        for vehicle in coordinator.vehicles:
            if known_vins.get(vehicle.vin) is vehicle:
                continue
            # Not marked as known while in privacy mode, so the tracker is
            # added on a later refresh once privacy mode is turned off.
            if vehicle.privacy_mode:
                _LOGGER.debug(
                    "Vehicle is in privacy mode with location tracking disabled"
                )
                continue
            known_vins[vehicle.vin] = vehicle
            new_entities.append(PorscheDeviceTracker(coordinator, vehicle))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheDeviceTracker(PorscheBaseEntity, TrackerEntity):
    """Class describing Porsche Connect device tracker."""

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator, vehicle)

        self._attr_unique_id = self._vin
        # The device is already named after the car: a name here would double it.
        self._attr_name = None
        self._attr_translation_key = "location"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        data: dict[str, Any] = {"updated_at": self.vehicle.location_updated_at}
        if self.vehicle.location[2] is not None:
            data["direction"] = float(self.vehicle.location[2])
        return data

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        if self.vehicle.location[0] is not None:
            return float(self.vehicle.location[0])
        return None

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        if self.vehicle.location[1] is not None:
            return float(self.vehicle.location[1])
        return None

    @property
    def source_type(self) -> SourceType:
        """Return the source type, eg gps or router, of the device."""
        return SourceType.GPS
