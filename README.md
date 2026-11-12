# My Porsche Connect for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![CI][ci-shield]][ci]
[![Home Assistant][ha-shield]][hacs-repo]
[![License][license-shield]](LICENSE)

**Your Porsche, at home in Home Assistant.**

See your car on your dashboard, next to your lights and your heating. Know at a
glance whether it is locked, how far it can go and where it is parked. Warm the
cabin before you leave, get a message when a door was left open, and let your
home react when the car comes back.

Sign in with your My Porsche account and your car appears. Nothing to wire,
nothing to configure by hand. Available in seven languages.

[![Open this repository in HACS][hacs-repo-badge]][hacs-repo]

## What you can do

- **Check on your car without opening the app.** Range, fuel or battery level,
  mileage, tire pressures, next service: all on your dashboard.
- **Never wonder if you locked it.** See the lock, every door, window and lid,
  and lock or unlock from Home Assistant.
- **Leave in a warm car.** On electric and plug-in hybrid models, start the
  climatisation from an automation: every cold weekday morning, or when your
  alarm goes off.
- **Be told, not surprised.** A notification when a door stays open, when
  charging is finished, or when a service is due.
- **Let the house follow the car.** Open the garage and switch on the lights
  when it arrives home.
- **Charge your way.** Set the charge target, start direct charging, follow the
  charging power and the time it ends.

## Built to be trusted with your car

- **Careful with your car.** A lock, unlock or climatisation command is sent
  once. If Porsche answers slowly, nothing is replayed behind your back.
- **Careful with your data.** Your password, your PIN and the position of your
  car never appear in logs or in the diagnostics you may share.
- **It keeps working.** Porsche changes its login without notice. Automatic
  checks run every day to catch it before you do, and when Porsche wants a
  captcha or a new password, Home Assistant simply asks you.
