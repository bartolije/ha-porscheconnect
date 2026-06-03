"""Unit tests for ICE capability gating and service-interval sensors.

Like test_open_states_and_tires, these run against the entity-description
tables directly (no HA setup), validating the `is_available` capability
gates and the service-interval description table. Verified shapes come from
a live 718 Cayman GT4 RS (engine COMBUSTION) overview, where PARKING_BRAKE /
PARKING_LIGHT / REMOTE_ACCESS_AUTHORIZATION come back NOT_SUPPORTED (dropped
from vehicle.data) and the *_SERVICE_RANGE/TIME nodes are present.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.porscheconnect.binary_sensor import (
    SENSOR_TYPES as BINARY_SENSOR_TYPES,
)
from custom_components.porscheconnect.sensor import SENSOR_TYPES


def _vehicle_with(data: dict, **attrs) -> SimpleNamespace:
    """Minimal vehicle stand-in: just .data plus any has_* attrs needed."""
    default_attrs = {
        "has_porsche_connect": True,
        "has_electric_drivetrain": False,
        "has_ice_drivetrain": True,
        "has_tire_pressure_monitoring": "TIRE_PRESSURE" in data,
    }
    default_attrs.update(attrs)
    return SimpleNamespace(data=data, **default_attrs)


# -- Capability gates on previously-ungated binary sensors ------------------


class TestUnsupportedBinarySensorGating:
    """parking_brake / parking_light / remote_access used to always be
    created, surfacing a permanent "Unknown" on combustion cars that report
    these measurements as NOT_SUPPORTED. They must now hide when the key is
    absent from vehicle.data.
    """

    GATED = {
        "parking_brake": "PARKING_BRAKE",
        "parking_light": "PARKING_LIGHT",
        "remote_access": "REMOTE_ACCESS_AUTHORIZATION",
    }

    @pytest.fixture
    def by_key(self):
        return {d.key: d for d in BINARY_SENSOR_TYPES}

    def test_hidden_when_node_absent(self, by_key):
        vehicle = _vehicle_with({"vin": "X"})  # combustion car, nodes dropped
        for key in self.GATED:
            assert by_key[key].is_available(vehicle) is False, key

    def test_shown_when_node_present(self, by_key):
        for key, node in self.GATED.items():
            vehicle = _vehicle_with({node: {"isEnabled": True}})
            assert by_key[key].is_available(vehicle) is True, key


# -- Fuel reserve sensor ----------------------------------------------------


class TestFuelReserveSensor:
    """fuel_reserve mirrors fuel_level but is diagnostic/opt-in and gated on
    the FUEL_RESERVE node being present.
    """

    @pytest.fixture
    def desc(self):
        return next(d for d in SENSOR_TYPES if d.key == "fuel_reserve")

    def test_node_and_leaf(self, desc):
        assert desc.measurement_node == "FUEL_RESERVE"
        assert desc.measurement_leaf == "percent"

    def test_disabled_by_default(self, desc):
        assert desc.entity_registry_enabled_default is False

    def test_gated_on_node_presence(self, desc):
        assert desc.is_available(_vehicle_with({})) is False
        assert desc.is_available(_vehicle_with({"FUEL_RESERVE": {"percent": 15}})) is True


# -- Service-interval sensors -----------------------------------------------


class TestServiceIntervalSensors:
    """Six sensors: {main,oil,intermediate} x {distance,time}, each gated on
    its API node and reusing key as translation_key.
    """

    @pytest.fixture
    def service_descs(self):
        return [d for d in SENSOR_TYPES if d.key.endswith(("_service_distance", "_service_time"))]

    def test_six_descriptions(self, service_descs):
        assert len(service_descs) == 6
        keys = sorted(d.key for d in service_descs)
        assert keys == [
            "intermediate_service_distance",
            "intermediate_service_time",
            "main_service_distance",
            "main_service_time",
            "oil_service_distance",
            "oil_service_time",
        ]

    def test_key_equals_translation_key(self, service_descs):
        for d in service_descs:
            assert d.key == d.translation_key

    def test_nodes_and_leaves(self, service_descs):
        by_key = {d.key: d for d in service_descs}
        assert by_key["main_service_distance"].measurement_node == "MAIN_SERVICE_RANGE"
        assert by_key["main_service_distance"].measurement_leaf == "kilometers"
        assert by_key["oil_service_time"].measurement_node == "OIL_SERVICE_TIME"
        assert by_key["oil_service_time"].measurement_leaf == "days"

    def test_only_main_enabled_by_default(self, service_descs):
        by_key = {d.key: d for d in service_descs}
        assert by_key["main_service_distance"].entity_registry_enabled_default is True
        assert by_key["main_service_time"].entity_registry_enabled_default is True
        for key in (
            "oil_service_distance", "oil_service_time",
            "intermediate_service_distance", "intermediate_service_time",
        ):
            assert by_key[key].entity_registry_enabled_default is False, key

    def test_gated_on_node_presence(self, service_descs):
        by_key = {d.key: d for d in service_descs}
        assert by_key["main_service_distance"].is_available(_vehicle_with({})) is False
        present = _vehicle_with({"MAIN_SERVICE_RANGE": {"kilometers": 14900}})
        assert by_key["main_service_distance"].is_available(present) is True
