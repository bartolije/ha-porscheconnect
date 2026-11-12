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


# -- config flow: after each error, fix the cause and finish the flow --------


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (PorscheWrongCredentialsError("nope"), "invalid_auth"),
        (PorscheExceptionError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_recovers_from_an_error(
    hass: HomeAssistant, failure: Exception, error: str
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(CONNECTION, side_effect=[_login(failure), _login()]),
        patch("custom_components.porscheconnect.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": error}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_EMAIL] == TEST_EMAIL


async def test_captcha_flow_recovers_from_a_refused_code(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(
            CONNECTION,
            side_effect=[
                _captcha(),
                _login(PorscheWrongCredentialsError("wrong code")),
                # Not a data URI: shown as it is.
                _captcha("https://example.invalid/captcha.png"),
                _login(),
            ],
        ),
        patch("custom_components.porscheconnect.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["step_id"] == "captcha"
        # Opening the step again shows the same form.
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert result["step_id"] == "captcha"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "WRONG"}
        )
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "invalid_auth"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["step_id"] == "captcha"
        assert "example.invalid" in result["description_placeholders"]["captcha_img"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "RIGHT"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (config_entries.SOURCE_REAUTH, "reauth_successful"),
        (config_entries.SOURCE_RECONFIGURE, "reconfigure_successful"),
    ],
)
async def test_reauth_and_reconfigure_recover_from_an_error(
    hass: HomeAssistant, source: str, reason: str
) -> None:
    entry = _existing_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    first = (
        dict(CREDENTIALS)
        if source == config_entries.SOURCE_REAUTH
        else {CONF_PASSWORD: TEST_PASSWORD}
    )
    with (
        patch(
            CONNECTION,
            side_effect=[_login(PorscheWrongCredentialsError("nope")), _login()],
        ),
        patch("custom_components.porscheconnect.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=first
        )
        assert result["type"] == FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}
        assert entry.data[CONF_PASSWORD] == "old-password"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data[CONF_PASSWORD] == TEST_PASSWORD


async def test_empty_form_is_refused_by_the_schema(hass: HomeAssistant) -> None:
    """Both fields are required: an empty submit never reaches the login."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})


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
    issue_id = f"connect_inactive_{mock_vehicle.vin}"

    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue.translation_key == "connect_inactive"
    assert issue.translation_placeholders == {"vehicle": "Taycan"}

    mock_vehicle.has_porsche_connect = True
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_removing_the_entry_forgets_its_http_client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    from custom_components.porscheconnect import _ENTRY_CLIENTS

    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.entry_id in hass.data[_ENTRY_CLIENTS]

    assert await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.entry_id not in hass.data[_ENTRY_CLIENTS]


# -- last uncovered paths ----------------------------------------------------


async def test_diagnostics_mask_identifiers_and_drop_coordinates(
    hass: HomeAssistant,
    mock_vehicle,
    mock_connection_cls,
    mock_account_cls,
) -> None:
    from custom_components.porscheconnect.diagnostics import (
        _mask_email,
        _mask_vin,
        async_get_config_entry_diagnostics,
    )

    assert _mask_email("a@example.com") == "a***@example.com"
    assert _mask_email("not an email") == "not an email"
    assert _mask_vin("123") == "***123"
    assert _mask_vin(None) is None

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="",
        unique_id=TEST_EMAIL,
        data={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
    )
    mock_vehicle.data.update(
        {"trips": [{"lat": 48.85837, "lng": 2.29448, "vin": 42}], "PAIRING_CODE": "x"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    dump = await async_get_config_entry_diagnostics(hass, entry)

    assert dump["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert dump["entry"]["data"][CONF_EMAIL] == "te***@example.com"
    trip = dump["vehicles"][0]["data"]["trips"][0]
    assert trip == {"lat": "**REDACTED**", "lng": "**REDACTED**", "vin": None}


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
