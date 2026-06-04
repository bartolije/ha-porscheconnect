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

# The Porsche API takes the target temperature in Kelvin.
_KELVIN_OFFSET = 273.15
_DEFAULT_TEMP_C = 20.0
_MIN_TEMP_C = 15.0
_MAX_TEMP_C = 30.0

_HVAC_MODES = [HVACMode.OFF, HVACMode.HEAT_COOL]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PorscheConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Porsche Connect climate entity from config entry."""
    coordinator: PorscheConnectDataUpdateCoordinator = config_entry.runtime_data

    known_vins: set[str] = set()

    @callback
    def _async_add_entities() -> None:
        new_entities: list[PorscheClimate] = []
        for vehicle in coordinator.vehicles:
            if vehicle.vin in known_vins:
                continue
            if not (vehicle.has_remote_climatisation and vehicle.has_remote_services):
                continue
            known_vins.add(vehicle.vin)
            new_entities.append(PorscheClimate(coordinator, vehicle))
        if new_entities:
            async_add_entities(new_entities)

    _async_add_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_entities))


class PorscheClimate(PorscheBaseEntity, ClimateEntity):
    """Remote climatisation exposed as a climate entity."""

    # Primary feature of the device → named after the vehicle.
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
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
        self._attr_unique_id = f"{self._vin}-climate"
        # The API reports on/off but not the previously-requested target, so we
        # keep an optimistic target the user can adjust.
        self._attr_target_temperature = _DEFAULT_TEMP_C

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
        self._attr_target_temperature = temperature
        if self.vehicle.remote_climatise_on:
            await self._async_apply(turn_on=True)
        else:
            self.async_write_ha_state()

    async def _async_apply(self, *, turn_on: bool) -> None:
        """Send the climatise start/stop command and refresh listeners."""
        try:
            if turn_on:
                await self.vehicle.remote_services.climatise_on(
                    target_temperature=self._attr_target_temperature + _KELVIN_OFFSET,
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
