"""Tests for the Porsche Connect config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)
from pytest_homeassistant.common import MockConfigEntry

from custom_components.porscheconnect.const import (
    CONF_CAPTCHA_CODE,
    CONF_CODE_VERIFIER,
    CONF_OAUTH_STATE,
    DOMAIN,
    TRANSIENT_AUTH_FIELDS,
)

from .conftest import TEST_EMAIL, TEST_PASSWORD, TEST_TOKEN


def _connection_with_token(token=TEST_TOKEN):
    """Return a MagicMock that yields a token on get_token()."""
    instance = MagicMock()
    instance.get_token = AsyncMock(return_value=token)
    instance.token = token
    return instance


async def test_user_step_happy_path(hass: HomeAssistant) -> None:
    """User submits valid credentials → an entry is created."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_EMAIL
    assert result["data"][CONF_EMAIL] == TEST_EMAIL
    assert result["data"][CONF_PASSWORD] == TEST_PASSWORD
    assert result["data"][CONF_ACCESS_TOKEN] == TEST_TOKEN

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    # Unique id should be the email (the parallel structural fix lower-cases it).
    assert entries[0].unique_id in {TEST_EMAIL, TEST_EMAIL.lower()}


async def test_user_step_wrong_credentials(hass: HomeAssistant) -> None:
    """Wrong creds → form re-shown with `invalid_auth`."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    instance = MagicMock()
    instance.get_token = AsyncMock(side_effect=PorscheWrongCredentialsError("nope"))
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=instance,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: "bad"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_step_cannot_connect(hass: HomeAssistant) -> None:
    """An API error that is not about the credentials → `cannot_connect`."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    instance = MagicMock()
    instance.get_token = AsyncMock(side_effect=PorscheExceptionError(503))
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=instance,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_already_configured(hass: HomeAssistant) -> None:
    """Submitting the same email twice → flow aborts with already_configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL.lower(),
        data={
            CONF_EMAIL: TEST_EMAIL,
            CONF_PASSWORD: TEST_PASSWORD,
            CONF_ACCESS_TOKEN: TEST_TOKEN,
        },
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_step_captcha_required(hass: HomeAssistant) -> None:
    """Captcha required → flow transitions to the captcha step.

    The flow's `_async_form_captcha` decodes the captcha as a base64 SVG, so
    feed it a real (but tiny) base64-encoded SVG payload.
    """
    import base64

    svg = b'<svg width="150" height="50"></svg>'
    captcha_uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")

    err = PorscheCaptchaRequiredError("captcha please")
    err.captcha = captcha_uri
    err.state = "state-token-xyz"

    instance = MagicMock()
    instance.get_token = AsyncMock(side_effect=err)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=instance,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "captcha"


async def test_reauth_flow_updates_entry(hass: HomeAssistant) -> None:
    """Reauth on an existing entry should update credentials in place."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL.lower(),
        data={
            CONF_EMAIL: TEST_EMAIL,
            CONF_PASSWORD: "old-password",
            CONF_ACCESS_TOKEN: {"access_token": "old"},
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=dict(entry.data),
    )
    assert result["type"] == FlowResultType.FORM

    new_token = {"access_token": "fresh", "expires_in": 3600}
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(new_token),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: "new-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] in {"reauth_successful", "reconfigure_successful"}
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_ACCESS_TOKEN] == new_token


async def test_captcha_step_resumes_with_code_verifier(hass: HomeAssistant) -> None:
    """The solved captcha must be replayed with the PKCE verifier of the
    interrupted login — Auth0 rejects the resume without it — and none of
    those single-use secrets may end up in the config entry.
    """
    import base64

    svg = b'<svg width="150" height="50"></svg>'
    captcha_uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")

    err = PorscheCaptchaRequiredError("captcha please")
    err.captcha = captcha_uri
    err.state = "state-token-xyz"
    err.code_verifier = "verifier-abc"

    challenged = MagicMock()
    challenged.get_token = AsyncMock(side_effect=err)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=challenged,
    ) as first_cls:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )
    assert result["step_id"] == "captcha"
    client = first_cls.call_args.kwargs["async_client"]
    assert client.headers["Accept-Encoding"] == "gzip, deflate"

    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(),
    ) as connection_cls:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CAPTCHA_CODE: "SOLVED"},
        )
        await hass.async_block_till_done()

    kwargs = connection_cls.call_args.kwargs
    # Same client as the first step: keeps the Auth0 transaction cookies.
    assert kwargs["async_client"] is client
    assert kwargs[CONF_CAPTCHA_CODE] == "SOLVED"
    assert kwargs[CONF_OAUTH_STATE] == "state-token-xyz"
    assert kwargs[CONF_CODE_VERIFIER] == "verifier-abc"

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert TRANSIENT_AUTH_FIELDS.isdisjoint(result["data"])
    assert result["data"][CONF_ACCESS_TOKEN] == TEST_TOKEN


