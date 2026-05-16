"""Unit tests for the new per-OPEN_STATE_* binary sensors and per-tire sensors.

These run against the entity-description tables directly (not via HA setup)
so they validate the capability gating and the value-extraction lambdas
without needing a live Porsche payload. Once the GT4 RS is paired in the
PCM and starts emitting `OPEN_STATE_*` / `TIRE_PRESSURE` keys, these
extractions are what will drive the real entities.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.porscheconnect.binary_sensor import (
    SENSOR_TYPES as BINARY_SENSOR_TYPES,
)
from custom_components.porscheconnect.sensor import SENSOR_TYPES as SENSOR_TYPES


def _vehicle_with(data: dict, **attrs) -> SimpleNamespace:
    """Minimal vehicle stand-in: just .data plus any has_* attrs the
    `is_available` lambdas need.
    """
    default_attrs = {
        "has_porsche_connect": True,
        "has_electric_drivetrain": False,
        "has_ice_drivetrain": True,
        "has_remote_climatisation": False,
        "has_remote_services": True,
        "has_tire_pressure_monitoring": "TIRE_PRESSURE" in data,
        "tire_pressures": data.get("TIRE_PRESSURE"),
    }
    default_attrs.update(attrs)
    return SimpleNamespace(data=data, **default_attrs)


# -- OPEN_STATE_* binary sensors ----------------------------------------


class TestOpenStateBinarySensors:
    """The 17 OPEN_STATE_* descriptions are gated on key-presence in data.

    A car that only exposes front doors must not get window/sunroof
    entities created — same defensive pattern as the climate-zones fix
    for #292.
    """

    @pytest.fixture
    def open_state_descs(self):
        # Only the 17 added by _open_state_descriptions(); the original
        # 6 are kept untouched (parking_brake, parking_light, doors_and_lids,
        # remote_access, privacy_mode, tire_pressure_status).
        return [d for d in BINARY_SENSOR_TYPES if d.measurement_node and d.measurement_node.startswith("OPEN_STATE_")]

    def test_seventeen_open_state_descriptions(self, open_state_descs):
        # 4 doors + 2 lids + 4 windows + 2 sunroofs + 1 top
        # + 2 charge flaps + spoiler + service flap = 17.
        assert len(open_state_descs) == 17

    def test_is_available_requires_key_in_data(self, open_state_descs):
        """Each description must hide itself when its OPEN_STATE_* key is
        absent from `vehicle.data`. Mirrors the climate zones fix.
        """
        door_left = next(d for d in open_state_descs if d.key == "door_front_left")

        vehicle_without_door = _vehicle_with({"vin": "X"})
        assert door_left.is_available(vehicle_without_door) is False

        vehicle_with_door = _vehicle_with({"OPEN_STATE_DOOR_FRONT_LEFT": {"isOpen": False}})
        assert door_left.is_available(vehicle_with_door) is True

    def test_each_open_state_has_unique_key_and_translation(self, open_state_descs):
        keys = [d.key for d in open_state_descs]
        translation_keys = [d.translation_key for d in open_state_descs]
        assert len(set(keys)) == 17, "duplicate entity key in OPEN_STATE_* set"
        assert keys == translation_keys, (
            "Each OPEN_STATE_* entity must reuse its key as translation_key "
            "to match the entries we wrote into strings.json"
        )

    def test_cosmetic_and_maintenance_parts_are_disabled_by_default(
        self, open_state_descs,
    ):
        """Spoiler and service flap default to disabled — primary user-facing
        parts (doors, windows, lids, sunroofs, charge flaps, top) stay on.
        """
        by_key = {d.key: d for d in open_state_descs}
        assert by_key["spoiler"].entity_registry_enabled_default is False
        assert by_key["service_flap"].entity_registry_enabled_default is False
        # And the primary ones stay enabled:
        for primary in (
            "door_front_left", "lid_front", "window_rear_right",
            "sunroof", "convertible_top", "charge_flap_left",
        ):
            assert by_key[primary].entity_registry_enabled_default is not False, primary


# -- Per-tire pressure deviation sensors --------------------------------


class TestTirePressureSensors:
    """Four per-tire sensors expose TIRE_PRESSURE.<tire>.differenceBar.

    The Porsche API names the keys frontLeftTire / frontRightTire /
    rearLeftTire / rearRightTire (verified against the lib fixture).
    """

    SAMPLE_TP = {
        "frontLeftTire": {"differenceBar": 0.05},
        "frontRightTire": {"differenceBar": -0.10},
        "rearLeftTire": {"differenceBar": 0.02},
        "rearRightTire": {"differenceBar": 0.07},
    }

    @pytest.fixture
    def tire_descs(self):
        return [d for d in SENSOR_TYPES if d.key.startswith("tire_pressure_")]

    def test_four_per_tire_descriptions(self, tire_descs):
        assert len(tire_descs) == 4
        keys = sorted(d.key for d in tire_descs)
        assert keys == [
            "tire_pressure_front_left",
            "tire_pressure_front_right",
            "tire_pressure_rear_left",
            "tire_pressure_rear_right",
        ]

    def test_value_fn_pulls_correct_tire_delta(self, tire_descs):
        vehicle = _vehicle_with({"TIRE_PRESSURE": self.SAMPLE_TP})
        by_key = {d.key: d for d in tire_descs}
        assert by_key["tire_pressure_front_left"].value_fn(vehicle) == 0.05
        assert by_key["tire_pressure_front_right"].value_fn(vehicle) == -0.10
        assert by_key["tire_pressure_rear_left"].value_fn(vehicle) == 0.02
        assert by_key["tire_pressure_rear_right"].value_fn(vehicle) == 0.07

    def test_value_fn_returns_none_when_tire_missing(self, tire_descs):
        # If a tire entry isn't in the payload, we must not crash — return None.
        partial = {"frontLeftTire": {"differenceBar": 0.05}}
        vehicle = _vehicle_with({"TIRE_PRESSURE": partial})
        by_key = {d.key: d for d in tire_descs}
        assert by_key["tire_pressure_front_left"].value_fn(vehicle) == 0.05
        assert by_key["tire_pressure_rear_right"].value_fn(vehicle) is None

    def test_value_fn_returns_none_when_no_tire_pressure_data(self, tire_descs):
        vehicle = _vehicle_with({}, tire_pressures=None)
        by_key = {d.key: d for d in tire_descs}
        assert by_key["tire_pressure_front_left"].value_fn(vehicle) is None

    def test_disabled_by_default(self, tire_descs):
        """Per-tire deltas are off by default to keep the dashboard clean —
        the aggregated tire_pressure_status binary sensor stays enabled.
        """
        for desc in tire_descs:
            assert desc.entity_registry_enabled_default is False

    def test_is_available_requires_tire_pressure_monitoring(self, tire_descs):
        no_tpms = _vehicle_with({}, has_tire_pressure_monitoring=False)
        for desc in tire_descs:
            assert desc.is_available(no_tpms) is False

        with_tpms = _vehicle_with(
            {"TIRE_PRESSURE": self.SAMPLE_TP},
            has_tire_pressure_monitoring=True,
        )
        for desc in tire_descs:
            assert desc.is_available(with_tpms) is True
