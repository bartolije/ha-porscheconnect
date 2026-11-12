"""Entity actions and outages, through Home Assistant: set up an entry, then
call actions and read states, as a user or an automation would.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pyporscheconnectapi.exceptions import PorscheExceptionError
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN


@pytest.fixture
async def car(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
):
    """Set up the entry with a car that accepts every command."""
    for command in (
        "lock_vehicle",
        "unlock_vehicle",
        "flash_indicators",
        "honk_and_flash_indicators",
        "direct_charge_on",
        "direct_charge_off",
        "set_target_soc",
    ):
        setattr(mock_vehicle.remote_services, command, AsyncMock())
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_vehicle


def _entity(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id, f"{platform} {unique_id} was not created"
    return entity_id


async def _call(hass: HomeAssistant, domain: str, action: str, entity_id: str, **data):
    await hass.services.async_call(
        domain, action, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


async def test_lock_and_unlock(hass: HomeAssistant, car) -> None:
    lock = _entity(hass, "lock", car.vin)

    await _call(hass, "lock", "lock", lock)
    car.remote_services.lock_vehicle.assert_awaited_once()

    await _call(hass, "lock", "unlock", lock, code="1234")
    car.remote_services.unlock_vehicle.assert_awaited_once_with("1234")


@pytest.mark.parametrize("code", ["12ab", "123", "12345"])
async def test_unlock_refuses_a_code_that_cannot_be_a_pin(
    hass: HomeAssistant, car, code: str
) -> None:
    """Wrong input is refused before anything is sent to Porsche."""
    with pytest.raises(ServiceValidationError) as error:
        await _call(hass, "lock", "unlock", _entity(hass, "lock", car.vin), code=code)

    assert error.value.translation_key == "pin_code_invalid"
    car.remote_services.unlock_vehicle.assert_not_awaited()


async def test_switch_button_and_number(hass: HomeAssistant, car) -> None:
    switch = _entity(hass, "switch", f"{car.vin}-direct_charging")
    await _call(hass, "switch", "turn_on", switch)
    car.remote_services.direct_charge_on.assert_awaited_once()
    await _call(hass, "switch", "turn_off", switch)
    car.remote_services.direct_charge_off.assert_awaited_once()

    await _call(
        hass, "button", "press", _entity(hass, "button", f"{car.vin}-flash_indicators")
    )
    car.remote_services.flash_indicators.assert_awaited_once()

    number = _entity(hass, "number", f"{car.vin}-target_soc")
    await _call(hass, "number", "set_value", number, value=80)
    car.remote_services.set_target_soc.assert_awaited_once_with(target_soc=80)


async def test_climate(hass: HomeAssistant, car) -> None:
    climate = _entity(hass, "climate", car.vin)

    await _call(hass, "climate", "set_temperature", climate, temperature=21)
    await _call(hass, "climate", "turn_on", climate)
    car.remote_services.climatise_on.assert_awaited_once()
    # 21 °C, sent in kelvin.
    assert car.remote_services.climatise_on.await_args.kwargs[
        "target_temperature"
    ] == pytest.approx(294.15)

    await _call(hass, "climate", "turn_off", climate)
    car.remote_services.climatise_off.assert_awaited_once()


@pytest.mark.parametrize(
    ("domain", "action", "platform", "suffix", "command", "data", "key"),
    [
        ("lock", "lock", "lock", "", "lock_vehicle", {}, "lock_failed"),
        (
            "lock",
            "unlock",
            "lock",
            "",
            "unlock_vehicle",
            {"code": "1234"},
            "unlock_failed",
        ),
        (
            "switch",
            "turn_on",
            "switch",
            "-direct_charging",
            "direct_charge_on",
            {},
            "remote_service_failed",
        ),
        (
            "button",
            "press",
            "button",
            "-flash_indicators",
            "flash_indicators",
            {},
            "remote_service_failed",
        ),
        (
            "number",
            "set_value",
            "number",
            "-target_soc",
            "set_target_soc",
            {"value": 80},
            "remote_service_failed",
        ),
        (
            "climate",
            "turn_on",
            "climate",
            "",
            "climatise_on",
            {},
            "remote_service_failed",
        ),
    ],
)
async def test_a_command_porsche_refuses_raises_a_translated_error(  # noqa: PLR0913
    hass: HomeAssistant,
    car,
    domain: str,
    action: str,
    platform: str,
    suffix: str,
    command: str,
    data: dict,
    key: str,
) -> None:
    getattr(car.remote_services, command).side_effect = PorscheExceptionError(500)

    with pytest.raises(HomeAssistantError) as error:
        await _call(
            hass, domain, action, _entity(hass, platform, f"{car.vin}{suffix}"), **data
        )

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == key


async def test_outage_is_logged_once_and_recovery_once(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    car,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = mock_config_entry.runtime_data
    mileage = _entity(hass, "sensor", f"{car.vin}-mileage")
    caplog.clear()
    caplog.set_level(logging.INFO, logger="custom_components.porscheconnect")

    car.get_stored_overview.side_effect = PorscheExceptionError(503)
    for _ in range(3):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(mileage).state == STATE_UNAVAILABLE

    car.get_stored_overview.side_effect = None
    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(mileage).state != STATE_UNAVAILABLE

    lines = [record.getMessage() for record in caplog.records]
    assert len([line for line in lines if "Error fetching" in line]) == 1
    assert len([line for line in lines if "recovered" in line]) == 1


@pytest.mark.parametrize("status", [405, 423])
async def test_blocked_account_is_not_retried(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
    status: int,
) -> None:
    """Mobile access disabled, account locked: only the owner can lift it."""
    mock_vehicle.get_stored_overview.side_effect = PorscheExceptionError(status)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    # Not a wrong password: no reauthentication is asked.
    assert not hass.config_entries.flow.async_progress()
