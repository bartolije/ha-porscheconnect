"""Support for the Porsche Connect binary sensors."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyporscheconnectapi.vehicle import PorscheVehicle

from . import (
    PorscheBaseEntity,
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True)
class PorscheBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class describing Porsche Connect binary sensor entities."""

    measurement_node: str | None = None
    measurement_leaf: str | None = None
    value_fn: Callable[[PorscheVehicle], bool] | None = None
    attr_fn: Callable[[PorscheVehicle], dict[str, str]] | None = None
    is_available: Callable[[PorscheVehicle], bool] = lambda v: v.has_porsche_connect


SENSOR_TYPES: list[PorscheBinarySensorEntityDescription] = [
    PorscheBinarySensorEntityDescription(
        # Reflects an account-side configuration flag rather than live
        # vehicle state — useful when debugging "why are my services not
        # working", but noisy on a default dashboard.
        name="Remote access",
        key="remote_access",
        translation_key="remote_access",
        measurement_node="REMOTE_ACCESS_AUTHORIZATION",
        measurement_leaf="isEnabled",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Capability gate: the API drops this measurement (NOT_SUPPORTED) on
        # vehicles that don't offer it (e.g. most combustion cars), which
        # otherwise surfaces a permanent "Unknown" entity. Mirror the
        # OPEN_STATE_* gate: no key in data == not available.
        is_available=lambda v: "REMOTE_ACCESS_AUTHORIZATION" in v.data,
    ),
    PorscheBinarySensorEntityDescription(
        name="Privacy mode",
        key="privacy_mode",
        translation_key="privacy_mode",
        measurement_node="GLOBAL_PRIVACY_MODE",
        measurement_leaf="isEnabled",
        device_class=None,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PorscheBinarySensorEntityDescription(
        name="Parking brake",
        key="parking_brake",
        translation_key="parking_brake",
        measurement_node="PARKING_BRAKE",
        measurement_leaf="isOn",
        device_class=None,
        # Capability gate — see remote_access above.
        is_available=lambda v: "PARKING_BRAKE" in v.data,
    ),
    PorscheBinarySensorEntityDescription(
        name="Parking light",
        key="parking_light",
        translation_key="parking_light",
        measurement_node="PARKING_LIGHT",
        measurement_leaf="isOn",
        device_class=BinarySensorDeviceClass.LIGHT,
        # Capability gate — see remote_access above.
        is_available=lambda v: "PARKING_LIGHT" in v.data,
    ),
    PorscheBinarySensorEntityDescription(
        name="Doors and lids",
        key="doors_and_lids",
        translation_key="doors_and_lids",
        value_fn=lambda v: not v.vehicle_closed,
        attr_fn=lambda v: v.doors_and_lids,
        device_class=BinarySensorDeviceClass.OPENING,
    ),
    PorscheBinarySensorEntityDescription(
        name="Tire pressure status",
        key="tire_pressure_status",
        translation_key="tire_pressure_status",
        value_fn=lambda v: not v.tire_pressure_status,
        attr_fn=lambda v: v.tire_pressures,
        is_available=lambda v: v.has_tire_pressure_monitoring,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


# Per-component OPEN_STATE_* binary sensors (doors, lids, windows, sunroofs,
# charge flaps, convertible top, spoiler, service flap). The Porsche API
# only includes the `OPEN_STATE_*` key for components the vehicle physically
# has — so we gate each sensor on the data containing its key. The aggregated
# `doors_and_lids` sensor above is kept enabled-by-default; these per-part
# sensors are enabled-by-default for primary parts (doors, lids, windows,
# sunroofs, charge flaps) and disabled for cosmetic ones (spoiler) /
# maintenance-only ones (service flap) — see _OPEN_STATE_CONFIG below.
@dataclass(frozen=True)
class _OpenStateConfig:
    """Display config for a single OPEN_STATE_* binary sensor."""

    api_suffix: str  # the part after "OPEN_STATE_"
    key: str  # HA entity key
    device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OPENING
    enabled_by_default: bool = True
    entity_category: EntityCategory | None = None


_DOOR = BinarySensorDeviceClass.DOOR
_WINDOW = BinarySensorDeviceClass.WINDOW
_DIAG = EntityCategory.DIAGNOSTIC

_OPEN_STATE_CONFIG: list[_OpenStateConfig] = [
    # Doors — primary user-facing state.
    _OpenStateConfig("DOOR_FRONT_LEFT", "door_front_left", _DOOR),
    _OpenStateConfig("DOOR_FRONT_RIGHT", "door_front_right", _DOOR),
    _OpenStateConfig("DOOR_REAR_LEFT", "door_rear_left", _DOOR),
    _OpenStateConfig("DOOR_REAR_RIGHT", "door_rear_right", _DOOR),
    # Lids: front (frunk) + rear (trunk/boot).
    _OpenStateConfig("LID_FRONT", "lid_front"),
    _OpenStateConfig("LID_REAR", "lid_rear"),
    # Windows.
    _OpenStateConfig("WINDOW_FRONT_LEFT", "window_front_left", _WINDOW),
    _OpenStateConfig("WINDOW_FRONT_RIGHT", "window_front_right", _WINDOW),
    _OpenStateConfig("WINDOW_REAR_LEFT", "window_rear_left", _WINDOW),
    _OpenStateConfig("WINDOW_REAR_RIGHT", "window_rear_right", _WINDOW),
    # Sunroof (Cayenne, Panamera) + rear sunroof (some Panamera).
    _OpenStateConfig("SUNROOF", "sunroof", _WINDOW),
    _OpenStateConfig("SUNROOF_REAR", "sunroof_rear", _WINDOW),
    # Convertible top (718 Boxster / 911 Cabriolet / 911 Targa).
    _OpenStateConfig("TOP", "convertible_top", _WINDOW),
    # Charge flaps (BEV/PHEV — left and right depending on model).
    _OpenStateConfig("CHARGE_FLAP_LEFT", "charge_flap_left"),
    _OpenStateConfig("CHARGE_FLAP_RIGHT", "charge_flap_right"),
    # Active aero spoiler (Taycan / 911 etc.) — diagnostic, cosmetic.
    _OpenStateConfig(
        "SPOILER", "spoiler",
        enabled_by_default=False, entity_category=_DIAG,
    ),
    # Service flap (washer fluid / oil access) — maintenance-only, disabled.
    _OpenStateConfig(
        "SERVICE_FLAP", "service_flap",
        enabled_by_default=False, entity_category=_DIAG,
    ),
]


def _open_state_descriptions() -> list[PorscheBinarySensorEntityDescription]:
    """Materialise the OPEN_STATE_* config table into entity descriptions."""
    descriptions: list[PorscheBinarySensorEntityDescription] = []
    for cfg in _OPEN_STATE_CONFIG:
        api_key = f"OPEN_STATE_{cfg.api_suffix}"
        descriptions.append(
            PorscheBinarySensorEntityDescription(
                key=cfg.key,
                translation_key=cfg.key,
                measurement_node=api_key,
                measurement_leaf="isOpen",
                device_class=cfg.device_class,
                entity_category=cfg.entity_category,
                entity_registry_enabled_default=cfg.enabled_by_default,
                # Capability gate: the API only includes the key for
                # components the car physically has. Mirrors the climate
                # zones fix (#292): missing key == not available.
                is_available=lambda v, _k=api_key: _k in v.data,
            ),
        )
    return descriptions


SENSOR_TYPES.extend(_open_state_descriptions())


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: set[str] = set()

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheBinarySensor] = []
        for vehicle in coordinator.vehicles:
            if vehicle.vin in known_vins:
                continue
            known_vins.add(vehicle.vin)
            new_entities.extend(
                PorscheBinarySensor(coordinator, vehicle, description)
                for description in SENSOR_TYPES
                if description.is_available(vehicle)
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheBinarySensor(BinarySensorEntity, PorscheBaseEntity):
    """Representation of a Porsche binary sensor."""

    entity_description: PorscheBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
        description: PorscheBinarySensorEntityDescription,
    ) -> None:
        """Initialize of the sensor."""
        super().__init__(coordinator, vehicle)

        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{self._vin}-{description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.entity_description.value_fn:
            self._attr_is_on = self.entity_description.value_fn(self.vehicle)
        else:
            self._attr_is_on = self.coordinator.get_vehicle_data_leaf(
                self.vehicle,
                self.entity_description.measurement_node,
                self.entity_description.measurement_leaf,
            )

        _LOGGER.debug(
            "Updating binary sensor '%s' of %s with state '%s'",
            self.entity_description.key,
            self.vehicle.data["name"],
            self._attr_is_on,
            # state,
        )

        if self.entity_description.attr_fn:
            self._attr_extra_state_attributes = self.entity_description.attr_fn(
                self.vehicle,
            )

        super()._handle_coordinator_update()
