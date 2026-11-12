"""Tests for the config flow: every flow, through every error, to its end."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import CONF_CAPTCHA_CODE, DOMAIN

from .conftest import TEST_EMAIL, TEST_PASSWORD, TEST_TOKEN

CONNECTION = "custom_components.porscheconnect.config_flow.Connection"
SETUP_ENTRY = "custom_components.porscheconnect.async_setup_entry"
CREDENTIALS = {CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD}
NEW_TOKEN = {"access_token": "fresh", "expires_in": 3600}

# Every error a form can show, with what makes Porsche (or a bug) cause it.
ERRORS = [
    (PorscheWrongCredentialsError("nope"), "invalid_auth"),
    (PorscheExceptionError("down"), "cannot_connect"),
    (RuntimeError("bug"), "unknown"),
]


def _login(result: object = TEST_TOKEN) -> MagicMock:
    """A Connection whose login returns a token or raises `result`."""
    connection = MagicMock()
    if isinstance(result, Exception):
        connection.get_token = AsyncMock(side_effect=result)
    else:
        connection.get_token = AsyncMock(return_value=result)
    return connection


def _captcha(name: str = "first") -> MagicMock:
    """A Connection whose login stops on a captcha, as an SVG data URI."""
    err = PorscheCaptchaRequiredError("captcha please")
    svg = f'<svg width="150" height="50">{name}</svg>'.encode()
    err.captcha = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    err.state = f"state-{name}"
    err.code_verifier = f"verifier-{name}"
    return _login(err)


def _shown_captcha(result: dict) -> str:
    """Return the SVG the captcha form shows."""
    image = result["description_placeholders"]["captcha_img"]
    return base64.b64decode(image.split(",", 1)[1].split('"')[0]).decode()


def _existing_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL,
        data={
            CONF_EMAIL: TEST_EMAIL,
            CONF_PASSWORD: "old-password",
            CONF_ACCESS_TOKEN: {"access_token": "old"},
        },
    )
    entry.add_to_hass(hass)
    return entry


async def _start_user_flow(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]
    return result


# -- user flow -----------------------------------------------------------------


async def test_user_flow_creates_the_entry(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)
    with (
        patch(CONNECTION, return_value=_login(NEW_TOKEN)) as connection,
        patch(SETUP_ENTRY, return_value=None) as setup_entry,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            # Typed with capitals and spaces: one account all the same.
            user_input={CONF_EMAIL: "  Tester@Example.COM ", CONF_PASSWORD: "pw"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_EMAIL
    assert result["result"].unique_id == TEST_EMAIL
    assert result["data"] == {
        CONF_EMAIL: TEST_EMAIL,
        CONF_PASSWORD: "pw",
        CONF_ACCESS_TOKEN: NEW_TOKEN,
    }
    assert result["result"].version == 3
    # A first login carries no captcha data.
    assert connection.call_args.kwargs["email"] == TEST_EMAIL
    assert connection.call_args.kwargs["captcha_code"] is None
    assert connection.call_args.kwargs["state"] is None
    assert connection.call_args.kwargs["code_verifier"] is None
    assert len(setup_entry.mock_calls) == 1


@pytest.mark.parametrize(("failure", "error"), ERRORS)
async def test_user_flow_recovers_from_an_error(
    hass: HomeAssistant, failure: Exception, error: str
) -> None:
    result = await _start_user_flow(hass)
    with (
        patch(CONNECTION, side_effect=[_login(failure), _login()]),
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": error}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_EMAIL


async def test_user_flow_recovers_when_the_library_refuses_the_input(
    hass: HomeAssistant,
) -> None:
    """The library can refuse before it sends anything."""
    result = await _start_user_flow(hass)
    with (
        patch(CONNECTION, side_effect=[PorscheExceptionError("bad input"), _login()]),
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["errors"] == {"base": "cannot_connect"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_EMAIL


async def test_user_flow_refuses_an_account_that_is_already_set_up(
    hass: HomeAssistant,
) -> None:
    _existing_entry(hass)
    result = await _start_user_flow(hass)
    with patch(CONNECTION, return_value=_login()) as connection:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL.upper(), CONF_PASSWORD: "pw"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    connection.assert_not_called()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_user_flow_refuses_an_account_being_set_up_elsewhere(
    hass: HomeAssistant,
) -> None:
    first = await _start_user_flow(hass)
    second = await _start_user_flow(hass)
    with patch(CONNECTION, return_value=_captcha()):
        # The first flow now waits on its captcha, with the account as unique ID.
        first = await hass.config_entries.flow.async_configure(
            first["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert first["step_id"] == "captcha"

        second = await hass.config_entries.flow.async_configure(
            second["flow_id"], user_input=dict(CREDENTIALS)
        )

    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"


async def test_empty_form_is_refused_by_the_schema(hass: HomeAssistant) -> None:
    """Both fields are required: an empty submit never reaches the login."""
    result = await _start_user_flow(hass)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})


# -- captcha -------------------------------------------------------------------


async def test_captcha_resumes_the_login_it_interrupted(hass: HomeAssistant) -> None:
    result = await _start_user_flow(hass)
    with (
        patch(CONNECTION, side_effect=[_captcha(), _login(NEW_TOKEN)]) as connection,
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "captcha"
        # Enlarged for readability, on a white background.
        assert 'width="300" height="100"' in _shown_captcha(result)

        # Opening the step again shows the same captcha.
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        assert "first" in _shown_captcha(result)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "ABC12"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_EMAIL
    # Only the account, the password and the token are stored.
    assert result["data"] == {**CREDENTIALS, CONF_ACCESS_TOKEN: NEW_TOKEN}
    # Both logins go through the same HTTP client: the session is in its cookies.
    first, resumed = connection.call_args_list
    assert resumed.kwargs["captcha_code"] == "ABC12"
    assert resumed.kwargs["state"] == "state-first"
    assert resumed.kwargs["code_verifier"] == "verifier-first"
    assert resumed.kwargs["async_client"] is first.kwargs["async_client"]


async def test_second_captcha_is_answered_with_its_own_login(
    hass: HomeAssistant,
) -> None:
    result = await _start_user_flow(hass)
    with (
        patch(
            CONNECTION, side_effect=[_captcha("first"), _captcha("second"), _login()]
        ) as connection,
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "ONE"}
        )
        assert result["step_id"] == "captcha"
        assert "second" in _shown_captcha(result)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "TWO"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_EMAIL
    last = connection.call_args.kwargs
    assert last["captcha_code"] == "TWO"
    assert last["state"] == "state-second"
    assert last["code_verifier"] == "verifier-second"


@pytest.mark.parametrize(("failure", "error"), ERRORS)
async def test_captcha_flow_recovers_from_a_refused_code(
    hass: HomeAssistant, failure: Exception, error: str
) -> None:
    """A refused captcha is spent: the next try is a new login (#23)."""
    not_a_data_uri = _captcha()
    not_a_data_uri.get_token.side_effect.captcha = "https://example.invalid/c.png"
    result = await _start_user_flow(hass)
    with (
        patch(
            CONNECTION,
            side_effect=[_captcha(), _login(failure), not_a_data_uri, _login()],
        ) as connection,
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "WRONG"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": error}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        # The new login does not replay the spent captcha.
        fresh = connection.call_args.kwargs
        assert fresh["captcha_code"] is None
        assert fresh["state"] is None
        assert fresh["code_verifier"] is None
        assert result["step_id"] == "captcha"
        # Not a data URI: shown as it is.
        placeholders = result["description_placeholders"]
        assert "example.invalid/c.png" in placeholders["captcha_img"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "RIGHT"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TEST_EMAIL


async def test_captcha_that_is_not_base64_is_shown_untouched(
    hass: HomeAssistant,
) -> None:
    odd = _captcha()
    odd.get_token.side_effect.captcha = "data:image/png;base64,not-base64!"
    result = await _start_user_flow(hass)
    with patch(CONNECTION, return_value=odd):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )

    assert result["step_id"] == "captcha"
    assert "not-base64!" in result["description_placeholders"]["captcha_img"]
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_the_http_client_of_the_flow_is_closed_with_it(
    hass: HomeAssistant,
) -> None:
    result = await _start_user_flow(hass)
    with (
        patch(CONNECTION, return_value=_login()),
        patch(SETUP_ENTRY, return_value=None),
        patch(
            "custom_components.porscheconnect.config_flow.async_close_porsche_client"
        ) as close,
    ):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=dict(CREDENTIALS)
        )
        await hass.async_block_till_done()

    close.assert_called_once()


# -- reauthentication and reconfiguration ----------------------------------------


async def _start(hass: HomeAssistant, entry: MockConfigEntry, source: str) -> dict:
    """Start the flow the way Home Assistant does, and check its first form."""
    if source == config_entries.SOURCE_REAUTH:
        result = await entry.start_reauth_flow(hass)
        step = "reauth_confirm"
    else:
        result = await entry.start_reconfigure_flow(hass)
        step = "reconfigure"
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step
    # The account is shown, never asked: it cannot change in these flows.
    assert result["description_placeholders"]["email"] == TEST_EMAIL
    assert list(result["data_schema"].schema) == [CONF_PASSWORD]
    return result


SOURCES = [
    (config_entries.SOURCE_REAUTH, "reauth_confirm", "reauth_successful"),
    (config_entries.SOURCE_RECONFIGURE, "reconfigure", "reconfigure_successful"),
]


@pytest.mark.parametrize(("source", "step", "reason"), SOURCES)
async def test_reauth_and_reconfigure_update_the_entry(
    hass: HomeAssistant, source: str, step: str, reason: str
) -> None:
    entry = _existing_entry(hass)
    result = await _start(hass, entry, source)
    with (
        patch(CONNECTION, return_value=_login(NEW_TOKEN)) as connection,
        patch(SETUP_ENTRY, return_value=None) as setup_entry,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data == {
        CONF_EMAIL: TEST_EMAIL,
        CONF_PASSWORD: "new-password",
        CONF_ACCESS_TOKEN: NEW_TOKEN,
    }
    assert entry.unique_id == TEST_EMAIL
    assert connection.call_args.kwargs["email"] == TEST_EMAIL
    assert connection.call_args.kwargs["password"] == "new-password"
    # The entry is reloaded with the new password.
    assert len(setup_entry.mock_calls) == 1
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize(("failure", "error"), ERRORS)
@pytest.mark.parametrize(("source", "step", "reason"), SOURCES)
async def test_reauth_and_reconfigure_recover_from_an_error(
    hass: HomeAssistant,
    source: str,
    step: str,
    reason: str,
    failure: Exception,
    error: str,
) -> None:
    entry = _existing_entry(hass)
    result = await _start(hass, entry, source)
    with (
        patch(CONNECTION, side_effect=[_login(failure), _login(NEW_TOKEN)]),
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PASSWORD: "wrong"}
        )
        # The error is shown on the form the flow started with.
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == step
        assert result["errors"] == {"base": error}
        assert result["description_placeholders"]["email"] == TEST_EMAIL
        assert entry.data[CONF_PASSWORD] == "old-password"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PASSWORD: "right"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data[CONF_PASSWORD] == "right"
    assert entry.data[CONF_ACCESS_TOKEN] == NEW_TOKEN


@pytest.mark.parametrize(("source", "step", "reason"), SOURCES)
async def test_reauth_and_reconfigure_go_through_a_captcha(
    hass: HomeAssistant, source: str, step: str, reason: str
) -> None:
    entry = _existing_entry(hass)
    result = await _start(hass, entry, source)
    with (
        patch(
            CONNECTION,
            side_effect=[
                _captcha(),
                _login(PorscheWrongCredentialsError("wrong code")),
                _captcha("second"),
                _login(NEW_TOKEN),
            ],
        ),
        patch(SETUP_ENTRY, return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PASSWORD: "new-password"}
        )
        assert result["step_id"] == "captcha"

        # A refused code leads back to the password form, not to the user form.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "WRONG"}
        )
        assert result["step_id"] == step
        assert result["errors"] == {"base": "invalid_auth"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_PASSWORD: "new-password"}
        )
        assert "second" in _shown_captcha(result)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "RIGHT"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_ACCESS_TOKEN] == NEW_TOKEN
    assert CONF_CAPTCHA_CODE not in entry.data


