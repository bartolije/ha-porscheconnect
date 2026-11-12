"""Base entity for the Porsche Connect integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DOMAIN
from .coordinator import PorscheConnectDataUpdateCoordinator


class PorscheBaseEntity(CoordinatorEntity[PorscheConnectDataUpdateCoordinator]):
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
            model_id=(vehicle.data.get("modelType") or {}).get("code"),
            manufacturer="Porsche",
            serial_number=self._vin,
        )

    @property
    def available(self) -> bool:
        """Unavailable once the car has left the account."""
        return super().available and self.vehicle in self.coordinator.vehicles

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()
