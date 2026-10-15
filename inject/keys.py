"""Key names -> bytes a terminal sends for them.

Keys are written straight into the pseudo-terminal that runs Claude Code, so they
reach only that process, whatever window has focus. That replaces a global
injector (pynput/xdotool/ydotool) and its focus guard, which don't work on
GNOME Wayland without root access to /dev/uinput.
"""

KEYS = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "enter": b"\r",
    "escape": b"\x1b",
    "space": b" ",
    "tab": b"\t",
    "shift+tab": b"\x1b[Z",
    "backspace": b"\x7f",
}


def encode(key: str) -> bytes:
    """Bytes for a key name like "up", "ctrl+c", "shift+tab" or a single character."""
    name = key.lower()
    if name in KEYS:
        return KEYS[name]
    if name.startswith("ctrl+") and len(name) == 6 and name[5].isalpha():
        return bytes([ord(name[5]) & 0x1F])
    if len(key) == 1:
        return key.encode()
    raise ValueError(f"unknown key {key!r}")
