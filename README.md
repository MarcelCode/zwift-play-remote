# zwift-play-remote

Control Claude Code's agent view (`claude agents`) with Zwift Play or Zwift Click controllers over Bluetooth. You can steer several agents while riding an ERG workout.

```
Zwift Play ──BLE──▶ zwift-remote ──keystrokes──▶ pseudo-terminal running `claude agents`
```

The daemon connects to the controllers, performs the `RideOn` handshake and decodes button presses. It types the mapped keys straight into the pseudo-terminal that runs Claude Code. Your terminal stays wired to that pseudo-terminal too, so you can still use the keyboard.

Typing into Claude Code's own pseudo-terminal means keys only ever reach Claude Code, so a focus guard isn't needed. It also works on Wayland without root access to `/dev/uinput`. Global injectors like pynput, xdotool and ydotool can't do that.

## Setup

Requirements: Linux with BlueZ (macOS should work too, but it's untested), [uv](https://docs.astral.sh/uv/), and Claude Code 2.1.139 or newer.

```bash
git clone https://github.com/MarcelCode/zwift-play-remote
cd zwift-play-remote
uv sync
```

Disconnect the controllers from Zwift and Zwift Companion first, because only one host can be connected at a time. Run the ERG workout from another device, or connect your trainer to Zwift without the Play controllers.

## Usage

> **Press a button to wake the controllers.** Zwift Play and Zwift Click fall asleep when idle and are invisible over Bluetooth until you press a button. Press any button on **each** controller (both Play halves) when `zwift-remote` starts. That first press only wakes the controller and isn't forwarded to Claude Code. If a controller falls asleep mid-ride, press a button on it once more and it reconnects within a few seconds.

1. Check the controllers and the button names:

   ```bash
   uv run zwift-remote events
   ```

2. Ride:

   ```bash
   uv run zwift-remote run              # starts `claude agents`
   uv run zwift-remote run --wait 0     # don't wait for controllers
   uv run zwift-remote run claude       # any other command
   ```

   `run` waits up to 30 s for the controllers, or until you press Ctrl+C, and then starts Claude Code. Connection messages go to `~/.cache/zwift-play-remote.log` after that.

## Button map

Defaults in [`config.toml`](config.toml):

| Button | Key | Effect in Claude Code |
|---|---|---|
| D-pad left | `Left` | back out of a session to the agent list |
| D-pad right | `Right` | attach to selected session |
| D-pad up / down | `Up` / `Down`, long press `PgUp` / `PgDn` | move between sessions / scroll an attached session |
| A | `Enter` | attach / send reply / dispatch |
| B | `Escape` | close peek, clear input, interrupt |
| Y | hold `Space` | push-to-talk (voice mode `hold`) |
| Z | `Space` | peek at selected session |
| Left paddle | `1` | pick option 1 |
| Right paddle | `2` | pick option 2 |
| Click − / + | `Up` / `Down` | move between sessions |

Typical loop: `←` → `Z` on the top row → hold `Y` and talk → `A` → `←`.

Push-to-talk repeats the key every 30 ms while Y is held, the way keyboard auto-repeat does. Claude Code's voice dictation treats that as a held key. If you changed the push-to-talk key in `~/.claude/keybindings.json`, change `y = { hold = "..." }` to match.

Binding types: `"key"` is sent on press. `{ tap = "k", long = "k2" }` sends `k` on a short press and repeats `k2` on a long press. `{ hold = "k" }` repeats `k` while the button is held.

## Notifications

[`hooks/agent-needs-input.sh`](hooks/agent-needs-input.sh) shows a desktop notification and plays a sound when an agent waits for input. To use it, add the snippet from [`hooks/settings.example.json`](hooks/settings.example.json) to `~/.claude/settings.json`.

## Supported controllers

| Controller | Protocol | Status |
|---|---|---|
| Zwift Play, firmware 1.x (up to 1.3.1) | `PlayKeyPadStatus` | implemented |
| Zwift Play, firmware 2.x (2.0.1) | `RideKeyPadStatus` | implemented |
| Zwift Click | `ClickKeyPadStatus` | implemented |
| Zwift Ride | `RideKeyPadStatus` | implemented, untested |
| Zwift Click v2 / Ride v2 on locked firmware | needs Zwift unlock | not supported |

The decoders are unit-tested against the documented protocol but haven't been verified on hardware yet. Once you have, record your working firmware versions here, and don't update the firmware without checking that the controllers still connect afterwards. Protocol details and sources are in [`docs/protocol.md`](docs/protocol.md).

## Troubleshooting

- **Nothing found:** press a button on the controller. Also check that nothing else (Zwift, Companion, a phone) is connected to it, and that `bluetoothctl show` reports `Powered: yes`.
- **Connects then drops immediately:** run `bluetoothctl remove <address>` to remove the controller pairing in BlueZ, then try again.
- **A key does the wrong thing:** agent view is a research preview and its shortcuts may change. Edit `config.toml`.

## Development

```bash
uv run pytest
```

Layout: `zwiftplay/protocol.py` (UUIDs, protobuf decoding), `zwiftplay/ble.py` (scan, connect, handshake, events), `inject/keys.py` (key names → terminal bytes), `daemon.py` (config, button mapper, pseudo-terminal wrapper). The original brief is [`zwift-play-claude-code-remote.md`](zwift-play-claude-code-remote.md).
