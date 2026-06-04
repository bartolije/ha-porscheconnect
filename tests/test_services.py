"""Unit tests for the Porsche Connect services helpers.

The full service handlers need a hass instance and a device registry, which is
out of scope for a direct unit test. This file exercises the pure helper
`_resolve_climate_zone_kwargs` in isolation (issue #292 zone filtering) using a
lightweight vehicle stand-in — no hass setup.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.porscheconnect.services import (
    ATTR_FRONT_LEFT,
    ATTR_FRONT_RIGHT,
    ATTR_REAR_LEFT,
    ATTR_REAR_RIGHT,
    _resolve_climate_zone_kwargs,
)


def _vehicle(**zones) -> SimpleNamespace:
    """A vehicle stand-in whose CLIMATIZER_STATE advertises the given zones.

    `zones` maps camelCase API keys (frontLeft/...) to their enabled flag; the
    KEYS are what the helper treats as "supported", regardless of value.
    """
    return SimpleNamespace(
        vin="VIN1",
        data={"CLIMATIZER_STATE": {"climateZonesEnabled": dict(zones)}},
    )


def test_requested_and_supported_zone_is_returned():
    """A requested zone present in the payload comes back in the kwargs."""
    vehicle = _vehicle(frontLeft=False)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_LEFT: True})
    assert kwargs == {ATTR_FRONT_LEFT: True}


def test_unsupported_zone_requested_true_raises():
    """Enabling a zone the car doesn't have fails loudly."""
    vehicle = _vehicle(frontLeft=False)
    with pytest.raises(ServiceValidationError):
        _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_RIGHT: True})


def test_unsupported_zone_requested_false_is_skipped():
    """Disabling an unsupported zone is harmless: no error, not in kwargs."""
    vehicle = _vehicle(frontLeft=False)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_REAR_LEFT: False})
    assert kwargs == {}


def test_zone_not_requested_is_omitted():
    """A zone left unset (None) is omitted entirely from the kwargs."""
    vehicle = _vehicle(frontLeft=True, rearRight=True)
    kwargs = _resolve_climate_zone_kwargs(vehicle, {ATTR_FRONT_LEFT: True})
    assert kwargs == {ATTR_FRONT_LEFT: True}
    assert ATTR_REAR_RIGHT not in kwargs
    assert ATTR_FRONT_RIGHT not in kwargs
