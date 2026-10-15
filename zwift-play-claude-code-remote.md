# Zwift Play → Claude Code remote

Project brief / handoff for Claude Code. Goal: control Claude Code's agent view from Zwift Play controllers over Bluetooth, so I can ride in ERG mode and still steer several agents.

## What we're building

A small background daemon that:

1. Connects to both Zwift Play controllers over BLE.
2. Performs Zwift's proprietary handshake and decrypts button events.
3. Maps each button to a keystroke (or key chord) injected into the terminal that is running `claude agents`.

No tmux, no terminal tabs. One terminal, Claude Code agent view, multiple background sessions.

## Target workflow on the bike

Claude Code agent view (`claude agents`, research preview, needs v2.1.139+):

- `←` on an empty prompt backgrounds the current session and opens agent view with that row selected.
- In agent view: `↑`/`↓` move between rows, `→` or `Enter` attach, `Space` opens the peek panel (shows the question a session is waiting on + a reply box), `Esc` closes peek / clears input / exits.
- Sessions that need input are sorted to the top of the list.
- Voice dictation is built in: hold/tap the push-to-talk key in the peek reply box, the dispatch input, or an attached session.
- Peek panel: numbered choices can be picked with number keys; `Tab` fills a suggested reply.
- Agent view fires the `Notification` hook with `agent_needs_input` / `agent_completed` and uses the terminal notification channel.

Typical loop: `←` → list → `Space` on the top row → PTT to dictate → `Enter` → `←`. Rarely need to attach.

## Button map (v1)

Zwift Play: two controllers, D-pad on the left, A/B/Y/Z on the right, one steering paddle + one orange shoulder button per side.

| Button | Key | Effect in Claude Code |
|---|---|---|
| D-pad left | `Left` | Back out of session to agent list |
| D-pad right | `Right` | Attach to selected session |
| D-pad up / down | `Up` / `Down` | Move between sessions (also hops between peeks) |
| A | `Enter` | Attach / send reply / dispatch |
| B | `Escape` | Close peek, clear input, interrupt response |
| Y | push-to-talk key (configure in Claude Code voice dictation) | Dictate reply / new task / prompt |
| Z | `Space` | Peek at selected session |
| Left paddle | `1` | Pick option 1 in a peeked question |
| Right paddle | `2` | Pick option 2 (alt: `Shift+Tab` for permission mode) |

Nice-to-have: long-press up/down → `PgUp`/`PgDn` for scrolling inside an attached session (attached sessions are fullscreen; arrow keys don't scroll there).

Keep the map in a config file (TOML/YAML); agent view shortcuts may change during preview.

## Technical notes

### BLE / Zwift Play protocol

- Controllers use a custom encrypted protocol, not BLE HID. Nordic nRF52832 inside.
- Messages are protobuf, encrypted after a key-exchange handshake on a vendor-specific service. Zwift calls it "ZAP" internally.
- Reverse-engineering reference: https://github.com/ajchellew/zwiftplay — has the handshake, key derivation, characteristic UUIDs, and message decoding (originally Android/Kotlin). There are community Python/Node ports built on it; find one first before re-implementing.
- Only one host can be paired at a time, so Zwift itself cannot use the controllers while the daemon owns them. ERG workout must run from another device/app.
- Firmware updates may break the handshake; pin the known-working firmware version in the README.

### Keystroke injection

- Python + `bleak` for BLE (cross-platform).
- Key injection: `pynput` (macOS/Linux/Windows). On Linux, `ydotool` for Wayland or `xdotool` for X11 are alternatives.
- Global injection goes to whatever window has focus. Guard: only inject when the terminal app is frontmost (`NSWorkspace` on macOS, `xdotool getactivewindow` on Linux); otherwise drop the press.
- Push-to-talk needs press/release semantics, not a single tap. The BLE layer must expose button-down and button-up events separately.

### Notifications (optional)

- A Claude Code `Notification` hook on `agent_needs_input` could trigger a sound, a desktop notification, or flash the Zwift Play LEDs (write path exists in the reverse-engineered protocol).

## Suggested project layout

```
zwift-play-remote/
  README.md
  config.toml            # button → key map, terminal app name, PTT key
  zwiftplay/
    ble.py               # scan, connect, handshake, decrypt notifications
    protocol.py          # protobuf message definitions / parsing
    events.py            # ButtonDown / ButtonUp dataclasses
  inject/
    keys.py              # pynput wrapper, focus guard
  daemon.py              # event loop: ble events → config lookup → inject
  tests/
```

## Tasks for Claude Code

1. Research: check the ajchellew/zwiftplay repo and any Python ports; document the handshake and the exact characteristic UUIDs and button event encoding in `docs/protocol.md`.
2. Implement `zwiftplay/ble.py` with `bleak`: scan for both controllers, connect, handshake, decrypt, yield `ButtonDown`/`ButtonUp` events. Start with a CLI that just prints events.
3. Implement `inject/keys.py` with a focus guard.
4. Implement `daemon.py` with the config-driven map above, including press/release for the PTT key and long-press detection.
5. Add a `Notification` hook example for `agent_needs_input`.
6. Test end to end with `claude agents` and two or three background sessions.

## Open questions

- Which push-to-talk key is configured in Claude Code voice dictation on this machine?
- macOS or Linux as the primary target? (Determines the focus-guard implementation.)
- Is there a maintained Python port of the Zwift Play protocol, or do we port from Kotlin?
- Current Zwift Play firmware version on my controllers.
