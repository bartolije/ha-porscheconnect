"""Support for Porsche Connect button entities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pyporscheconnectapi.vehicle import PorscheVehicle

from . import (
    PorscheBaseEntity,
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)
from .const import DOMAIN

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class PorscheButtonEntityDescription(ButtonEntityDescription):
    """Class describing Porsche Connect button entities."""

    remote_function: Callable[[PorscheVehicle], Coroutine[Any, Any, Any]]
    is_available: Callable[[PorscheVehicle], bool] = lambda v: v.has_remote_services


BUTTON_TYPES: tuple[PorscheButtonEntityDescription, ...] = (
    PorscheButtonEntityDescription(
        key="get_current_overview",
        translation_key="get_current_overview",
        remote_function=lambda v: v.get_current_overview(),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PorscheButtonEntityDescription(
        key="flash_indicators",
        translation_key="flash_indicators",
        remote_function=lambda v: v.remote_services.flash_indicators(),
    ),
    PorscheButtonEntityDescription(
        key="honk_and_flash_indicators",
        translation_key="honk_and_flash_indicators",
        remote_function=lambda v: v.remote_services.honk_and_flash_indicators(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Porsche buttons from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: set[str] = set()

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheButton] = []
        for vehicle in coordinator.vehicles:
            if vehicle.vin in known_vins:
                continue
            known_vins.add(vehicle.vin)
            new_entities.extend(
                PorscheButton(coordinator, vehicle, description)
                for description in BUTTON_TYPES
                if description.is_available(vehicle)
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheButton(PorscheBaseEntity, ButtonEntity):
    """Representation of a Porsche Connect button."""

    entity_description: PorscheButtonEntityDescription

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
        description: PorscheButtonEntityDescription,
    ) -> None:
        """Initialize Porsche Connect button."""
        super().__init__(coordinator, vehicle)
        self.entity_description = description
        self._attr_unique_id = f"{vehicle.vin}-{description.key}"

    async def async_press(self) -> None:
        """Press the button."""
        try:
            await self.entity_description.remote_function(self.vehicle)
        except PorscheExceptionError as ex:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_service_failed",
                translation_placeholders={
                    "service": self.entity_description.key,
                    "vin": self.vehicle.vin,
                    "error": str(ex),
                },
            ) from ex

        self.coordinator.async_update_listeners()
