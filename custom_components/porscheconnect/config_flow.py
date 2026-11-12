"""Config flow for Porsche Connect integration."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

import probatio as vol
from homeassistant import exceptions
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from pyporscheconnectapi.connection import Connection
from pyporscheconnectapi.exceptions import (
    PorscheCaptchaRequiredError,
    PorscheExceptionError,
    PorscheWrongCredentialsError,
)

from . import async_create_porsche_client
from .const import (
    CONF_CAPTCHA_CODE,
    CONF_CODE_VERIFIER,
    CONF_OAUTH_STATE,
    DOMAIN,
    TRANSIENT_AUTH_FIELDS,
)

if TYPE_CHECKING:
    import httpx2

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({CONF_EMAIL: str, CONF_PASSWORD: str})
CHANGE_PASSWORD_SCHEMA = vol.Schema({CONF_PASSWORD: str})


async def validate_input(
    client: httpx2.AsyncClient, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    token: dict[str, Any] = {}
    try:
        conn = Connection(
            email=data[CONF_EMAIL],
            password=data[CONF_PASSWORD],
            captcha_code=data.get(CONF_CAPTCHA_CODE),
            state=data.get(CONF_OAUTH_STATE),
            # Auth0 enforces PKCE: the verifier of the interrupted login must
            # come back with the captcha code, or the resume is rejected.
            code_verifier=data.get(CONF_CODE_VERIFIER),
            token=token,
            # httpx2 is Home Assistant's httpx; the library is annotated for httpx.
            async_client=client,  # type: ignore[arg-type]
        )
    except PorscheExceptionError as exc:
        _LOGGER.debug("Could not create connection: %s", exc)
        raise InvalidAuth from exc

    _LOGGER.debug("Attempting login")
    try:
        token = await conn.get_token()
    except PorscheCaptchaRequiredError as exc:
        _LOGGER.info("Captcha required to log in")
        return {
            "email": data[CONF_EMAIL],
            "password": data[CONF_PASSWORD],
            "captcha": exc.captcha,
            CONF_OAUTH_STATE: exc.state,
            CONF_CODE_VERIFIER: exc.code_verifier,
        }
    except PorscheWrongCredentialsError as exc:
        _LOGGER.info("Wrong credentials.")
        raise InvalidAuth from exc
    except PorscheExceptionError as exc:
        _LOGGER.info("Could not log in to Porsche Connect: %s", exc.message)
        raise CannotConnect from exc
    except Exception as exc:
        _LOGGER.exception("Unexpected error during login")
        raise CannotConnect from exc

    return {"title": data[CONF_EMAIL], CONF_ACCESS_TOKEN: token}


class PorscheConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Porsche Connect."""

    VERSION = 2

    email: str | None = None
    password: str | None = None
    captcha: str | None = None
    state: str | None = None
    code_verifier: str | None = None
    _client: httpx2.AsyncClient | None = None
    _existing_entry_data: dict[str, Any]

    @callback
    def _get_http_client(self) -> httpx2.AsyncClient:
        """Return the flow's HTTP client, shared by the login and captcha steps."""
        if self._client is None:
            self._client = async_create_porsche_client(self.hass)
        return self._client

    @callback
    def _get_entry_for_current_flow(self) -> ConfigEntry | None:
        """Return the existing entry for reauth/reconfigure flows."""
        if self.source == SOURCE_REAUTH:
            return self._get_reauth_entry()
        if self.source == SOURCE_RECONFIGURE:
            return self._get_reconfigure_entry()
        return None

    @callback
    def _get_expected_unique_id(self) -> str | None:
        """Return the account identifier for the current flow.

        Older entries may not have a unique_id yet, so fall back to the stored email.
        """
        if entry := self._get_entry_for_current_flow():
            return entry.unique_id or entry.data.get(CONF_EMAIL)
        return self.unique_id

    @callback
    def _abort_if_account_mismatch(self) -> None:
        """Abort if reauth/reconfigure targets a different account."""
        expected_unique_id = self._get_expected_unique_id()
        if expected_unique_id is None or self.unique_id == expected_unique_id:
            return
        self._abort_if_unique_id_mismatch()

    @callback
    def _get_entry_data(
        self,
        email: str,
        password: str,
        access_token: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the config entry data, without the in-flight auth secrets.

        Those are single-use: keeping them in the entry only makes a later
        login replay a stale captcha state.
        """
        entry = self._get_entry_for_current_flow()
        entry_data = dict(entry.data) if entry else {}
        for field in TRANSIENT_AUTH_FIELDS:
            entry_data.pop(field, None)
        entry_data.update(
            {
                CONF_EMAIL: email,
                CONF_PASSWORD: password,
                CONF_ACCESS_TOKEN: access_token,
            },
        )
        return entry_data

    @callback
    def _async_finish(
        self, credentials: dict[str, Any], info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create the entry, or update the one being reauthenticated/reconfigured."""
        entry_data = self._get_entry_data(
            credentials[CONF_EMAIL],
            credentials[CONF_PASSWORD],
            info.get(CONF_ACCESS_TOKEN),
        )
        if entry := self._get_entry_for_current_flow():
            self._abort_if_account_mismatch()
            return self.async_update_reload_and_abort(
                entry,
                unique_id=self.unique_id,
                data=entry_data,
            )
        return self.async_create_entry(title=info["title"], data=entry_data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
            )

        errors = {}
        _LOGGER.debug("Validating input.")

        # Normalize the email so case variants (foo@bar.com vs FOO@BAR.COM)
        # don't create duplicate accounts.
        unique_id = user_input[CONF_EMAIL].strip().lower()
        user_input[CONF_EMAIL] = unique_id
        await self.async_set_unique_id(unique_id)
        if self.source not in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            self._abort_if_unique_id_configured()

        try:
            info = await validate_input(self._get_http_client(), user_input)
            if info.get("captcha") and info.get(CONF_OAUTH_STATE):
                self.email = info.get("email")
                self.password = info.get("password")
                self.captcha = info.get("captcha")
                self.state = info.get(CONF_OAUTH_STATE)
                self.code_verifier = info.get(CONF_CODE_VERIFIER)
                return self._async_form_captcha()
            return self._async_finish(user_input, info)

        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration by re-auth."""
        await self.async_set_unique_id(
            self._get_expected_unique_id(),
            raise_on_progress=False,
        )
        return await self.async_step_user()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initialized by the user."""
        self._existing_entry_data = dict(self._get_reconfigure_entry().data)
        await self.async_set_unique_id(
            self._get_expected_unique_id(),
            raise_on_progress=False,
        )
        return await self.async_step_change_password()

    async def async_step_change_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the change password step."""
        if user_input is not None:
            return await self.async_step_user(
                {
                    CONF_EMAIL: self._existing_entry_data[CONF_EMAIL],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
            )

        return self.async_show_form(
            step_id="change_password",
            data_schema=CHANGE_PASSWORD_SCHEMA,
            description_placeholders={
                CONF_EMAIL: self._existing_entry_data[CONF_EMAIL],
            },
        )

    async def async_step_captcha(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Captcha verification step."""
        if user_input is not None:
            user_input = {
                CONF_EMAIL: self.email,
                CONF_PASSWORD: self.password,
                CONF_CAPTCHA_CODE: user_input[CONF_CAPTCHA_CODE],
                CONF_OAUTH_STATE: self.state,
                CONF_CODE_VERIFIER: self.code_verifier,
            }
            errors = {}
            try:
                info = await validate_input(self._get_http_client(), user_input)

                # Handle case where another captcha is required
                if info.get("captcha") and info.get(CONF_OAUTH_STATE):
                    self.captcha = info.get("captcha")
                    self.state = info.get(CONF_OAUTH_STATE)
                    self.code_verifier = info.get(CONF_CODE_VERIFIER)
                    return self._async_form_captcha()

                return self._async_finish(user_input, info)

            except (InvalidAuth, CannotConnect) as err:
                # The captcha and its login transaction are spent: showing the
                # same image again can only fail. Start over from the
                # credentials, which also asks for a fresh captcha (#23).
                errors["base"] = (
                    "invalid_auth" if isinstance(err, InvalidAuth) else "cannot_connect"
                )
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.add_suggested_values_to_schema(
                        STEP_USER_DATA_SCHEMA, {CONF_EMAIL: self.email}
                    ),
                    errors=errors,
                )

        return self._async_form_captcha()

    @callback
    def _async_form_captcha(
        self,
    ) -> ConfigFlowResult:
        """Captcha verification form."""
        # Best-effort upscaling of the Auth0 SVG captcha for readability. It is
        # normally a "data:image/svg+xml;base64,<payload>" data URI, but
        # tolerate other shapes (PNG/ACUL, plain URL) instead of crashing.
        if isinstance(self.captcha, str) and "," in self.captcha:
            header, payload = self.captcha.split(",", 1)
            try:
                svg = base64.b64decode(payload)
                svg = svg.replace(
                    b'width="150" height="50"',
                    b'width="300" height="100" style="background-color:white"',
                )
                self.captcha = header + "," + base64.b64encode(svg).decode("ascii")
            except ValueError:
                pass  # not base64 — leave the captcha source untouched

        return self.async_show_form(
            step_id="captcha",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CAPTCHA_CODE, default=vol.UNDEFINED): str,
                },
            ),
            description_placeholders={
                "captcha_img": f'<img src="{self.captcha}" />',
            },
        )


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate the Porsche login could not be completed."""
