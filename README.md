<!--
SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
SPDX-FileCopyrightText: 2026 BlueBell-XA

SPDX-License-Identifier: GPL-3.0-or-later
-->

# spoolman2klipper

`spoolman2klipper` is a small Moonraker client service that copies the active
Spoolman spool and filament metadata into Klipper macro variables.

It exists so other Klipper macros can synchronously read filament data such as
material, colour, recommended hotend temperature, bed temperature, diameter,
density, and remaining weight.

## How It Works

The service:

- connects to Moonraker over websocket
- listens for Moonraker `active_spool_set` notifications
- fetches the active spool from Spoolman
- writes a fixed set of fields into one Klipper holder macro with
  `SET_GCODE_VARIABLE`

The default holder macro is `SPOOLMAN`. Missing macros or missing variables are
skipped, so you can define only the variables you actually use.

## Klipper Macro

Add this holder macro to your Klipper config, or copy
`klipper-example-macros.cfg`.

```ini
[gcode_macro SPOOLMAN]
description: Holder macro populated by spoolman2klipper
variable_spool_id: -1
variable_filament_name: "''"
variable_material: "''"
variable_vendor: "''"
variable_color: "''"
variable_extruder_temp: 0
variable_bed_temp: 0
variable_diameter: 0.0
variable_density: 0.0
variable_remaining_weight: 0.0
variable_filament_weight: 0.0
gcode:
  {action_respond_info("Spoolman data holder macro")}
```

Other macros can then read the values:

```ini
[gcode_macro PRINT_START]
gcode:
  {% set spool = printer["gcode_macro SPOOLMAN"] %}
  {% if spool.extruder_temp > 0 %}
    M104 S{spool.extruder_temp}
  {% endif %}
  {% if spool.bed_temp > 0 %}
    M140 S{spool.bed_temp}
  {% endif %}
```

## Variables

- `spool_id`
- `filament_name`
- `material`
- `vendor`
- `color`
- `extruder_temp`
- `bed_temp`
- `diameter`
- `density`
- `remaining_weight`
- `filament_weight`

## Install

On the printer:

```sh
cd ~
git clone https://github.com/BlueBell-XA/spoolman2klipper.git
cd spoolman2klipper
python3 -m venv venv
venv/bin/pip3 install -r requirements.txt
```

Copy and edit the config:

```sh
mkdir -p ~/.config/spoolman2klipper
cp spoolman2klipper.cfg ~/.config/spoolman2klipper/spoolman2klipper.cfg
```

Default config:

```toml
[spoolman2klipper]
moonraker_url = "ws://localhost:7125/websocket"
spoolman_url = "http://localhost:7912/api"
klipper_macro = "SPOOLMAN"
sync_on_connect = true
reconnect_delay = 2.0
request_timeout = 5.0
```

## systemd

Generate and install the systemd service from the current repo path:

```sh
sudo ./scripts/install-service.sh
```

The installer uses the invoking sudo user by default. To force a user:

```sh
sudo SPOOLMAN2KLIPPER_USER=mks ./scripts/install-service.sh
```

Check status:

```sh
sudo systemctl status spoolman2klipper
```

## Mainsail / Moonraker Updates

Copy `moonraker-spoolman2klipper.cfg` next to `moonraker.conf`, then include it
from `moonraker.conf`:

```ini
[include moonraker-spoolman2klipper.cfg]
```

Moonraker update manager is configured to pull from:

```text
https://github.com/BlueBell-XA/spoolman2klipper.git
```

After this is configured, Mainsail should show updates when the GitHub repo has
new commits on `main`.

## Development

Create a venv and install dependencies:

```sh
python3 -m venv venv
venv/bin/pip3 install -r requirements-dev.txt
```

Run tests:

```sh
venv/bin/python -m pytest -q
```

Run lint:

```sh
make lint
```
