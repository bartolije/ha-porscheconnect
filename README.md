# Porsche Connect for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![pre-commit][pre-commit-shield]][pre-commit]
[![Black][black-shield]][black]

[![hacs][hacs_badge]][hacs]
[![Project Maintenance][maintenance-shield]][user_profile]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]

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

- **Taycan** (BEV)
- **Macan EV**
- **Cayenne** (PHEV / ICE, E3 generation, 2017+)
- **Panamera** (PHEV / ICE, G2 PA, 2021+)
- **911** (ICE, 992 generation)
- **718 Boxster / Cayman** (ICE)

ICE-only cars naturally do not expose state-of-charge, charging or
electric-range entities. PHEVs expose both fuel-level and battery sensors.

To verify your specific model and equipment, see
<https://connect-store.porsche.com/> — select your car and check whether the
*Porsche Connect* services package is available.

## Supported entities and capabilities

Detailed matrix to be added in a follow-up commit.

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

## Examples

Concrete Lovelace and automation examples to be added in a follow-up commit.

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
- **No diagnostics platform yet.** Bug reports must rely on the debug log
  recipe above.

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
[GitHub issue tracker](https://github.com/CJNE/ha-porscheconnect/issues).
General usage questions go to
[Discussions](https://github.com/CJNE/ha-porscheconnect/discussions),
the [HA Community Forum][forum], or [Discord][discord].

If you want to contribute code, read
[CONTRIBUTING.md](https://github.com/CJNE/ha-porscheconnect/blob/main/CONTRIBUTING.md)
first — it covers the dev container, pre-commit hooks, and the test layout.

---

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[black]: https://github.com/psf/black
[black-shield]: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
[buymecoffee]: https://www.buymeacoffee.com/cjne.coffee
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/CJNE/ha-porscheconnect.svg?style=for-the-badge
[commits]: https://github.com/CJNE/ha-porscheconnect/commits/main
[hacs]: https://hacs.xyz
[hacs_badge]: https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/CJNE/ha-porscheconnect.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40CJNE-blue.svg?style=for-the-badge
[pre-commit]: https://github.com/pre-commit/pre-commit
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/CJNE/ha-porscheconnect.svg?style=for-the-badge
[releases]: https://github.com/CJNE/ha-porscheconnect/releases
[user_profile]: https://github.com/CJNE