async def test_reauth_does_not_block_a_reconfigure_of_the_same_entry(
    hass: HomeAssistant,
) -> None:
    """Both can be open at once; each ends on its own."""
    entry = _existing_entry(hass)
    reconfigure = await _start(hass, entry, config_entries.SOURCE_RECONFIGURE)
    reauth = await _start(hass, entry, config_entries.SOURCE_REAUTH)
    with (
        patch(CONNECTION, return_value=_login(NEW_TOKEN)),
        patch(SETUP_ENTRY, return_value=None),
    ):
        reauth = await hass.config_entries.flow.async_configure(
            reauth["flow_id"], user_input={CONF_PASSWORD: "from-reauth"}
        )
        await hass.async_block_till_done()

    assert reauth["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "from-reauth"
    hass.config_entries.flow.async_abort(reconfigure["flow_id"])


# -- strings ---------------------------------------------------------------------


def test_every_flow_step_and_outcome_is_translated() -> None:
    """A step, an error or an abort without strings shows nothing useful."""
    import json
    import re
    from pathlib import Path

    component = Path(__file__).parent.parent / "custom_components/porscheconnect"
    source = (component / "config_flow.py").read_text()
    # async_step_reauth only hands over to reauth_confirm: it shows no form.
    steps = set(re.findall(r"async def async_step_(\w+)", source)) - {"reauth"}
    assert steps == {"user", "captcha", "reauth_confirm", "reconfigure"}
    errors = set(re.findall(r'errors\["base"\] = "(\w+)"', source))
    assert errors == {"invalid_auth", "cannot_connect", "unknown"}

    for strings in (component / "strings.json", *component.glob("translations/*.json")):
        config = json.loads(strings.read_text())["config"]
        assert set(config["step"]) == steps, strings.name
        assert set(config["error"]) == errors, strings.name
        assert set(config["abort"]) == {
            "already_configured",
            "already_in_progress",
            "reauth_successful",
            "reconfigure_successful",
        }, strings.name
        for step in config["step"].values():
            # Every field has a label and a help text.
            assert set(step["data"]) == set(step["data_description"]), strings.name


def test_translations_are_complete_and_used_keys_exist() -> None:
    """Every language has the keys of strings.json, and the code only uses keys that exist."""
    import json
    import re
    from pathlib import Path

    component = Path(__file__).parent.parent / "custom_components/porscheconnect"

    def keys(node: object, prefix: str = "") -> set[str]:
        if not isinstance(node, dict):
            return {prefix}
        return {k for name, child in node.items() for k in keys(child, f"{prefix}.{name}")}

    strings = json.loads((component / "strings.json").read_text())
    for translation in component.glob("translations/*.json"):
        assert keys(json.loads(translation.read_text())) == keys(strings), translation.name

    source = "".join(p.read_text() for p in component.glob("*.py"))
    used = set(re.findall(r'translation_key="(\w+)"', source))
    known = set(strings["exceptions"]) | {
        key for platform in strings["entity"].values() for key in platform
    } | set(strings["issues"]) | {"location"}
    assert used <= known, used - known