- **Built to Home Assistant's highest standards.** The integration follows the
  official [quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
  rule by rule ([how each rule is met](custom_components/porscheconnect/quality_scale.yaml)),
  with more than 120 automated tests, and it is checked on a real car.

## Supported cars

Any Porsche with an active **Porsche Connect** subscription, paired with your
My Porsche account. In practice, cars from model year 2021 on.

| Model              | Type                     | Status, doors, lock, position | Charging and climatisation |
| ------------------ | ------------------------ | ----------------------------- | -------------------------- |
| Taycan             | Electric                 | Yes                           | Yes                        |
| Macan Electric     | Electric                 | Yes                           | Yes                        |
| Cayenne (E3)       | Plug-in hybrid or petrol | Yes                           | Plug-in hybrid only        |
| Panamera (G2 PA)   | Plug-in hybrid or petrol | Yes                           | Plug-in hybrid only        |
| 911 (992)          | Petrol                   | Yes                           | No                         |
| 718 Boxster/Cayman | Petrol                   | Yes                           | No                         |

Not sure about your car? Select it on <https://connect-store.porsche.com/> and
check that the *Porsche Connect* package is offered.

The older *Porsche Car Connect* service is a different system and is not
supported.

## Installation

You need Home Assistant 2026.11 or newer and [HACS](https://hacs.xyz).

1. Click the **Open in HACS** button above, or in HACS open **⋮ → Custom
   repositories** and add `https://github.com/bartolije/ha-porscheconnect` as an
   **Integration**.
2. Search for **My Porsche Connect**, click **Download**, then restart Home
   Assistant.
3. Go to **Settings → Devices & services → Add integration**, search
   **My Porsche Connect** and sign in.

The **Porsche Connect** entry of the default HACS store is the original
integration. Both use the same folder, so keep only one. If you switch from it,
your entities keep their names and history.

<details>
<summary>Manual installation</summary>

Copy the `custom_components/porscheconnect/` folder of this repository into the
`custom_components/` folder next to your `configuration.yaml`, restart Home
Assistant, then add the integration as in step 3.

</details>

## Configuration

Everything is set up in the Home Assistant UI.

| Field    | Required      | Notes                                                             |
| -------- | ------------- | ----------------------------------------------------------------- |
| Email    | Yes           | The email of your My Porsche account.                             |
| Password | Yes           | The password of your My Porsche account.                          |
| Captcha  | When prompted | Porsche sometimes shows a picture to copy when you first sign in. |

Before you start, the car needs an active Porsche Connect subscription and must
be paired in its PCM with the pairing code shown in the My Porsche app.

**Unlocking** needs the 4-digit security PIN you chose in the Porsche app. Enter
it once as the *default code* in the options of the lock entity. Locking does
not need it.

**Changed your password?** Open **Settings → Devices & services → My Porsche
Connect → ⋮ → Reconfigure**. If Porsche ends your session, Home Assistant asks
you to sign in again by itself.

There are no other settings.

## What you get

Your car appears as one device. Home Assistant only creates what your car
actually reports, so a petrol car has no charging entities.

| For                | Entities                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------ |
| Range and energy   | Range, fuel level, battery level, electric range, mileage                                        |
| Charging           | Status, power, end time, charge target, direct charging                                          |
| Doors and security | Lock, each door, window and lid, sunroof, convertible top, parking brake and lights              |
| Comfort            | Climatisation with a target temperature                                                          |
| Position           | The car on your map (not created while privacy mode is on in the car)                            |
| Tires and service  | Tire pressure status and deviation per tire, next service, oil change, dashboard alerts          |
| Trips              | Distance, driving time, trips and consumption of the month                                       |
| Pictures           | Five views of your own car, in its colour                                                        |
| Buttons            | Flash the indicators, honk and flash, ask the car for fresh data                                 |

Some entities are disabled by default to keep the device page readable. Enable
them from the device page if you want them.

<details>
<summary>Full list of entities and when each one is created</summary>

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

¹ Built from the data of the My Porsche app and not yet seen on a car. If your
car shows one of them, please compare it with the app and open an issue with the
diagnostics attached (device page → ⋮ → Download diagnostics).

Entities are created from what the car reports when it is first seen. If your
car starts reporting something new later, reload the integration.

</details>

## Actions

### `porscheconnect.climatisation_start`

Starts the climatisation, with an optional temperature and seat heating.

| Name          | Required | Default | Notes                                           |
| ------------- | -------- | ------- | ----------------------------------------------- |
| `vehicle`     | yes      |         | The Porsche device.                             |
| `temperature` | no       | 20 °C   | 15 to 30 °C, in steps of 0.5.                   |
| `front_left`  | no       | false   | Heat the front left seat, if the car has it.    |
| `front_right` | no       | false   | Heat the front right seat, if the car has it.   |
| `rear_left`   | no       | false   | Heat the rear left seat, if the car has it.     |
| `rear_right`  | no       | false   | Heat the rear right seat, if the car has it.    |

```yaml
action: porscheconnect.climatisation_start
data:
  vehicle: 1a2b3c4d5e6f7890abcdef1234567890   # device id of the Porsche
  temperature: 21
  front_left: true
```

Asking for a seat the car does not have, or for a car without remote
climatisation, fails with a clear error instead of doing nothing.

### `porscheconnect.climatisation_stop`

Stops the climatisation. Its only parameter is `vehicle`.

```yaml
action: porscheconnect.climatisation_stop
data:
  vehicle: 1a2b3c4d5e6f7890abcdef1234567890
```

## Examples

A dashboard card and four automations: a warm cabin on cold mornings, a warning
when a door stays open, a charging log and a message when the car gets home. Replace `taycan` with the name of your car.

<details>
<summary>Show the examples</summary>

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

</details>

## How data is updated

Home Assistant asks Porsche for the state of your car **every 32 minutes**.
Porsche limits how often it can be asked, so there is no setting to go faster.

- Need it now? Press **Get current vehicle information** on the device page: it
  asks the car itself for fresh data.
- After a command (lock, climatisation, charging), the entities are refreshed
  right away.
- A car added to your account appears at the next update. A car that left it is
  removed after two updates without it, about an hour.
- Pictures are fetched once, when the integration starts.

## Troubleshooting

**A captcha is asked at sign-in.** Copy the characters and submit. If it comes
back, start again: each picture can be used once.

**The car is there but most entities are missing.** The car is probably not
paired in its PCM. Pair it with the code shown in the My Porsche app, then
reload the integration.

**The car is missing.** Check that the model has Porsche Connect and that the
subscription is active: Home Assistant shows a lapsed subscription under
**Settings → Repairs**. A car that left your account is removed after about an
hour and comes back if you add it again.

**Home Assistant asks me to sign in again.** Porsche ended the session. Enter
your password, and the captcha if one is shown.

**Lock works, unlock does not.** Set your 4-digit security PIN as the *default
code* in the options of the lock entity.

**Reporting a problem.** Download the diagnostics from the device page (⋮ →
Download diagnostics): your password and position are removed, your email and VIN masked. For
more detail, enable debug logs:

```yaml
logger:
  logs:
    custom_components.porscheconnect: debug
    pyporscheconnectapi: debug
```

The log never holds your password, a token or your PIN. It does name your VIN:
remove it before posting.

## Known limitations

- An active Porsche Connect subscription is required, and the car must be paired
  in its PCM.
- Porsche Car Connect, the older service, is not supported.
- Porsche accounts with two-factor authentication cannot sign in.
- Data is at most 32 minutes old: Porsche sends nothing by itself.
- On some model years, Porsche does not keep a charge target set from outside
  its own app.
- A captcha may be asked at sign-in, more often after several attempts.

## Removal

1. Go to **Settings → Devices & services → My Porsche Connect**.
2. Click **⋮** on the entry, choose **Delete** and confirm. The device and its
   entities disappear.
3. To uninstall completely: in HACS, open **My Porsche Connect → ⋮ → Remove**,
   then restart Home Assistant.

## Credits and contributing

This is a fork of [CJNE/ha-porscheconnect](https://github.com/CJNE/ha-porscheconnect)
by [Johan Isacsson](https://github.com/CJNE) and its contributors, maintained by
[bartolije](https://github.com/bartolije), with its own version of the library,
[pyporscheconnectapi-bartolije](https://github.com/bartolije/pyporscheconnectapi).
Fixes that also apply to the original project are sent back to it.

Bug reports and ideas are welcome in the
[issue tracker](https://github.com/bartolije/ha-porscheconnect/issues). To
contribute code, read [CONTRIBUTING.md](CONTRIBUTING.md).

This project is not affiliated with Porsche.

---

[ci]: https://github.com/bartolije/ha-porscheconnect/actions/workflows/tests.yaml
[ci-shield]: https://img.shields.io/github/actions/workflow/status/bartolije/ha-porscheconnect/tests.yaml?branch=main&label=CI&style=for-the-badge
[ha-shield]: https://img.shields.io/badge/Home%20Assistant-2026.11%2B-41BDF5.svg?style=for-the-badge
[hacs-repo]: https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=ha-porscheconnect&category=integration
[hacs-repo-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[license-shield]: https://img.shields.io/github/license/bartolije/ha-porscheconnect.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/bartolije/ha-porscheconnect.svg?style=for-the-badge
[releases]: https://github.com/bartolije/ha-porscheconnect/releases
