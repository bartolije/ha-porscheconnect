# Porsche Connect for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![pre-commit][pre-commit-shield]][pre-commit]
[![Ruff][ruff-shield]][ruff]

[![hacs][hacs_badge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

Connect your Porsche Connect–enabled vehicle to Home Assistant. The integration
reads vehicle telemetry (state of charge, range, mileage, location, tire
pressure, doors/lids…) and exposes remote actions (climatisation, lock/unlock,
flash/honk, direct charging, target SoC) for cars that have an active Porsche
Connect subscription and are paired to a My Porsche account.

> This integration does **not** support *Porsche Car Connect* — that is a
> separate, older Porsche service with its own backend.

## Features

- Battery, charging, range, mileage, fuel level sensors
- Doors/lids, parking brake/light, privacy mode, remote access binary sensors
- Tire pressure status (per-tire attributes) when the vehicle has TPMS
- Vehicle location via `device_tracker` (suppressed when privacy mode is on)
- Vehicle images (front, side, rear, rear-top, top views)
- Door `lock` entity (unlock requires the S-PIN configured per-entity)
- Remote `switch` entities: climatisation, direct charging
- `number` entity: target state of charge
- `button` entities: flash indicators, honk-and-flash, refresh overview
- `climatisation_start` service action with seat-heating zone selection
- Multi-vehicle accounts are auto-discovered and added at runtime
- Captcha, reauth and reconfigure flows handled in the UI

## Supported vehicles

The list below tracks what the upstream `pyporscheconnectapi` library can talk
to. In practice, **only Porsche Connect–equipped vehicles (typically MY 2021+)
report data** — older cars may authenticate against the account but expose
empty `commands` / `measurements` payloads.

| Model              | Drivetrain | Connect entities | Charging entities | Climatisation | Lock | Location |
| ------------------ | ---------- | ---------------- | ----------------- | ------------- | ---- | -------- |
| Taycan             | BEV        | Yes              | Yes               | Yes           | Yes  | Yes      |
| Macan EV           | BEV        | Yes              | Yes               | Yes           | Yes  | Yes      |
| Cayenne (E3)       | PHEV / ICE | Yes              | PHEV only         | PHEV only     | Yes  | Yes      |
| Panamera (G2 PA)   | PHEV / ICE | Yes              | PHEV only         | PHEV only     | Yes  | Yes      |
| 911 (992)          | ICE        | Yes              | No                | No            | Yes  | Yes      |
| 718 Boxster/Cayman | ICE        | Yes              | No                | No            | Yes  | Yes      |

ICE-only cars naturally do not expose state-of-charge, charging or
electric-range entities. PHEVs expose both fuel-level and battery sensors.

To verify your specific model and equipment, see
<https://connect-store.porsche.com/> — select your car and check whether the
*Porsche Connect* services package is available.

## Supported entities and capabilities

Each entity is gated on a capability flag exposed by the vehicle object so the
integration only creates entities that the car can actually drive.

| Platform        | Entity / key                                                       | Capability gate                                          |
| --------------- | ------------------------------------------------------------------ | -------------------------------------------------------- |
| `sensor`        | `state_of_charge`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_target`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_status`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_rate`                                                    | `has_electric_drivetrain`                                |
| `sensor`        | `charging_power`                                                   | `has_electric_drivetrain`                                |
| `sensor`        | `charging_finished`                                                | `has_electric_drivetrain`                                |
| `sensor`        | `remaining_range_electric`                                         | `has_electric_drivetrain`                                |
| `sensor`        | `mileage`                                                          | `has_porsche_connect` (default)                          |
| `sensor`        | `remaining_range`                                                  | `has_ice_drivetrain`                                     |
| `sensor`        | `fuel_level`                                                       | `has_ice_drivetrain`                                     |
| `binary_sensor` | `parking_brake`                                                    | `has_porsche_connect`                                    |
| `binary_sensor` | `parking_light`                                                    | `has_porsche_connect`                                    |
| `binary_sensor` | `privacy_mode`                                                     | `has_porsche_connect`                                    |
| `binary_sensor` | `remote_access`                                                    | `has_porsche_connect`                                    |
| `binary_sensor` | `doors_and_lids`                                                   | `has_porsche_connect`                                    |
| `binary_sensor` | `tire_pressure_status`                                             | `has_tire_pressure_monitoring`                           |
| `device_tracker`| Vehicle location                                                   | `has_porsche_connect` and `privacy_mode == false`        |
| `image`         | `front_view`, `side_view`, `rear_view`, `rear_top_view`, `top_view`| Pictures returned by the API                             |
| `lock`          | Door lock                                                          | `has_porsche_connect` (unlock needs S-PIN)               |
| `switch`        | `climatise`                                                        | `has_remote_climatisation` and `has_remote_services`     |
| `switch`        | `direct_charging`                                                  | `has_direct_charge` and `has_remote_services`            |
| `number`        | `target_soc` (25–100 %, step 5)                                    | `has_electric_drivetrain` and `has_remote_services`      |
| `button`        | `flash_indicators`                                                 | `has_remote_services`                                    |
| `button`        | `honk_and_flash_indicators`                                        | `has_remote_services`                                    |
| `button`        | `get_current_overview`                                             | `has_remote_services` (forces a fresh pull from the car) |

The privacy mode flag is honoured by the vehicle itself — when the driver
enables privacy in the PCM, the `device_tracker` entity is not created.

## Installation

The integration is delivered as a [HACS](https://hacs.xyz) custom integration.

### HACS (recommended)

1. In HACS, open **Integrations**.
2. Search for **Porsche Connect** and select it.
3. Click **Download**, then **Restart Home Assistant**.
4. Go to **Settings → Devices & services → Add integration**, search
   **Porsche Connect**, and follow the configuration flow.

### Manual

1. Open the directory containing your `configuration.yaml`.
2. Create `custom_components/` if it does not exist.
3. Inside it, create `custom_components/porscheconnect/`.
4. Copy every file from `custom_components/porscheconnect/` in this repo into
   that folder.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**, search
   **Porsche Connect**, and follow the configuration flow.

## Configuration

The integration is configured exclusively through the Home Assistant UI.
There is **no YAML configuration** and **no options flow** — no additional
configuration parameters beyond the credentials below.

### Installation parameters (credentials)

| Field      | Required      | Notes                                                            |
| ---------- | ------------- | ---------------------------------------------------------------- |
| Email      | Yes           | Your Porsche ID email (same one you use for the Porsche app).    |
| Password   | Yes           | Your Porsche ID password.                                        |
| Captcha    | When prompted | If Porsche's login server demands a captcha, the flow shows a step with the SVG image and an input field. |

You must also have:

- An **active Porsche Connect subscription** on the car you want to control.
- The car **paired in the PCM** (Porsche Communication Management) using the
  pairing code shown by My Porsche / the Porsche app. Un-paired cars
  authenticate but return empty `commands` / `measurements` payloads.

The **S-PIN** (4-digit security PIN you set in the Porsche app) is not asked
at install time. It is provided per-`lock` entity as the standard Home
Assistant lock *default code* in the entity options, and is only needed for
*unlock*. Lock and other remote services do not require it.

### Reauth and reconfigure

- **Reauth** is triggered automatically when the API returns 401 / wrong
  credentials. Home Assistant shows a repair notification leading back to the
  login form.
- **Reconfigure** lets you update the password for an existing entry without
  removing and re-adding it (Settings → Devices & services → Porsche Connect →
  Configure).

## Services / Actions

### `porscheconnect.climatisation_start`

Starts remote climatisation of the passenger compartment with an optional
target temperature and per-seat heating selection.

#### Parameters

| Name          | Type     | Required | Default | Notes                                                              |
| ------------- | -------- | -------- | ------- | ------------------------------------------------------------------ |
| `vehicle`     | device   | yes      | —       | The Porsche Connect device the action targets.                     |
| `temperature` | number   | no       | 20 °C   | Target cabin temperature, 15–25 °C, 0.5 °C step.                   |
| `front_left`  | boolean  | no       | false   | Activate front-left seat heating if the car has that zone.         |
| `front_right` | boolean  | no       | false   | Activate front-right seat heating if the car has that zone.        |
| `rear_left`   | boolean  | no       | false   | Activate rear-left seat heating if the car has that zone.          |
| `rear_right`  | boolean  | no       | false   | Activate rear-right seat heating if the car has that zone.         |

#### Behavior on unsupported zones (issue #292)

The Porsche API only lists zones the car physically supports in
`CLIMATIZER_STATE.climateZonesEnabled`. Two cases:

- If you set an unsupported zone to **`false`**, the parameter is silently
  dropped — calling "off" on a zone the car doesn't have is harmless.
- If you set an unsupported zone to **`true`**, the service raises
  `ServiceValidationError` so the misconfiguration surfaces in your automation
  rather than silently doing nothing.

If the car does not advertise `has_remote_climatisation` at all (e.g. an ICE
911), the service raises `ServiceValidationError` before any API call is
issued.

#### Example call

```yaml
service: porscheconnect.climatisation_start
data:
  vehicle: 1a2b3c4d5e6f7890abcdef1234567890   # device id of the Porsche
  temperature: 21
  front_left: true
  front_right: true
```

## Examples

### Lovelace dashboard snippet

```yaml
type: entities
title: Taycan
entities:
  - entity: sensor.taycan_state_of_charge
  - entity: sensor.taycan_remaining_range_electric
  - entity: sensor.taycan_charging_status
  - entity: sensor.taycan_charging_power
  - entity: binary_sensor.taycan_doors_and_lids
  - entity: binary_sensor.taycan_tire_pressure_status
  - entity: lock.taycan_door_lock
  - entity: switch.taycan_remote_climatisation
  - entity: number.taycan_target_state_of_charge
  - entity: button.taycan_flash_indicators
```

### Pre-heat the cabin at 7 am on cold mornings

```yaml
alias: Porsche pre-heat on cold mornings
trigger:
  - platform: time
    at: "07:00:00"
condition:
  - condition: numeric_state
    entity_id: sensor.openweathermap_temperature
    below: 5
action:
  - service: porscheconnect.climatisation_start
    data:
      vehicle: 1a2b3c4d5e6f7890abcdef1234567890
      temperature: 22
      front_left: true
      front_right: true
mode: single
```

### Alert if doors are open more than five minutes after parking

```yaml
alias: Porsche door-open alert
trigger:
  - platform: state
    entity_id: binary_sensor.taycan_doors_and_lids
    to: "on"
    for: "00:05:00"
action:
  - service: notify.mobile_app_my_phone
    data:
      title: Porsche
      message: A door or lid has been open for five minutes.
mode: single
```

### Log charging sessions to a logbook

```yaml
alias: Log Porsche charging start
trigger:
  - platform: state
    entity_id: sensor.taycan_charging_status
    to: charging
action:
  - service: logbook.log
    data:
      name: Taycan
      message: "Charging started at {{ states('sensor.taycan_state_of_charge') }} %"
      entity_id: sensor.taycan_state_of_charge
mode: single
```

### Geofence: ping me when the car gets home

```yaml
alias: Porsche arrived home
trigger:
  - platform: state
    entity_id: device_tracker.taycan
    to: home
action:
  - service: notify.mobile_app_my_phone
    data:
      title: Porsche
      message: The Taycan just arrived home.
mode: single
```

## Polling and data updates

The integration is **cloud-polling** (`iot_class: cloud_polling`) — there is no
push channel from Porsche to Home Assistant.

- **Default poll interval:** every **1920 seconds (32 minutes)** via
  `DataUpdateCoordinator`. The interval is deliberately conservative to stay
  well within Porsche's backend rate limits; multi-vehicle accounts share the
  same tick.
- **What each tick fetches:** for every vehicle on the account, the stored
  overview (`get_stored_overview`) — i.e. the measurements and capability
  payload cached server-side by Porsche.
- **First refresh:** on initial setup the integration additionally fetches the
  vehicle list and the picture locations (used by the `image` platform).
- **Extra refreshes are triggered by:**
  - Pressing the **Get current vehicle information** button, which forces a
    fresh pull from the car instead of returning the cached overview.
  - Any remote action (climatisation switch, target SoC change, lock/unlock,
    flash, honk) — after the API call the coordinator notifies listeners so
    entities re-read state.
  - The reauth flow re-running setup after a token refresh.

The default 32-minute cadence balances "responsive enough for ambient
dashboards" against "doesn't aggressively wake the car or burn through API
quota". Override it only if you understand the trade-off (the upstream
`CONF_SCAN_INTERVAL` is respected on the config entry).

## Troubleshooting

### Captcha screen during install

Porsche occasionally requires a captcha for a fresh login. The config flow
detects this and renders the SVG image inline in a `captcha` step; type the
characters you see and submit. If it loops, retry from scratch — the captcha
is single-use and time-limited.

### Empty `commands` / `measurements` — `connect: false`

If the integration loads but no sensors populate, the car is most likely not
paired in the PCM. Pair the car in My Porsche / the Porsche app using the
displayed pairing code; the next coordinator tick will pick up the new
capability set automatically (no HA restart required).

### Reauth requested out of the blue

Porsche tokens expire periodically. Any 401 from the API (or a
`PorscheWrongCredentialsError`) is converted to `ConfigEntryAuthFailed`, which
HA surfaces as a repair notification linking back to the login form. Just
re-enter the password.

### Lock works but unlock doesn't

Unlock requires the **S-PIN** you configured in the Porsche app. Open the
`lock` entity's options and set the *default code* to your 4-digit S-PIN; HA
will pass it on every unlock call.

### Vehicle is missing from the device list

- The model is older than MY 2021 / doesn't ship Porsche Connect — confirm
  on <https://connect-store.porsche.com/>.
- The Porsche Connect subscription has lapsed — renew it in My Porsche.
- The car was not paired in the PCM. Pair it, then trigger one extra refresh
  (the *Get current vehicle information* button) or wait for the next
  32-minute tick.

### Enabling debug logs

To capture verbose logs for a bug report, add this to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.porscheconnect: debug
    pyporscheconnectapi: debug
```

Reload the logger or restart HA, reproduce the issue, then attach the relevant
log slice to the GitHub issue.

## Known limitations

- **Active Porsche Connect subscription is mandatory.** Without it, the API
  rejects vehicle queries even though authentication succeeds.
- **Porsche Car Connect is not supported.** That is a different service with
  a different backend; this integration targets *Porsche Connect* only.
- **Cars must be paired in the PCM.** Un-paired cars expose empty
  `commands` / `measurements` payloads, so no entities are created.
- **Captcha may be required at first login.** Handled by the config flow but
  occasionally loops if Porsche flags the IP.
- **2FA / TOTP is not supported by the underlying library.** If you have
  enabled 2FA on the Porsche ID, login will fail.
- **Charging-profile target SoC has a known bug (issue #319).** The
  `number.target_soc` entity writes to the active profile, but Porsche may
  silently revert the value on certain MYs / firmware combinations. Track
  upstream for the fix.
- **No push updates.** The integration polls every 32 minutes by default; for
  near-real-time data, use the *Get current vehicle information* button.

## Removal

1. Go to **Settings → Devices & services → Porsche Connect**.
2. Open the integration card, click the **⋮** menu on the entry, choose
   **Delete**, and confirm.
3. Restart Home Assistant if you also want to remove the HACS files; otherwise
   the entities disappear immediately.
4. (Optional) Revoke the OAuth grant from
   [My Porsche](https://login.porsche.com/) → *Privacy & data* → connected
   apps, if you want Porsche to invalidate the stored refresh token.

To fully uninstall:

1. Remove the integration as above.
2. In HACS, open **Porsche Connect** → ⋮ → **Remove**.
3. Restart Home Assistant.

## Contributing / Development

Bug reports and feature requests are welcome on the
[GitHub issue tracker](https://github.com/bartolije/ha-porscheconnect/issues).
General usage questions go to
[Discussions](https://github.com/bartolije/ha-porscheconnect/discussions),
the [HA Community Forum][forum], or [Discord][discord].

If you want to contribute code, read
[CONTRIBUTING.md](https://github.com/bartolije/ha-porscheconnect/blob/main/CONTRIBUTING.md)
first — it covers the dev container, pre-commit hooks, and the test layout.

---

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[ruff]: https://github.com/astral-sh/ruff
[ruff-shield]: https://img.shields.io/badge/code%20style-ruff-261230.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/bartolije/ha-porscheconnect.svg?style=for-the-badge
[commits]: https://github.com/bartolije/ha-porscheconnect/commits/main
[hacs]: https://hacs.xyz
[hacs_badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/bartolije/ha-porscheconnect.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40bartolije-blue.svg?style=for-the-badge
[pre-commit]: https://github.com/pre-commit/pre-commit
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/bartolije/ha-porscheconnect.svg?style=for-the-badge
[releases]: https://github.com/bartolije/ha-porscheconnect/releases
[user_profile]: https://github.com/bartolije
