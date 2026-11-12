"""Constants for the Porsche Connect integration."""

from homeassistant.const import Platform

DOMAIN = "porscheconnect"
DEFAULT_SCAN_INTERVAL = 1920

CONF_CAPTCHA_CODE = "captcha_code"
CONF_CODE_VERIFIER = "code_verifier"
CONF_OAUTH_STATE = "state"

# Single-use secrets of an in-flight login: they belong to the flow, never to
# the stored config entry.
TRANSIENT_AUTH_FIELDS = frozenset(
    {CONF_CAPTCHA_CODE, CONF_CODE_VERIFIER, CONF_OAUTH_STATE},
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DEVICE_TRACKER,
    Platform.IMAGE,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]
