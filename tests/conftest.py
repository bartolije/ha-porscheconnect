"""Shared fixtures for the Porsche Connect test suite."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN

# Enables the pytest-homeassistant-custom-component plugin and its fixtures
# (notably `hass`, `enable_custom_integrations`).
pytest_plugins = ("pytest_homeassistant_custom_component",)


TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "hunter2"
TEST_TOKEN = {"access_token": "abc123", "expires_in": 3600}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations,  # noqa: ARG001
):
    """Enable loading of the porscheconnect custom component during tests."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a MockConfigEntry matching the integration's expected schema."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL.lower(),
        data={
            CONF_EMAIL: TEST_EMAIL,
            CONF_PASSWORD: TEST_PASSWORD,
            CONF_ACCESS_TOKEN: TEST_TOKEN,
        },
    )


def _make_vehicle() -> SimpleNamespace:
    """Build a minimal stand-in for `pyporscheconnectapi.vehicle.PorscheVehicle`.

    Only the attributes the integration actually reads are populated.
    """
    vehicle = SimpleNamespace()
    vehicle.vin = "WP0ZZZY1ZLSA00001"
    vehicle.model_name = "Taycan Turbo S"
    vehicle.has_electric_drivetrain = True
    vehicle.has_ice_drivetrain = False
    vehicle.has_remote_climatisation = True
    vehicle.has_remote_services = True
    vehicle.has_tire_pressure_monitoring = True
    vehicle.has_porsche_connect = True
    vehicle.privacy_mode = False
    vehicle.picture_locations = {}
    vehicle.data = {
        "name": "Taycan",
        "modelName": "Taycan Turbo S",
        "vin": vehicle.vin,
    }
    vehicle.get_stored_overview = AsyncMock(return_value=None)
    vehicle.get_picture_locations = AsyncMock(return_value=None)
    vehicle.remote_services = SimpleNamespace(
        climatise_on=AsyncMock(return_value=None),
    )
    return vehicle


@pytest.fixture
def mock_vehicle() -> SimpleNamespace:
    """Single mock vehicle suitable for setup paths."""
    return _make_vehicle()


@pytest.fixture
def mock_account(mock_vehicle) -> MagicMock:
    """A mocked `PorscheConnectAccount` returning one vehicle."""
    account = MagicMock()
    account.token = TEST_TOKEN
    account.get_vehicles = AsyncMock(return_value=[mock_vehicle])
    return account


@pytest.fixture
def mock_connection_cls() -> Generator[MagicMock, None, None]:
    """Patch `Connection` at its import sites (config_flow + __init__)."""
    instance = MagicMock()
    instance.get_token = AsyncMock(return_value=TEST_TOKEN)
    instance.token = TEST_TOKEN
    with (
        patch(
            "custom_components.porscheconnect.config_flow.Connection",
            return_value=instance,
        ) as cf_cls,
        patch(
            "custom_components.porscheconnect.Connection",
            return_value=instance,
        ),
    ):
        cf_cls.instance = instance
        yield cf_cls


@pytest.fixture
def mock_account_cls(mock_account) -> Generator[MagicMock, None, None]:
    """Patch `PorscheConnectAccount` where __init__.py imports it."""
    with patch(
        "custom_components.porscheconnect.PorscheConnectAccount",
        return_value=mock_account,
    ) as cls:
        yield cls
