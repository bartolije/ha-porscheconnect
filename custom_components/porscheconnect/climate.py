"""Support for the Porsche Connect remote climatisation as a climate entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
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

# The Porsche API takes the target temperature in Kelvin.
_KELVIN_OFFSET = 273.15
_DEFAULT_TEMP_C = 20.0
_MIN_TEMP_C = 15.0
_MAX_TEMP_C = 30.0

_HVAC_MODES = [HVACMode.OFF, HVACMode.HEAT_COOL]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Porsche Connect climate entity from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: dict[str, object] = {}

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheClimate] = []
        for vehicle in coordinator.vehicles:
            if known_vins.get(vehicle.vin) is vehicle:
                continue
            if not (vehicle.has_remote_climatisation and vehicle.has_remote_services):
                continue
            known_vins[vehicle.vin] = vehicle
            new_entities.append(PorscheClimate(coordinator, vehicle))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheClimate(PorscheBaseEntity, ClimateEntity):
    """Remote climatisation exposed as a climate entity."""

    # Primary feature of the device → named after the vehicle.
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = _HVAC_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = _MIN_TEMP_C
    _attr_max_temp = _MAX_TEMP_C
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        coordinator: PorscheConnectDataUpdateCoordinator,
        vehicle: PorscheVehicle,
    ) -> None:
        """Initialise the climate entity."""
        super().__init__(coordinator, vehicle)
        self._attr_unique_id = self._vin
        # Start from the target the car reports; the user's later choice is kept
        # until climatisation runs, then the car's target is followed again.
        reported = vehicle.climatisation_target_temperature
        self._attr_native_target_temperature = (
            reported if reported is not None else _DEFAULT_TEMP_C
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Follow the target the car applies while climatisation runs."""
        reported = self.vehicle.climatisation_target_temperature
        if self.vehicle.remote_climatise_on and reported is not None:
            self._attr_native_target_temperature = reported
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the remaining climatisation time, in minutes, while it runs."""
        return {"remaining_time": self.vehicle.climatisation_remaining_time}

    @property
    def hvac_mode(self) -> HVACMode:
        """Return HEAT_COOL while climatisation is running, OFF otherwise."""
        return HVACMode.HEAT_COOL if self.vehicle.remote_climatise_on else HVACMode.OFF

    async def async_turn_on(self) -> None:
        """Start remote climatisation."""
        await self._async_apply(turn_on=True)

    async def async_turn_off(self) -> None:
        """Stop remote climatisation."""
        await self._async_apply(turn_on=False)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start/stop climatisation from the HVAC mode selector."""
        await self._async_apply(turn_on=hvac_mode != HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature, re-applying if climatisation is running."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._attr_native_target_temperature = temperature
        if self.vehicle.remote_climatise_on:
            await self._async_apply(turn_on=True)
        else:
            self.async_write_ha_state()

    async def _async_apply(self, *, turn_on: bool) -> None:
        """Send the climatise start/stop command and refresh listeners."""
        try:
            if turn_on:
                target = self._attr_native_target_temperature or _DEFAULT_TEMP_C
                target_kelvin = target + _KELVIN_OFFSET
                await self.vehicle.remote_services.climatise_on(
                    target_temperature=target_kelvin,
                )
            else:
                await self.vehicle.remote_services.climatise_off()
        except PorscheExceptionError as ex:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="remote_service_failed",
                translation_placeholders={
                    "service": "climatisation",
                    "vin": self.vehicle.vin,
                    "error": str(ex),
                },
            ) from ex

        self.coordinator.async_update_listeners()
