"""Constants for the Porsche Connect integration."""

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
    "sensor",
    "binary_sensor",
    "device_tracker",
    "number",
    "switch",
    "button",
    "lock",
    "image",
    "climate",
]
