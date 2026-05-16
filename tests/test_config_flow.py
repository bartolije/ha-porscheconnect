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
    PorscheWrongCredentialsError,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porscheconnect.const import DOMAIN

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
