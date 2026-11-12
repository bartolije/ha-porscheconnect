"""Support for the Porsche Connect sensors."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from pyporscheconnectapi.vehicle import PorscheVehicle

from .coordinator import (
    PorscheConnectConfigEntry,
    PorscheConnectDataUpdateCoordinator,
    has_measurement,
)
from .entity import PorscheBaseEntity

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
    value_fn: Callable[[PorscheVehicle], float | int | str | datetime | None] | None = (
        None
    )
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


def _contract_end(v: PorscheVehicle) -> datetime | None:
    """Return when the Porsche Connect contract ends (CONNECT_CONTRACT.until)."""
    until = (v.data.get("CONNECT_CONTRACT") or {}).get("until")
    return dt_util.parse_datetime(until) if isinstance(until, str) else None


BATTERY_ENERGY_STATUSES = ["normal", "warning", "critical"]


def _battery_energy_status(v: PorscheVehicle) -> str | None:
    """Return BEM_LEVEL.status, or None for a value the enum doesn't know yet."""
    status = str((v.data.get("BEM_LEVEL") or {}).get("status", "")).lower()
    return status if status in BATTERY_ENERGY_STATUSES else None


def _battery_temperature(v: PorscheVehicle) -> float | None:
    """Return BATTERY_CONDITION.batteryTemperatureK in °C (HA doesn't convert K)."""
    kelvin = (v.data.get("BATTERY_CONDITION") or {}).get("batteryTemperatureK")
    return round(kelvin - 273.15, 1) if isinstance(kelvin, (int, float)) else None


def _has_leaf(node: str, leaf: str) -> Callable[[PorscheVehicle], bool]:
    """Gate on a field that only some vehicles fill in (e.g. fuel vs kWh)."""
    return lambda v: (v.data.get(node) or {}).get(leaf) is not None


_MONTHLY = "TRIP_STATISTICS_MONTHLY_REPORT"


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
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="charging_status",
        translation_key="charging_status",
        measurement_node="CHARGING_SUMMARY",
        measurement_leaf="status",
        device_class=SensorDeviceClass.ENUM,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        # The kph charging rate duplicates the more useful kW power reading
        # below — leave it off by default so users opt-in if they actually
        # want both views.
        key="charging_rate",
        translation_key="charging_rate",
        state_class=SensorStateClass.MEASUREMENT,
        measurement_node="CHARGING_RATE",
        measurement_leaf="chargingRate-kph",
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
        device_class=SensorDeviceClass.TIMESTAMP,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="charging_power",
        translation_key="charging_power",
        state_class=SensorStateClass.MEASUREMENT,
        measurement_node="CHARGING_RATE",
        measurement_leaf="chargingPowerkW",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        key="remaining_range_electric",
        translation_key="remaining_range_electric",
        measurement_node="E_RANGE",
        measurement_leaf="kilometers",
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
        # No explicit icon: the battery device class picks the level-aware one.
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        is_available=lambda v: v.has_electric_drivetrain,
    ),
    PorscheSensorEntityDescription(
        # When the car last sent its data: the other values are that old.
        key="last_update",
        translation_key="last_update",
        value_fn=lambda v: v.last_global_update,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_available=lambda v: "GLOBAL_TIMESTAMP" in v.data,
    ),
    PorscheSensorEntityDescription(
        key="mileage",
        translation_key="mileage",
        measurement_node="MILEAGE",
        measurement_leaf="kilometers",
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
    PorscheSensorEntityDescription(
        key="connect_contract_end",
        translation_key="connect_contract_end",
        value_fn=_contract_end,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_available=has_measurement("CONNECT_CONTRACT"),
    ),
    # The fields below come from the app's data models (My Porsche 21.26.44):
    # vehicles that lack them get NOT_SUPPORTED, so no entity is created.
    PorscheSensorEntityDescription(
        key="monthly_distance",
        translation_key="monthly_distance",
        measurement_node=_MONTHLY,
        measurement_leaf="distanceKm",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        is_available=has_measurement(_MONTHLY),
    ),
    PorscheSensorEntityDescription(
        key="monthly_driving_time",
        translation_key="monthly_driving_time",
        measurement_node=_MONTHLY,
        measurement_leaf="drivingTimeMinutes",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        is_available=has_measurement(_MONTHLY),
    ),
    PorscheSensorEntityDescription(
        key="monthly_trips",
        translation_key="monthly_trips",
        measurement_node=_MONTHLY,
        measurement_leaf="tripsTaken",
        is_available=has_measurement(_MONTHLY),
    ),
    PorscheSensorEntityDescription(
        key="monthly_fuel_consumption",
        translation_key="monthly_fuel_consumption",
        measurement_node=_MONTHLY,
        measurement_leaf="avgLiterPerHundredKm",
        native_unit_of_measurement="L/100km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_available=_has_leaf(_MONTHLY, "avgLiterPerHundredKm"),
    ),
    PorscheSensorEntityDescription(
        key="monthly_electric_consumption",
        translation_key="monthly_electric_consumption",
        measurement_node=_MONTHLY,
        measurement_leaf="avgKwhPerHundredKm",
        device_class=SensorDeviceClass.ENERGY_DISTANCE,
        native_unit_of_measurement="kWh/100km",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_available=_has_leaf(_MONTHLY, "avgKwhPerHundredKm"),
    ),
    PorscheSensorEntityDescription(
        key="battery_energy_status",
        translation_key="battery_energy_status",
        value_fn=_battery_energy_status,
        device_class=SensorDeviceClass.ENUM,
        options=BATTERY_ENERGY_STATUSES,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_available=has_measurement("BEM_LEVEL"),
    ),
    PorscheSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        value_fn=_battery_temperature,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_available=has_measurement("BATTERY_CONDITION"),
    ),
    PorscheSensorEntityDescription(
        key="charging_session_energy",
        translation_key="charging_session_energy",
        measurement_node="CHARGING_SESSION",
        measurement_leaf="totalChargedEnergykWh",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        is_available=has_measurement("CHARGING_SESSION"),
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
                device_class=SensorDeviceClass.DISTANCE,
                native_unit_of_measurement=UnitOfLength.KILOMETERS,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=enabled,
                is_available=has_measurement(range_node),
            ),
        )
        descriptions.append(
            PorscheSensorEntityDescription(
                key=f"{key_prefix}_time",
                translation_key=f"{key_prefix}_time",
                measurement_node=time_node,
                measurement_leaf="days",
                device_class=SensorDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.DAYS,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=0,
                entity_category=EntityCategory.DIAGNOSTIC,
                entity_registry_enabled_default=enabled,
                is_available=has_measurement(time_node),
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

    known_vins: dict[str, object] = {}

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheSensor] = []
        for vehicle in coordinator.vehicles:
            if known_vins.get(vehicle.vin) is vehicle:
                continue
            known_vins[vehicle.vin] = vehicle
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
            self._vin,
            state,
        )

        self._attr_native_value = state
        super()._handle_coordinator_update()
