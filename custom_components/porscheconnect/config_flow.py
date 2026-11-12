"""Config flow for Porsche Connect integration."""

from __future__ import annotations

import base64
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import probatio as vol
from homeassistant import exceptions
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)

from . import async_close_porsche_client, async_create_porsche_client
from .const import CONF_CAPTCHA_CODE, DOMAIN

if TYPE_CHECKING:
    import httpx2

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)
# Reauthentication and reconfiguration keep the account: only the password.
STEP_PASSWORD_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR}
)
STEP_CAPTCHA_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPTCHA_CODE): TextSelector(
            TextSelectorConfig(autocomplete="off")
        )
    }
)


class CaptchaRequired(exceptions.HomeAssistantError):
    """Porsche wants a captcha before it goes on with the login."""

    def __init__(self, err: PorscheCaptchaRequiredError) -> None:
        """Keep what is needed to resume this login with the captcha code."""
        super().__init__("Captcha required")
        self.captcha = err.captcha or ""
        self.state = err.state
        self.code_verifier = err.code_verifier


async def async_login(
    client: httpx2.AsyncClient,
    email: str,
    password: str,
    captcha: CaptchaRequired | None = None,
    captcha_code: str | None = None,
) -> dict[str, Any]:
    """Log in to Porsche and return the token.

    With a captcha and the code the user read, resume the login it interrupted.
    Raises CaptchaRequired, InvalidAuth or CannotConnect; anything else is a
    bug and is left to the caller.
    """
    resumed = captcha if captcha_code else None
    try:
        connection = Connection(
            email=email,
            password=password,
            captcha_code=captcha_code if resumed else None,
            state=resumed.state if resumed else None,
            # Auth0 enforces PKCE: the verifier of the interrupted login must
            # come back with the captcha code, or the resume is rejected.
            code_verifier=resumed.code_verifier if resumed else None,
            token={},
            async_client=client,
        )
        token: dict[str, Any] = await connection.get_token()
    except PorscheCaptchaRequiredError as err:
        raise CaptchaRequired(err) from err
    except PorscheWrongCredentialsError as err:
        raise InvalidAuth from err
    except PorscheExceptionError as err:
        _LOGGER.debug("Could not log in to Porsche Connect: %s", err)
        raise CannotConnect from err
    return token


class PorscheConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Porsche Connect."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialise the flow."""
        self._email = ""
        self._password = ""
        # The captcha Porsche asked for, and the login it belongs to.
        self._captcha: CaptchaRequired | None = None
        self._client: httpx2.AsyncClient | None = None

    @callback
    def _get_http_client(self) -> httpx2.AsyncClient:
        """Return the flow's HTTP client: the captcha resumes the same session."""
        if self._client is None:
            self._client = async_create_porsche_client(self.hass)
        return self._client

    @callback
    def async_remove(self) -> None:
        """Close the HTTP client when the flow ends."""
        if self._client is not None:
            self.hass.async_create_task(async_close_porsche_client(self._client))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account, then log in."""
        if user_input is None:
            return self._async_show_credentials_form()

        # Normalised, so that Foo@Bar.com and foo@bar.com are one account.
        self._email = user_input[CONF_EMAIL].strip().lower()
        self._password = user_input[CONF_PASSWORD]
        await self.async_set_unique_id(self._email)
        self._abort_if_unique_id_configured()
        return await self._async_login()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Porsche refused the stored credentials: ask for the password again."""
        self._email = entry_data[CONF_EMAIL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password of the account of the entry."""
        if user_input is None:
            return self._async_show_credentials_form()
        self._password = user_input[CONF_PASSWORD]
        return await self._async_login()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the password of an existing entry."""
        if user_input is None:
            self._email = self._get_reconfigure_entry().data[CONF_EMAIL]
            return self._async_show_credentials_form()
        self._password = user_input[CONF_PASSWORD]
        return await self._async_login()

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Resume the login with the captcha the user read."""
        if user_input is None:
            return self._async_show_captcha_form()
        return await self._async_login(user_input[CONF_CAPTCHA_CODE])

    async def _async_login(self, captcha_code: str | None = None) -> ConfigFlowResult:
        """Log in, then finish the flow, ask for a captcha or show the error."""
        captcha = self._captcha
        errors: dict[str, str] = {}
        try:
            token = await async_login(
                self._get_http_client(),
                self._email,
                self._password,
                captcha,
                captcha_code,
            )
        except CaptchaRequired as err:
            self._captcha = err
            return self._async_show_captcha_form()
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self._async_finish(token)
        # A refused captcha and its login are spent: the next try starts a new
        # login from the credentials, which asks for a fresh captcha (#23).
        return self._async_show_credentials_form(errors)

    @callback
    def _async_finish(self, token: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry, or update the one being reauthenticated/reconfigured."""
        data = {
            CONF_EMAIL: self._email,
            CONF_PASSWORD: self._password,
            CONF_ACCESS_TOKEN: token,
        }
        # The account cannot change here: these two flows never ask for it.
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=self._email, data=data)

    @callback
    def _async_show_credentials_form(
        self, errors: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Show the form the flow started with, with the errors of the login."""
        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            return self.async_show_form(
                step_id=(
                    "reauth_confirm" if self.source == SOURCE_REAUTH else "reconfigure"
                ),
                data_schema=STEP_PASSWORD_DATA_SCHEMA,
                description_placeholders={"email": self._email},
                errors=errors,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, {CONF_EMAIL: self._email}
            ),
            errors=errors,
        )

    @callback
    def _async_show_captcha_form(self) -> ConfigFlowResult:
        """Show the captcha picture Porsche sent."""
        assert self._captcha is not None  # noqa: S101 - set before every call
        image = self._captcha.captcha
        # Best-effort upscaling of the Auth0 SVG captcha for readability. It is
        # normally a "data:image/svg+xml;base64,<payload>" data URI, but
        # tolerate other shapes (PNG/ACUL, plain URL) instead of crashing.
        if "," in image:
            header, payload = image.split(",", 1)
            try:
                svg = base64.b64decode(payload).replace(
                    b'width="150" height="50"',
                    b'width="300" height="100" style="background-color:white"',
                )
                image = header + "," + base64.b64encode(svg).decode("ascii")
            except ValueError:
                pass  # not base64: leave the captcha source untouched

        return self.async_show_form(
            step_id="captcha",
            data_schema=STEP_CAPTCHA_DATA_SCHEMA,
            description_placeholders={"captcha_img": f'<img src="{image}" />'},
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
