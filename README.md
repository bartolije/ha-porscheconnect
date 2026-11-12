# My Porsche Connect for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![CI][ci-shield]][ci]
[![Home Assistant][ha-shield]][hacs-repo]
[![License][license-shield]](LICENSE)

**Your Porsche, at home in Home Assistant.**

[Porsche Connect](https://connect-store.porsche.com/) is the online service of
Porsche cars: it is what the My Porsche app uses to show and control your car.
This integration brings the same car into Home Assistant.

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
  official [quality scale](https://contributors.home-assistant.io/core/quality-scale/)
  rule by rule ([how each rule is met](custom_components/porscheconnect/quality_scale.yaml)),
  with more than 150 automated tests, and it is checked on a real car. Home Assistant does
  not review custom integrations: this is the maintainer's own assessment, open
  for anyone to check.

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

### Before you start

- Home Assistant 2026.11 or newer, with [HACS](https://hacs.xyz).
- An active **Porsche Connect** subscription for the car.
- The car paired with your My Porsche account, in its PCM, with the pairing code
  the My Porsche app shows.
- A My Porsche account **without two-factor authentication**: it cannot sign in
  from Home Assistant.

### Steps

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
| Captcha code | When prompted | Porsche sometimes shows a picture to copy when you first sign in. |

**Unlocking** needs the 4-digit security PIN you chose in the Porsche app. Enter
it once as the *default code* in the options of the lock entity. Locking does
not need it.

**Changed your password?** Open **Settings → Devices & services → My Porsche
Connect → ⋮ → Reconfigure** and enter the new one. If Porsche ends your session,
Home Assistant asks for your password again by itself. The account of an entry
never changes: to use another account, add it as a new entry.

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
<summary>Every entity, what it shows and on which cars</summary>

**Sensors**

| Entity | What it shows | Available on |
| ------ | ------------- | ------------ |
| Mileage | Total distance driven | Every car |
| Remaining range | Range left on fuel | Petrol and plug-in hybrid |
| Fuel level | Fuel left, in percent | Petrol and plug-in hybrid |
| Fuel reserve ² | Reserve level reported by the car, in percent | Cars that report it |
| State of charge | Battery level, in percent | Electric and plug-in hybrid |
| Remaining range electric | Range left on the battery | Electric and plug-in hybrid |
| Charging status | Charging, completed, not plugged, error… | Electric and plug-in hybrid |
| Charging power | Power the car charges with, in kW | Electric and plug-in hybrid |
| Charging rate ² | Range gained per hour of charging | Electric and plug-in hybrid |
| Charging ends | Time the charge is expected to end | Electric and plug-in hybrid |
| Charging target | Battery level the charge stops at | Electric and plug-in hybrid |
| Energy charged in the last session ¹ | Energy of the last charge, in kWh | Cars that report it |
| Battery energy status ¹ | Normal, warning or critical | Cars that report it |
| Battery temperature ¹ | Temperature of the battery | Cars that report it |
| Distance to service, Time to service | When the next service is due | Cars that report it |
| Distance and time to oil service ² | When the next oil change is due | Cars that report it |
| Distance and time to intermediate service ² | When the intermediate service is due | Cars that report it |
| Tire pressure deviation (per tire) ² | Difference to the recommended pressure, in bar | Cars with tire pressure monitoring |
| Monthly report distance, driving time, trips ¹ | Totals of the current month | Cars that report it |
| Monthly report fuel and electric consumption ¹ | Average consumption of the month | Cars that report it |
| Porsche Connect contract end | Date the subscription ends | Cars that report it |
| Last update from the car | When the car last sent its data | Cars that report it |

**Binary sensors**

| Entity | What it shows | Available on |
| ------ | ------------- | ------------ |
| Doors and lids | On when any door, window or lid is open | Every car |
| Door, Window (each one), Frunk, Trunk | Open or closed | Cars that report that part |
| Sunroof, Rear sunroof, Convertible top | Open or closed | Cars that have one |
| Charge flap (left, right) | Open or closed | Cars that have one |
| Active spoiler ², Service flap ² | Open or closed | Cars that have one |
| Parking brake | On when the parking brake is set | Cars that report it |
| Parking light | On when the parking light is on | Cars that report it |
| Tire pressure status | A problem with the pressure of a tire | Cars with tire pressure monitoring |
| Instrument cluster alerts ¹ | A warning on the dashboard (oil level, tire pressure) | Cars that report it |
| Privacy mode | On when the driver enabled privacy in the car | Every car |
| Remote access ² | Whether remote commands are allowed | Cars that report it |

**Controls**

| Entity | What it does | Available on |
| ------ | ------------ | ------------ |
| Door lock (`lock`) | Locks and unlocks the car; unlocking needs your PIN | Every car |
| The car itself (`climate`) | Starts and stops the climatisation, with a target temperature | Electric and plug-in hybrid with remote services |
| Remote climatisation ² (`switch`) | Same command as the climate entity, without a temperature | Electric and plug-in hybrid with remote services |
| Direct charging (`switch`) | Charges now, ignoring the timers | Cars with direct charging |
| Target state of charge (`number`) | Sets the level the charge stops at, 25 to 100 % | Electric and plug-in hybrid with remote services |
| Flash indicators (`button`) | Flashes the indicators | Cars with remote services |
| Honk and flash indicators (`button`) | Sounds the horn and flashes | Cars with remote services |
| Get current vehicle information (`button`) | Asks the car for fresh data | Cars with remote services |

**Position and pictures**

| Entity | What it shows | Available on |
| ------ | ------------- | ------------ |
| The car itself (`device_tracker`) | The car on the map, with its heading | Every car, unless privacy mode is on |
| View from the side | A picture of your car | Every car |
| View from the front, the rear, above, diagonally from above ² | Other pictures of your car | Every car |

¹ Built from the data of the My Porsche app and not yet seen on a car. If your
car shows one of them, please compare it with the app and open an issue with the
diagnostics attached (device page → ⋮ → Download diagnostics).

² Disabled by default. Enable it from the device page.

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
- Pictures are fetched when the integration starts, then once a day until
  Porsche has some for your car.

## Troubleshooting

<details>
<summary>"Invalid authentication" when signing in</summary>

**What you see.** The form comes back with *Invalid authentication*.

**Why.** Porsche refused the email or the password, or the account uses
two-factor authentication, which cannot sign in from Home Assistant.

**What to do.** Check that the same email and password work in the My Porsche
app, then try again.

</details>

<details>
<summary>"Failed to connect" or "Unexpected error" when signing in</summary>

**What you see.** The form comes back with *Failed to connect* or *Unexpected
error*.

**Why.** Porsche did not answer, or answered something the integration does not
understand. Porsche also limits the number of sign-ins.

**What to do.** Wait a few minutes and try again. If it lasts, open an issue
with the log: *Unexpected error* writes the details there.

</details>

<details>
<summary>A captcha is asked, again and again</summary>

**What you see.** A picture to copy when signing in, sometimes several times.

**Why.** Porsche asks for it after several sign-ins, and each picture can be
used once.

**What to do.** Copy the characters and submit. If the form comes back, enter
your password again: a new picture follows.

</details>

<details>
<summary>The car is there but most entities are missing</summary>

**What you see.** The device exists with only a few entities.

**Why.** The car is not paired in its PCM, or its Porsche Connect contract is
not active. In the second case Home Assistant says so under **Settings →
Repairs**.

**What to do.** Pair the car with the code shown in the My Porsche app, or
renew the contract. For a pairing, reload the integration afterwards; after a
renewal, the entities come back by themselves.

</details>

<details>
<summary>A car is missing, or disappeared</summary>

**What you see.** A car of yours has no device, or its device is gone.

**Why.** The model has no Porsche Connect, or the car is no longer on your My
Porsche account. A car that left the account is removed after about an hour.

**What to do.** Check the car in the My Porsche app. Once it is on the account
again, it comes back at the next update.

</details>

<details>
<summary>Home Assistant asks me to sign in again</summary>

**What you see.** A notification asking for the password of the account.

**Why.** Porsche ended the session, or the password changed.

**What to do.** Enter your password, and the captcha if one is shown.

</details>

<details>
<summary>The integration does not start: access blocked</summary>

**What you see.** The entry is in error with *Porsche has blocked access for
this account*.

**Why.** The account is locked, or mobile access is disabled for it.

**What to do.** Sign in to the My Porsche app to lift it, then reload the
integration.

</details>

<details>
<summary>Lock works, unlock does not</summary>

**What you see.** Unlocking fails, or says the PIN is missing or invalid.

**Why.** Unlocking needs the 4-digit security PIN of the Porsche app.

**What to do.** Set it as the *default code* in the options of the lock entity.

</details>

### Reporting a problem

Download the diagnostics from the device page (⋮ → Download diagnostics): your
email, password, position and the name of your car are removed, and the VIN is
masked. For more detail, enable debug logs:

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
- Entities are created from what the car reports when it is first seen. If it
  starts reporting something new later, reload the integration.

## Removal

1. Go to **Settings → Devices & services → My Porsche Connect**.
2. Click **⋮** on the entry, choose **Delete** and confirm. The device and its
   entities disappear. Nothing else is left: the integration stores nothing at
   Porsche, and your My Porsche account is untouched.
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
