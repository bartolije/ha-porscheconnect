"""Tests for the measurements read since My Porsche 21.26.44.

Payloads follow the app's data models; CONNECT_CONTRACT is a captured one.
"""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, platform: str, vin: str, key: str) -> str | None:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{vin}-{key}")
    return hass.states.get(entity_id).state if entity_id else None


async def test_new_entities_exist_only_when_the_car_reports_them(
    hass: HomeAssistant, mock_config_entry, mock_vehicle, mock_connection_cls, mock_account_cls
) -> None:
    """A car without the new measurements (NOT_SUPPORTED) gets no new entity."""
    await _setup(hass, mock_config_entry)

    for platform, key in [
        ("sensor", "connect_contract_end"),
        ("sensor", "monthly_distance"),
        ("sensor", "battery_energy_status"),
        ("sensor", "battery_temperature"),
        ("sensor", "charging_session_energy"),
        ("binary_sensor", "instrument_cluster_alerts"),
    ]:
        assert _state(hass, platform, mock_vehicle.vin, key) is None, key


async def test_new_sensor_values(
    hass: HomeAssistant, mock_config_entry, mock_vehicle, mock_connection_cls, mock_account_cls
) -> None:
    """Each new sensor reads its field; fuel-only report has no kWh sensor."""
    mock_vehicle.data |= {
        "CONNECT_CONTRACT": {"isEnabled": True, "until": "2030-06-03T12:32:04Z"},
        "TRIP_STATISTICS_MONTHLY_REPORT": {
            "isBeginningOfMonth": False,
            "distanceKm": 412.5,
            "previousDistanceKm": 380.0,
            "drivingTimeMinutes": 395,
            "previousDrivingTimeMinutes": 350,
            "tripsTaken": 23,
            "previousTripsTaken": 20,
            "avgLiterPerHundredKm": 11.2,
            "avgKwhPerHundredKm": None,
        },
        "BEM_LEVEL": {"status": "WARNING", "supportedStatuses": [], "actions": ["TAKE_TRIP"]},
        "BATTERY_CONDITION": {"batteryTemperatureK": 298.15},
        "CHARGING_SESSION": {"totalChargedEnergykWh": 42.7},
    }
    await _setup(hass, mock_config_entry)
    vin = mock_vehicle.vin

    assert _state(hass, "sensor", vin, "connect_contract_end") == "2030-06-03T12:32:04+00:00"
    assert float(_state(hass, "sensor", vin, "monthly_distance")) == 412.5
    assert float(_state(hass, "sensor", vin, "monthly_driving_time")) == 395
    assert _state(hass, "sensor", vin, "monthly_trips") == "23"
    assert float(_state(hass, "sensor", vin, "monthly_fuel_consumption")) == 11.2
    assert _state(hass, "sensor", vin, "monthly_electric_consumption") is None
    assert _state(hass, "sensor", vin, "battery_energy_status") == "warning"
    assert float(_state(hass, "sensor", vin, "battery_temperature")) == pytest.approx(25)
    assert float(_state(hass, "sensor", vin, "charging_session_energy")) == 42.7


async def test_battery_energy_status_ignores_unknown_values(
    hass: HomeAssistant, mock_config_entry, mock_vehicle, mock_connection_cls, mock_account_cls
) -> None:
    """A status the enum doesn't list yet shows as unknown instead of failing."""
    mock_vehicle.data["BEM_LEVEL"] = {"status": "SOMETHING_NEW"}
    await _setup(hass, mock_config_entry)

    assert _state(hass, "sensor", mock_vehicle.vin, "battery_energy_status") == STATE_UNKNOWN


@pytest.mark.parametrize(
    ("alerts", "expected"),
    [
        ({"infos": ["OIL_LEVEL_LOW"], "warnings": [], "criticals": []}, STATE_OFF),
        ({"infos": [], "warnings": ["TIRE_PRESSURE_WARNING"], "criticals": []}, STATE_ON),
        ({"infos": [], "warnings": [], "criticals": ["OIL_LEVEL_CRITICAL"]}, STATE_ON),
    ],
)
async def test_instrument_cluster_alerts(
    hass: HomeAssistant,
    mock_config_entry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
    alerts: dict[str, list[str]],
    expected: str,
) -> None:
    """Warnings and criticals turn the problem sensor on; infos alone don't."""
    mock_vehicle.data["INSTRUMENT_CLUSTER_ALERTS"] = alerts
    await _setup(hass, mock_config_entry)

    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{mock_vehicle.vin}-instrument_cluster_alerts"
    )
    state = hass.states.get(entity_id)
    assert state.state == expected
    assert state.attributes["warnings"] == [a.lower() for a in alerts["warnings"]]
