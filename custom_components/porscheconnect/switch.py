"""Support for the Porsche Connect switch entities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pyporscheconnectapi.vehicle import PorscheVehicle

from .const import DOMAIN
from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)
from .entity import PorscheBaseEntity

# One command at a time: the car handles them in sequence.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class PorscheSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Porsche Connect switch entities."""

    value_fn: Callable[[PorscheVehicle], bool | None]
    remote_service_on: Callable[[PorscheVehicle], Coroutine[Any, Any, Any]]
    remote_service_off: Callable[[PorscheVehicle], Coroutine[Any, Any, Any]]
    is_available: Callable[[PorscheVehicle], bool] = lambda _: False


SWITCH_TYPES: list[PorscheSwitchEntityDescription] = [
    PorscheSwitchEntityDescription(
        key="climatise",
        translation_key="climatise",
        # Same command as the climate entity, which also sets the temperature.
        entity_registry_enabled_default=False,
        is_available=lambda v: v.has_remote_climatisation and v.has_remote_services,
        value_fn=lambda v: v.remote_climatise_on,
        remote_service_on=lambda v: v.remote_services.climatise_on(),
        remote_service_off=lambda v: v.remote_services.climatise_off(),
    ),
    PorscheSwitchEntityDescription(
        key="direct_charging",
        translation_key="direct_charging",
        is_available=lambda v: v.has_direct_charge and v.has_remote_services,
        value_fn=lambda v: v.direct_charge_on,
        remote_service_on=lambda v: v.remote_services.direct_charge_on(),
        remote_service_off=lambda v: v.remote_services.direct_charge_off(),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Porsche switch from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: dict[str, object] = {}

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheSwitch] = []
        for vehicle in coordinator.vehicles:
            if known_vins.get(vehicle.vin) is vehicle:
                continue
            known_vins[vehicle.vin] = vehicle
            new_entities.extend(
                PorscheSwitch(coordinator, vehicle, description)
                for description in SWITCH_TYPES
                if description.is_available(vehicle)
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheSwitch(PorscheBaseEntity, SwitchEntity):
    """Representation of Porsche switch."""

    entity_description: PorscheSwitchEntityDescription

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
        description: PorscheSwitchEntityDescription,
    ) -> None:
        """Initialize an Porsche Switch."""
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{self._vin}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the entity value to represent the entity state."""
        return self.entity_description.value_fn(self.vehicle)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            await self.entity_description.remote_service_on(self.vehicle)
        except PorscheExceptionError as ex:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_service_failed",
                translation_placeholders={
                    "service": f"{self.entity_description.key}_on",
                    "vin": self.vehicle.vin,
                    "error": str(ex),
                },
            ) from ex

        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            await self.entity_description.remote_service_off(self.vehicle)
        except PorscheExceptionError as ex:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_service_failed",
                translation_placeholders={
                    "service": f"{self.entity_description.key}_off",
                    "vin": self.vehicle.vin,
                    "error": str(ex),
                },
            ) from ex

        self.coordinator.async_update_listeners()