async def test_captcha_step_error_restarts_login(hass: HomeAssistant) -> None:
    """A refused captcha step goes back to the credentials, not to the spent
    captcha, and the next try starts a new login with a fresh captcha (#23).
    """
    import base64

    def challenged(state: str) -> MagicMock:
        err = PorscheCaptchaRequiredError("captcha please")
        err.captcha = "data:image/svg+xml;base64," + base64.b64encode(
            f"<svg>{state}</svg>".encode()
        ).decode("ascii")
        err.state = state
        err.code_verifier = f"verifier-{state}"
        instance = MagicMock()
        instance.get_token = AsyncMock(side_effect=err)
        return instance

    refused = MagicMock()
    refused.get_token = AsyncMock(side_effect=PorscheWrongCredentialsError("nope"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        side_effect=[challenged("first"), refused, challenged("second")],
    ) as connection_cls:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )
        assert result["step_id"] == "captcha"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_CAPTCHA_CODE: "WRONG"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "invalid_auth"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )

    assert result["step_id"] == "captcha"
    assert "second" in base64.b64decode(
        result["description_placeholders"]["captcha_img"].split(",", 1)[1].split('"')[0]
    ).decode()
    # The new login does not replay the spent captcha transaction.
    last = connection_cls.call_args.kwargs
    assert last[CONF_CAPTCHA_CODE] is None
    assert last[CONF_OAUTH_STATE] is None


def _existing_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_EMAIL.lower(),
        data={
            CONF_EMAIL: TEST_EMAIL,
            CONF_PASSWORD: "old-password",
            CONF_ACCESS_TOKEN: {"access_token": "old"},
        },
    )
    entry.add_to_hass(hass)
    return entry


def _captcha_connection(payload: str = "abc") -> MagicMock:
    """A connection whose login is interrupted by a captcha."""
    err = PorscheCaptchaRequiredError("captcha please")
    err.captcha = "data:image/png;base64," + payload
    err.state = "state-token"
    err.code_verifier = "verifier"
    instance = MagicMock()
    instance.get_token = AsyncMock(side_effect=err)
    return instance


async def test_reconfigure_flow_changes_password(hass: HomeAssistant) -> None:
    """Reconfigure asks for the new password only and keeps the account."""
    entry = _existing_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "change_password"
    assert result["description_placeholders"] == {CONF_EMAIL: TEST_EMAIL}

    new_token = {"access_token": "fresh", "expires_in": 3600}
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(new_token),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_PASSWORD: "new-password"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_EMAIL] == TEST_EMAIL
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_ACCESS_TOKEN] == new_token


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (config_entries.SOURCE_REAUTH, "reauth_successful"),
        (config_entries.SOURCE_RECONFIGURE, "reconfigure_successful"),
    ],
)
async def test_existing_entry_updated_after_two_captchas(
    hass: HomeAssistant, source: str, reason: str
) -> None:
    """Reauth and reconfigure also finish through the captcha step, even when
    Porsche asks for a second captcha, and tolerate a captcha that is no SVG.
    """
    entry = _existing_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )

    new_token = {"access_token": "fresh", "expires_in": 3600}
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        side_effect=[
            _captcha_connection(),
            _captcha_connection("def"),
            _connection_with_token(new_token),
        ],
    ):
        first_input = (
            {CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: "new-password"}
            if source == config_entries.SOURCE_REAUTH
            else {CONF_PASSWORD: "new-password"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=first_input
        )
        assert result["step_id"] == "captcha"
        # Not base64: the image source is passed through untouched.
        assert "base64,abc" in result["description_placeholders"]["captcha_img"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "ONE"}
        )
        assert result["step_id"] == "captcha"
        assert "base64,def" in result["description_placeholders"]["captcha_img"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_CAPTCHA_CODE: "TWO"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_ACCESS_TOKEN] == new_token
    assert TRANSIENT_AUTH_FIELDS.isdisjoint(entry.data)


async def test_reauth_with_another_account_is_refused(hass: HomeAssistant) -> None:
    """Reauth must not silently turn the entry into a different account."""
    entry = _existing_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: "someone@example.com", CONF_PASSWORD: "x"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data[CONF_PASSWORD] == "old-password"


@pytest.mark.parametrize(
    ("connection", "error"),
    [
        (PorscheExceptionError("bad input"), "invalid_auth"),
        (_connection_with_token(), "cannot_connect"),
    ],
)
async def test_user_step_reports_other_login_failures(
    hass: HomeAssistant, connection, error: str
) -> None:
    """A refused connection and an unexpected error both come back as a form."""
    if error == "cannot_connect":
        connection.get_token = AsyncMock(side_effect=RuntimeError("boom"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        side_effect=[connection],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_reauth_of_an_entry_with_capitals_in_its_unique_id(
    hass: HomeAssistant,
) -> None:
    """Entries made by the original integration keep the email as typed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="Tester@Example.com",
        data={CONF_EMAIL: "Tester@Example.com", CONF_PASSWORD: "old-password"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    with patch(
        "custom_components.porscheconnect.config_flow.Connection",
        return_value=_connection_with_token(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_EMAIL: "Tester@Example.com", CONF_PASSWORD: "new"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"


def test_every_flow_step_is_translated() -> None:
    """A step without strings shows an empty form."""
    import json
    import re
    from pathlib import Path

    component = Path(__file__).parent.parent / "custom_components/porscheconnect"
    steps = set(re.findall(r'step_id="(\w+)"', (component / "config_flow.py").read_text()))
    assert "change_password" in steps
    for strings in (component / "strings.json", *component.glob("translations/*.json")):
        translated = json.loads(strings.read_text())["config"]["step"]
        assert steps <= set(translated), strings.name


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
