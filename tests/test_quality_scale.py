"""Tests the integration quality scale asks for: every flow recovers from its
errors, stale devices go away, repair issues, and the last uncovered paths.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import CONF_CAPTCHA_CODE, DOMAIN

from .conftest import TEST_EMAIL, TEST_PASSWORD, TEST_TOKEN, _make_vehicle

CONNECTION = "custom_components.porscheconnect.config_flow.Connection"
CREDENTIALS = {CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD}


def _login(result: object = TEST_TOKEN) -> MagicMock:
    """A Connection whose login returns a token or raises `result`."""
    connection = MagicMock()
    if isinstance(result, Exception):
        connection.get_token = AsyncMock(side_effect=result)
    else:
        connection.get_token = AsyncMock(return_value=result)
        connection.token = result
    return connection


def _captcha(image: str = "data:image/svg+xml;base64,PHN2Zy8+") -> MagicMock:
    err = PorscheCaptchaRequiredError("captcha please")
    err.captcha = image
    err.state = "state"
    err.code_verifier = "verifier"
    return _login(err)


def _existing_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL,
        data={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: "old-password"},
    )
    entry.add_to_hass(hass)
    return entry


# -- stale devices, dynamic devices, repair issues -------------------------


async def test_car_gone_for_two_refreshes_is_removed_then_set_up_again(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data
    devices = dr.async_get(hass)
    identifier = (DOMAIN, mock_vehicle.vin)
    unique_id = f"{mock_vehicle.vin}-mileage"
    assert devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    )

    mock_account.get_vehicles.return_value = []
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    # One odd answer from Porsche does not delete anything.
    assert devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    ) is None
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id) is None

    # Back on the account: the library lists it as a new vehicle object.
    mock_account.get_vehicles.return_value = [_make_vehicle()]
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    )
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)


async def test_inactive_connect_contract_raises_a_repair_issue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    mock_vehicle.has_porsche_connect = False
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    issues = ir.async_get(hass)
    issue_id = f"connect_inactive_{mock_config_entry.entry_id}_{mock_vehicle.vin}"

    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue.translation_key == "connect_inactive"
    assert issue.translation_placeholders == {"vehicle": "Taycan"}
    # Bound to its entry: Home Assistant hides it with the entry and removes it with it.
    assert issue.config_entry_id == mock_config_entry.entry_id

    # Contract back: the issue goes away and the entry is set up again, since
    # entities are created from what the car reports at setup.
    mock_vehicle.has_porsche_connect = True
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await mock_config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    reload.assert_called_once_with(mock_config_entry.entry_id)

    # An issue never outlives its entry.
    mock_vehicle.has_porsche_connect = False
    await mock_config_entry.runtime_data.async_refresh()
    assert issues.async_get_issue(DOMAIN, issue_id)
    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


# -- last uncovered paths ----------------------------------------------------


async def test_diagnostics_hold_nothing_that_identifies_the_owner(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    import json

    from custom_components.porscheconnect.diagnostics import (
        _mask_vin,
        async_get_config_entry_diagnostics,
    )

    assert _mask_vin("123") == "***123"
    assert _mask_vin(None) is None

    mock_vehicle.data.update(
        {
            "customName": "Jeremie's Taycan",
            "trips": [{"lat": 48.85837, "lng": 2.29448, "vin": 42}],
            "PAIRING_CODE": "pairing-secret",
            "CHARGING_PROFILES": [{"name": "Home", "position": {"x": 48.85837}}],
            "TIMERS": [{"departure": "07:30"}],
        }
    )
    mock_vehicle.data["name"] = "Jeremie's Taycan"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    dump = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert dump["entry"]["data"] == {
        CONF_EMAIL: "**REDACTED**",
        CONF_PASSWORD: "**REDACTED**",
        "access_token": "**REDACTED**",
    }
    assert "title" not in dump["entry"]
    data = dump["vehicles"][0]["data"]
    assert data["trips"] == [{"lat": "**REDACTED**", "lng": "**REDACTED**", "vin": None}]
    for redacted in ("customName", "name", "PAIRING_CODE", "CHARGING_PROFILES", "TIMERS"):
        assert data[redacted] == "**REDACTED**"
    text = json.dumps(dump, default=str)
    for secret in ("example.com", "tester", TEST_PASSWORD, "Jeremie", "07:30", "Home"):
        assert secret not in text
    assert mock_vehicle.vin not in text
    assert dump["vehicles"][0]["vin"] == "***" + mock_vehicle.vin[-4:]
    assert dump["coordinator"] == {
        "last_update_success": True,
        "update_interval_seconds": 1920.0,
    }


async def test_image_is_loaded_from_its_url(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    from homeassistant.components.image import DATA_COMPONENT

    mock_vehicle.picture_locations = {"sideView": "https://example.invalid/side.png"}
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "image", DOMAIN, f"{mock_vehicle.vin}-side_view"
    )
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id)

    with patch.object(
        entity, "_fetch_url", AsyncMock(return_value=SimpleNamespace(content=b"png"))
    ):
        image = await entity._async_load_image_from_url("https://example.invalid/x")
    assert image.content == b"png"

    with patch.object(entity, "_fetch_url", AsyncMock(return_value=None)):
        assert await entity._async_load_image_from_url("https://example.invalid/x") is None


async def test_failed_unlock_and_switch_off_are_reported() -> None:
    from custom_components.porscheconnect.lock import PorscheLock
    from custom_components.porscheconnect.switch import SWITCH_TYPES, PorscheSwitch

    failing = AsyncMock(side_effect=PorscheExceptionError(500))
    vehicle = SimpleNamespace(
        vin="VIN1",
        model_name="Taycan",
        data={"name": "Taycan"},
        vehicle_locked=True,
        remote_climatise_on=True,
        direct_charge_on=True,
        remote_services=SimpleNamespace(
            unlock_vehicle=failing, climatise_off=failing, direct_charge_off=failing
        ),
    )

    lock = PorscheLock(MagicMock(), vehicle)
    lock.async_write_ha_state = MagicMock()
    with pytest.raises(HomeAssistantError) as unlock:
        await lock.async_unlock(code="1234")
    assert unlock.value.translation_key == "unlock_failed"
    assert lock.is_locked is None

    switch = PorscheSwitch(MagicMock(), vehicle, SWITCH_TYPES[0])
    with pytest.raises(HomeAssistantError) as off:
        await switch.async_turn_off()
    assert off.value.translation_key == "remote_service_failed"


async def test_car_without_remote_climatisation_has_no_climate_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    mock_vehicle.has_remote_climatisation = False
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert not [e for e in registry.entities.values() if e.domain == "climate"]
    tracker = registry.async_get_entity_id("device_tracker", DOMAIN, mock_vehicle.vin)
    # No position yet: the tracker has no coordinates rather than a crash.
    assert "longitude" not in hass.states.get(tracker).attributes
    coordinator = mock_config_entry.runtime_data
    assert coordinator.get_vehicle_data_leaf(mock_vehicle, None, "x") is None


async def test_set_temperature_without_a_temperature_sends_nothing() -> None:
    from custom_components.porscheconnect.climate import PorscheClimate

    vehicle = SimpleNamespace(
        vin="VIN1",
        model_name="Taycan",
        data={"name": "Taycan"},
        remote_climatise_on=True,
        climatisation_target_temperature=None,
        remote_services=SimpleNamespace(climatise_on=AsyncMock()),
    )
    climate = PorscheClimate(MagicMock(), vehicle)

    await climate.async_set_temperature(hvac_mode="heat")

    vehicle.remote_services.climatise_on.assert_not_awaited()


async def test_car_back_after_its_device_was_removed_by_hand_is_set_up_again(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_account,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    from custom_components.porscheconnect import async_remove_config_entry_device

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data
    devices = dr.async_get(hass)
    identifier = (DOMAIN, mock_vehicle.vin)

    mock_account.get_vehicles.return_value = []
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    device = devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    )
    assert await async_remove_config_entry_device(hass, mock_config_entry, device)
    devices.async_remove_device(device.id)

    mock_account.get_vehicles.return_value = [_make_vehicle()]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert devices.async_get_device_by_identifier(
        identifier, mock_config_entry.entry_id
    )
    assert er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{mock_vehicle.vin}-mileage"
    )
