# Gimbal serial protocol

USB serial, 115200 baud, 8N1. One ASCII text line per message, ending in `\n`.
Angles are degrees. Azimuth: 0 = north, 90 = east. Elevation: 0 = level, 90 = straight up.

## Laptop to controller

| Line | Meaning |
|---|---|
| `T,<az>,<el>,<az_rate>,<el_rate>` | New target. Rates are degrees per second. Sent once a second while tracking. Example: `T,142.500,45.200,0.3100,0.0500` |
| `HOME` | Declare the current physical pose to be north and level (no endstops yet). Aim the gimbal first. |
| `PARK` | Go to straight up (elevation 90). |
| `STOP` | Stop moving and release any target. |
| `PING` | Connectivity check. |

## Controller to laptop

| Line | Meaning |
|---|---|
| `READY` | Booted and drivers enabled. |
| `POS,<az>,<el>,<state>` | Position report, twice a second. State is `IDLE`, `TRACKING`, `PARKING` or `PARKED`. |
| `OK,<cmd>` | Command accepted. |
| `PONG` | Reply to `PING`. |
| `ERR,<code>` | `BAD_NUMBER`, `UNKNOWN_COMMAND`, `LINE_TOO_LONG` or `WATCHDOG`. |

## Safety behaviour

- **Watchdog:** if no `T` line arrives for 5 seconds while tracking, the controller stops moving and reports `ERR,WATCHDOG`. A crashed laptop or unplugged cable cannot leave the gimbal running.
- **Below the horizon:** the server does not send targets with negative elevation, so the watchdog stops the motors.
- **Limits:** elevation is clamped to 0 to 90. Azimuth is a continuous angle limited to the cable range, and the controller picks the shortest legal path (359 to 1 degree is a 2 degree move).
- **Smooth motion:** between updates the controller extrapolates the target using the rates, so the motors glide instead of stepping once a second.