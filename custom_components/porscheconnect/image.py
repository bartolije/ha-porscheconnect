"""Porsche Connect image platform."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.image import Image, ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util
from pyporscheconnectapi.vehicle import PorscheVehicle

from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)
from .entity import PorscheBaseEntity

CONTENT_TYPE = "image/png"

PARALLEL_UPDATES = 0


@dataclass(frozen=True)
class PorscheImageEntityDescription(ImageEntityDescription):
    """Describes a Porsche image entity."""

    view: str = ""


# Only the side view is enabled by default — it makes the best "hero" image
# for a dashboard. The other four angles are opt-in so we don't ship five
# image entities per car on first install.
IMAGE_TYPES: list[PorscheImageEntityDescription] = [
    PorscheImageEntityDescription(
        key="front_view",
        translation_key="front_view",
        view="frontView",
        entity_registry_enabled_default=False,
    ),
    PorscheImageEntityDescription(
        key="side_view",
        translation_key="side_view",
        view="sideView",
    ),
    PorscheImageEntityDescription(
        key="rear_view",
        translation_key="rear_view",
        view="rearView",
        entity_registry_enabled_default=False,
    ),
    PorscheImageEntityDescription(
        key="rear_top_view",
        translation_key="rear_top_view",
        view="rearTopView",
        entity_registry_enabled_default=False,
    ),
    PorscheImageEntityDescription(
        key="top_view",
        translation_key="top_view",
        view="topView",
        entity_registry_enabled_default=False,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Porsche Connect image entity from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: dict[str, object] = {}

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheImage] = []
        for vehicle in coordinator.vehicles:
            if known_vins.get(vehicle.vin) is vehicle:
                continue
            vehicle_images = [
                PorscheImage(hass, coordinator, vehicle, description)
                for description in IMAGE_TYPES
                if description.view in vehicle.picture_locations
            ]
            # Only mark the VIN handled once pictures actually arrived, so a
            # later refresh that finally populates picture_locations (e.g. after
            # a transient failure at setup) can still add the image entities.
            if vehicle_images:
                known_vins[vehicle.vin] = vehicle
                new_entities.extend(vehicle_images)
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheImage(PorscheBaseEntity, ImageEntity):
    """Representation of an image entity."""

    entity_description: PorscheImageEntityDescription

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
        description: PorscheImageEntityDescription,
    ) -> None:
        """Initialize the image entity."""
        super().__init__(coordinator, vehicle)
        ImageEntity.__init__(self, hass)

        self.entity_description = description

        self._attr_content_type = CONTENT_TYPE
        self._attr_unique_id = f"{self._vin}-{description.key}"
        self._attr_image_url = vehicle.picture_locations[description.view]
        self._attr_image_last_updated = dt_util.utcnow()

    async def _async_load_image_from_url(self, url: str) -> Image | None:
        """Load an image by url."""
        if response := await self._fetch_url(url):
            image_data = response.content
            return Image(
                content=image_data,
                content_type=CONTENT_TYPE,
            )
        return None
