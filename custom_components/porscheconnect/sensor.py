"""Support for the Porsche Connect sensors."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTime,
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
class PorscheSensorEntityDescription(SensorEntityDescription):
    """Class describing Porsche Connect sensor entities."""

    measurement_node: str | None = None
    measurement_leaf: str | None = None
    # Custom extractor for values that don't live at a fixed 2-level path
    # (e.g. per-tire pressure deltas under TIRE_PRESSURE.<tire>.<field>).
    # When present, takes priority over measurement_node / _leaf.
    value_fn: Callable[[PorscheVehicle], float | int | str | None] | None = None
    is_available: Callable[[PorscheVehicle], bool] = lambda v: v.has_porsche_connect


def _tire_delta(tire: str) -> Callable[[PorscheVehicle], float | None]:
    """Return a `value_fn` that pulls `TIRE_PRESSURE.<tire>.differenceBar`.

    Used for the four per-tire pressure deviation sensors. The Porsche
    API exposes a per-tire `differenceBar` (positive = over-pressure,
    negative = under-pressure) relative to the OEM target — same source
    the existing `tire_pressure_status` binary sensor reduces to a
    single PROBLEM bool. A captured tire payload looks like:

        {"frontLeftTire": {"differenceBar": 0.05}, ...}
    """
    def _extract(v: PorscheVehicle) -> float | None:
        tp = v.tire_pressures or {}
        leaf = tp.get(tire)
        if not isinstance(leaf, dict):
            return None
        delta = leaf.get("differenceBar")
        return float(delta) if isinstance(delta, (int, float)) else None
    return _extract


SENSOR_TYPES: list[PorscheSensorEntityDescription] = [
    PorscheSensorEntityDescription(
        key="charging_target",
        translation_key="charging_target",
        measurement_node="CHARGING_SUMMARY",
        measurement_leaf="minSoC",
        device_class=None,
        native_unit_of_measurement=PERCENTAGE,
        state_class=None,
        suggested_display_precision=0,
        icon="mdi:battery-high",
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="charging_status",
        translation_key="charging_status",
        measurement_node="CHARGING_SUMMARY",
        measurement_leaf="status",
        icon="mdi:battery-charging",
        device_class=SensorDeviceClass.ENUM,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        # The kph charging rate duplicates the more useful kW power reading
        # below — leave it off by default so users opt-in if they actually
        # want both views.
        key="charging_rate",
        translation_key="charging_rate",
        measurement_node="CHARGING_RATE",
        measurement_leaf="chargingRate-kph",
        icon="mdi:speedometer",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        is_available=lambda v: v.has_electric_drivetrain,
        entity_registry_enabled_default=False,
    ),
    PorscheSensorEntityDescription(
        key="charging_finished",
        translation_key="charging_finished",
        measurement_node="CHARGING_SUMMARY",
        measurement_leaf="targetDateTimeWithOffset",
        icon="mdi:clock-end",
        device_class=SensorDeviceClass.TIMESTAMP,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="charging_power",
        translation_key="charging_power",
        measurement_node="CHARGING_RATE",
        measurement_leaf="chargingPower",
        icon="mdi:lightning-bolt-circle",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="remaining_range_electric",
        translation_key="remaining_range_electric",
        measurement_node="E_RANGE",
        measurement_leaf="kilometers",
        icon="mdi:gauge",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="state_of_charge",
        translation_key="state_of_charge",
        measurement_node="BATTERY_LEVEL",
        measurement_leaf="percent",
        icon="mdi:battery-medium",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="mileage",
        translation_key="mileage",
        measurement_node="MILEAGE",
        measurement_leaf="kilometers",
        icon="mdi:counter",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
    ),
    PorscheSensorEntityDescription(
        key="remaining_range",
        translation_key="remaining_range",
        measurement_node="RANGE",
        measurement_leaf="kilometers",
        icon="mdi:gas-station",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        is_available=lambda v: v.has_ice_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="fuel_level",
        translation_key="fuel_level",
        measurement_node="FUEL_LEVEL",
        measurement_leaf="percent",
        icon="mdi:gas-station",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        is_available=lambda v: v.has_ice_drivetrain,
    ),
    PorscheSensorEntityDescription(
        # The fuel level at which the low-fuel reserve warning trips. Static
        # per vehicle, so diagnostic + disabled by default.
        key="fuel_reserve",
        translation_key="fuel_reserve",
        measurement_node="FUEL_RESERVE",
        measurement_leaf="percent",
        icon="mdi:gas-station-outline",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_available=lambda v: "FUEL_RESERVE" in v.data,
    ),
    # Per-tire pressure deviation (signed bar, +/- vs OEM target).
    # Diagnostic + disabled by default so the default dashboard keeps a
    # single tire_pressure_status flag; enthusiasts can flip them on.
    PorscheSensorEntityDescription(
        key="tire_pressure_front_left",
        translation_key="tire_pressure_front_left",
        value_fn=_tire_delta("frontLeftTire"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_available=lambda v: v.has_tire_pressure_monitoring,
    ),
    PorscheSensorEntityDescription(
        key="tire_pressure_front_right",
        translation_key="tire_pressure_front_right",
        value_fn=_tire_delta("frontRightTire"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_available=lambda v: v.has_tire_pressure_monitoring,
    ),
    PorscheSensorEntityDescription(
        key="tire_pressure_rear_left",
        translation_key="tire_pressure_rear_left",
        value_fn=_tire_delta("rearLeftTire"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_available=lambda v: v.has_tire_pressure_monitoring,
    ),
    PorscheSensorEntityDescription(
        key="tire_pressure_rear_right",
        translation_key="tire_pressure_rear_right",
        value_fn=_tire_delta("rearRightTire"),
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_available=lambda v: v.has_tire_pressure_monitoring,
    ),
]


# Service-interval sensors. The API reports up to three service types
# (MAIN / OIL / INTERMEDIATE), each as a remaining distance (km) and a
# remaining time (days). They're gated on the measurement being present so
# they never surface "Unknown" on a vehicle that doesn't report a given
# type; the main service is enabled by default, the rest opt-in.
@dataclass(frozen=True)
class _ServiceType:
    """Display config for one service-interval type (distance + time)."""

    api_prefix: str  # API node prefix, e.g. "MAIN" -> MAIN_SERVICE_RANGE/TIME
    key_prefix: str  # HA entity key prefix, e.g. "main_service"
    enabled_by_default: bool


_SERVICE_TYPES: list[_ServiceType] = [
    _ServiceType("MAIN", "main_service", enabled_by_default=True),
    _ServiceType("OIL", "oil_service", enabled_by_default=False),
    _ServiceType("INTERMEDIATE", "intermediate_service", enabled_by_default=False),
]


def _service_descriptions() -> list[PorscheSensorEntityDescription]:
    """Materialise the distance/time service-interval sensor descriptions."""
    descriptions: list[PorscheSensorEntityDescription] = []
    for service in _SERVICE_TYPES:
        key_prefix = service.key_prefix
        enabled = service.enabled_by_default
        range_node = f"{service.api_prefix}_SERVICE_RANGE"
        time_node = f"{service.api_prefix}_SERVICE_TIME"
        descriptions.append(
            PorscheSensorEntityDescription(
                key=f"{key_prefix}_distance",
                translation_key=f"{key_prefix}_distance",
                measurement_node=range_node,
                measurement_leaf="kilometers",
                icon="mdi:car-wrench",
                device_class=SensorDeviceClass.DISTANCE,
                native_unit_of_measurement=UnitOfLength.KILOMETERS,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=enabled,
                is_available=lambda v, _n=range_node: _n in v.data,
            ),
        )
        descriptions.append(
            PorscheSensorEntityDescription(
                key=f"{key_prefix}_time",
                translation_key=f"{key_prefix}_time",
                measurement_node=time_node,
                measurement_leaf="days",
                icon="mdi:wrench-clock",
                device_class=SensorDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.DAYS,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=enabled,
                is_available=lambda v, _n=time_node: _n in v.data,
            ),
        )
    return descriptions


SENSOR_TYPES.extend(_service_descriptions())


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
        new_entities: list[PorscheSensor] = []
        for vehicle in coordinator.vehicles:
            if vehicle.vin in known_vins:
                continue
            known_vins.add(vehicle.vin)
            new_entities.extend(
                PorscheSensor(coordinator, vehicle, description)
                for description in SENSOR_TYPES
                if description.is_available(vehicle)
            )
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheSensor(PorscheBaseEntity, SensorEntity):
    """Representation of a Porsche sensor."""

    entity_description: PorscheSensorEntityDescription

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
        description: PorscheSensorEntityDescription,
    ) -> None:
        """Initialize of the sensor."""
        super().__init__(coordinator, vehicle)

        self.entity_description = description
        self._attr_unique_id = f"{self._vin}-{description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.entity_description.value_fn is not None:
            state = self.entity_description.value_fn(self.vehicle)
        else:
            state = self.coordinator.get_vehicle_data_leaf(
                self.vehicle,
                self.entity_description.measurement_node,
                self.entity_description.measurement_leaf,
            )

        if type(state) is str:
            state = state.lower()

        _LOGGER.debug(
            "Updating sensor '%s' of %s with state '%s'",
            self.entity_description.key,
            self.vehicle.data["name"],
            state,
        )

        self._attr_native_value = state
        super()._handle_coordinator_update()
