# My Porsche Connect for Home Assistant

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

## About this fork

This repository is a fork of
[CJNE/ha-porscheconnect](https://github.com/CJNE/ha-porscheconnect), the
Porsche Connect integration by [Johan Isacsson](https://github.com/CJNE) and
its contributors, maintained by [bartolije](https://github.com/bartolije). It
uses a fork of the library as well:
[pyporscheconnectapi-bartolije](https://pypi.org/project/pyporscheconnectapi-bartolije/)
([bartolije/pyporscheconnectapi](https://github.com/bartolije/pyporscheconnectapi),
forked from [CJNE/pyporscheconnectapi](https://github.com/CJNE/pyporscheconnectapi)).

Both integrations use the same `porscheconnect` domain, so only one of them can
be installed at a time. What this fork adds:

- support for the current Home Assistant releases (2026.11 and newer);
- a `climate` entity, one binary sensor per door, window and lid, and a pressure
  deviation sensor per tire;
- a reauthentication prompt when Porsche asks for a captcha, instead of endless
  retries;
- diagnostics with the position, pairing codes and key data redacted;
- when switching from the upstream integration, the existing entities are kept
  with their entity IDs and history.

Fixes that also apply upstream are sent back as pull requests.

## Features

- Battery, charging, range, mileage, fuel level sensors
- Doors/lids, parking brake/light, privacy mode, remote access binary sensors
- Tire pressure status (per-tire attributes) when the vehicle has TPMS
- Vehicle location via `device_tracker` (suppressed when privacy mode is on)
- Vehicle images (front, side, rear, rear-top, top views)
- Door `lock` entity (unlock requires the S-PIN configured per-entity)
- `climate` entity: remote climatisation with a target temperature
- Remote `switch` entities: direct charging, and climatisation (disabled by default:
  the `climate` entity sends the same command)
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

Each entity is gated on a capability flag or on a measurement the car reports,
so the integration only creates entities the car can actually feed. The gates
are read when the vehicle is first seen: if the car starts reporting a new
measurement later, reload the integration to get its entity.

| Platform        | Entity / key                                                       | Capability gate                                          |
| --------------- | ------------------------------------------------------------------ | -------------------------------------------------------- |
| `sensor`        | `state_of_charge`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_target`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_status`                                                  | `has_electric_drivetrain`                                |
| `sensor`        | `charging_rate` (disabled by default)                              | `has_electric_drivetrain`                                |
| `sensor`        | `charging_power`                                                   | `has_electric_drivetrain`                                |
| `sensor`        | `charging_finished`                                                | `has_electric_drivetrain`                                |
| `sensor`        | `remaining_range_electric`                                         | `has_electric_drivetrain`                                |
| `sensor`        | `last_update` (when the car last sent its data, diagnostic)        | `GLOBAL_TIMESTAMP` reported                              |
| `sensor`        | `connect_contract_end` (diagnostic)                                | `CONNECT_CONTRACT` reported                              |
| `sensor`        | `monthly_distance`, `monthly_driving_time`, `monthly_trips` ¹      | `TRIP_STATISTICS_MONTHLY_REPORT` reported                |
| `sensor`        | `monthly_fuel_consumption`, `monthly_electric_consumption` ¹       | the matching field reported                              |
| `sensor`        | `battery_energy_status`, `battery_temperature` (diagnostic) ¹      | `BEM_LEVEL`, `BATTERY_CONDITION` reported                |
| `sensor`        | `charging_session_energy` ¹                                        | `CHARGING_SESSION` reported                              |
| `sensor`        | `mileage`                                                          | `has_porsche_connect` (default)                          |
| `sensor`        | `remaining_range`                                                  | `has_ice_drivetrain`                                     |
| `sensor`        | `fuel_level`                                                       | `has_ice_drivetrain`                                     |
| `sensor`        | `fuel_reserve` (diagnostic, disabled by default)                   | `FUEL_RESERVE` reported                                  |
| `sensor`        | `tire_pressure_front_left`, `…_front_right`, `…_rear_left`,        | `has_tire_pressure_monitoring`                           |
| `sensor`        | `…_rear_right`: deviation in bar (diagnostic, disabled)            |                                                          |
| `sensor`        | `main_service_distance`, `main_service_time` (diagnostic)          | the matching service measurement reported                |
| `sensor`        | `oil_service_*`, `intermediate_service_*` (diagnostic, disabled)   | the matching service measurement reported                |
| `binary_sensor` | `parking_brake`                                                    | `PARKING_BRAKE` reported                                 |
| `binary_sensor` | `parking_light`                                                    | `PARKING_LIGHT` reported                                 |
| `binary_sensor` | `privacy_mode` (diagnostic)                                        | `has_porsche_connect`                                    |
| `binary_sensor` | `remote_access` (diagnostic, disabled by default)                  | `REMOTE_ACCESS_AUTHORIZATION` reported                   |
| `binary_sensor` | `doors_and_lids`                                                   | `has_porsche_connect`                                    |
| `binary_sensor` | `door_*`, `window_*`, `lid_front`, `lid_rear`, `sunroof`,          | the matching `OPEN_STATE_*` measurement reported         |
| `binary_sensor` | `sunroof_rear`, `convertible_top`, `charge_flap_left/right`        |                                                          |
| `binary_sensor` | `spoiler`, `service_flap` (diagnostic, disabled by default)        | the matching `OPEN_STATE_*` measurement reported         |
| `binary_sensor` | `tire_pressure_status`                                             | `has_tire_pressure_monitoring`                           |
| `binary_sensor` | `instrument_cluster_alerts` (oil level, tire pressure) ¹           | `INSTRUMENT_CLUSTER_ALERTS` reported                     |
| `device_tracker`| Vehicle location                                                   | privacy mode off                                         |
| `image`         | `front_view`, `side_view`, `rear_view`, `rear_top_view`, `top_view`| Pictures returned by the API                             |
| `lock`          | Door lock                                                          | every vehicle (unlock needs the S-PIN)                   |
| `climate`       | Remote climatisation (target read from the car, `remaining_time`)  | `has_remote_climatisation` and `has_remote_services`     |
| `switch`        | `climatise` (disabled by default)                                  | `has_remote_climatisation` and `has_remote_services`     |
| `switch`        | `direct_charging`                                                  | `has_direct_charge` and `has_remote_services`            |
| `number`        | `target_soc` (25–100 %, step 5)                                    | `has_electric_drivetrain` and `has_remote_services`      |
| `button`        | `flash_indicators`                                                 | `has_remote_services`                                    |
| `button`        | `honk_and_flash_indicators`                                        | `has_remote_services`                                    |
| `button`        | `get_current_overview`                                             | `has_remote_services` (forces a fresh pull from the car) |

¹ Built from the data models of the My Porsche app (21.26.44), not yet seen on a
car: a 718 reports them as not supported. If your car shows one of them, please
check the value against the app and open an issue with the diagnostics attached
(device page, ⋮ menu, "Download diagnostics"), whether it is right or wrong.

The privacy mode flag is honoured by the vehicle itself — when the driver
enables privacy in the PCM, the `device_tracker` entity is not created; it is
added on the next refresh once privacy mode is turned off.

## Installation

The integration is delivered as a [HACS](https://hacs.xyz) custom integration.
It requires Home Assistant 2026.11 or newer.

### HACS (recommended)

[![Open this repository in HACS][hacs-repo-badge]][hacs-repo]

1. Click the button above, or in HACS open **⋮ → Custom repositories** and add
   `https://github.com/bartolije/ha-porscheconnect` with the type
   **Integration**. (The **Porsche Connect** entry of the default HACS store is
   the upstream integration; both install into `custom_components/porscheconnect`,
   so keep only one of them.)
2. Search for **My Porsche Connect** and select the one from this repository.
3. Click **Download**, then **Restart Home Assistant**.
4. Go to **Settings → Devices & services → Add integration**, search
   **My Porsche Connect**, and follow the configuration flow.

### Manual

1. Open the directory containing your `configuration.yaml`.
2. Create `custom_components/` if it does not exist.
3. Inside it, create `custom_components/porscheconnect/`.
4. Copy every file from `custom_components/porscheconnect/` in this repo into
   that folder.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**, search
   **My Porsche Connect**, and follow the configuration flow.

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
  credentials, or when Porsche asks for a captcha. Home Assistant shows a repair
  notification leading back to the login form.
- **Reconfigure** lets you update the password for an existing entry without
  removing and re-adding it (Settings → Devices & services → My Porsche Connect
  → ⋮ on the entry → Reconfigure).

## Services / Actions

### `porscheconnect.climatisation_start`

Starts remote climatisation of the passenger compartment with an optional
target temperature and per-seat heating selection.

#### Parameters

| Name          | Type     | Required | Default | Notes                                                              |
| ------------- | -------- | -------- | ------- | ------------------------------------------------------------------ |
| `vehicle`     | device   | yes      | —       | The Porsche Connect device the action targets.                     |
| `temperature` | number   | no       | 20 °C   | Target cabin temperature; the form offers 15–25 °C, 0.5 °C step.   |
| `front_left`  | boolean  | no       | false   | Activate front-left seat heating if the car has that zone.         |
| `front_right` | boolean  | no       | false   | Activate front-right seat heating if the car has that zone.        |
| `rear_left`   | boolean  | no       | false   | Activate rear-left seat heating if the car has that zone.          |
| `rear_right`  | boolean  | no       | false   | Activate rear-right seat heating if the car has that zone.         |

#### Behavior on unsupported zones

The Porsche API only lists zones the car physically supports in
`HVAC_SUMMARY.climateZonesEnabled`
([upstream issue #292](https://github.com/CJNE/ha-porscheconnect/issues/292)).
Two cases:

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
action: porscheconnect.climatisation_start
data:
  vehicle: 1a2b3c4d5e6f7890abcdef1234567890   # device id of the Porsche
  temperature: 21
  front_left: true
  front_right: true
```

### `porscheconnect.climatisation_stop`

Stops remote climatisation. Its only parameter is `vehicle`, the device to
target. It raises the same errors as `climatisation_start` for an unknown device
or a car without remote climatisation.

```yaml
action: porscheconnect.climatisation_stop
data:
  vehicle: 1a2b3c4d5e6f7890abcdef1234567890
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
  - entity: climate.taycan
  - entity: number.taycan_target_state_of_charge
  - entity: button.taycan_flash_indicators
```

### Pre-heat the cabin at 7 am on cold mornings

```yaml
alias: Porsche pre-heat on cold mornings
triggers:
  - trigger: time
    at: "07:00:00"
conditions:
  - condition: numeric_state
    entity_id: sensor.openweathermap_temperature
    below: 5
actions:
  - action: porscheconnect.climatisation_start
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
triggers:
  - trigger: state
    entity_id: binary_sensor.taycan_doors_and_lids
    to: "on"
    for: "00:05:00"
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: Porsche
      message: A door or lid has been open for five minutes.
mode: single
```

### Log charging sessions to a logbook

```yaml
alias: Log Porsche charging start
triggers:
  - trigger: state
    entity_id: sensor.taycan_charging_status
    to: charging
actions:
  - action: logbook.log
    data:
      name: Taycan
      message: "Charging started at {{ states('sensor.taycan_state_of_charge') }} %"
      entity_id: sensor.taycan_state_of_charge
mode: single
```

### Geofence: ping me when the car gets home

```yaml
alias: Porsche arrived home
triggers:
  - trigger: state
    entity_id: device_tracker.taycan
    to: home
actions:
  - action: notify.mobile_app_my_phone
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
- **What each tick fetches:** the account's vehicle list, then for every
  vehicle the stored overview (`get_stored_overview`) — i.e. the measurements
  and capability payload cached server-side by Porsche. A car added to the
  account gets its entities on the next tick; a car removed from it turns
  unavailable and its device can then be deleted.
- **Pictures:** the picture locations (used by the `image` platform) are
  fetched on setup, then once a day for as long as Porsche returns none.
- **Extra refreshes are triggered by:**
  - Pressing the **Get current vehicle information** button, which forces a
    fresh pull from the car instead of returning the cached overview.
  - Any remote action (climatisation switch, target SoC change, lock/unlock,
    flash, honk) — after the API call the coordinator notifies listeners so
    entities re-read state.
  - The reauth flow re-running setup after a token refresh.

The default 32-minute cadence balances "responsive enough for ambient
dashboards" against "doesn't aggressively wake the car or burn through API
quota". There is no setting to change it; an interval set in the options of the
upstream integration before switching to this fork is kept.

## Troubleshooting

### Captcha screen during install

Porsche occasionally requires a captcha for a fresh login. The config flow
detects this and renders the SVG image inline in a `captcha` step; type the
characters you see and submit. If it loops, retry from scratch — the captcha
is single-use and time-limited.

### Empty `commands` / `measurements` — `connect: false`

If the integration loads but no sensors populate, the car is most likely not
paired in the PCM. Pair the car in My Porsche / the Porsche app using the
displayed pairing code, then reload the integration (Settings → Devices &
services → My Porsche Connect → ⋮ → Reload): entities are created from what the
car reports when it is first seen.

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
- The car was not paired in the PCM. Pair it, then reload the integration or
  wait for the next 32-minute tick.

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
- **Charging-profile target SoC has a known bug
  ([upstream issue #319](https://github.com/CJNE/ha-porscheconnect/issues/319)).** The
  `number.target_soc` entity writes to the active profile, but Porsche may
  silently revert the value on certain MYs / firmware combinations. Track
  upstream for the fix.
- **No push updates.** The integration polls every 32 minutes by default; for
  near-real-time data, use the *Get current vehicle information* button.

## Removal

1. Go to **Settings → Devices & services → My Porsche Connect**.
2. Open the integration card, click the **⋮** menu on the entry, choose
   **Delete**, and confirm. The devices and entities disappear immediately.
3. (Optional) Revoke the OAuth grant from
   [My Porsche](https://login.porsche.com/) → *Privacy & data* → connected
   apps, if you want Porsche to invalidate the stored refresh token.

To fully uninstall:

1. Remove the integration as above.
2. In HACS, open **My Porsche Connect** → ⋮ → **Remove**.
3. Restart Home Assistant.

## Contributing / Development

Bug reports and feature requests are welcome on the
[GitHub issue tracker](https://github.com/bartolije/ha-porscheconnect/issues).
General usage questions go to the [HA Community Forum][forum] or
[Discord][discord].

If you want to contribute code, read
[CONTRIBUTING.md](https://github.com/bartolije/ha-porscheconnect/blob/main/CONTRIBUTING.md)
first — it covers the checks CI runs, pre-commit hooks, the tests and the
release order.

---

[hacs-repo]: https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=ha-porscheconnect&category=integration
[hacs-repo-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
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
