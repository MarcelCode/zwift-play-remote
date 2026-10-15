"""Zwift controller BLE protocol: UUIDs, handshake and button decoding.

See docs/protocol.md for where these values come from.
"""

SERVICE_UUID = "00000001-19ca-4651-86e5-fa29dcdd09d1"
ASYNC_UUID = "00000002-19ca-4651-86e5-fa29dcdd09d1"  # notify: button state
SYNC_RX_UUID = "00000003-19ca-4651-86e5-fa29dcdd09d1"  # write: commands to the device
SYNC_TX_UUID = "00000004-19ca-4651-86e5-fa29dcdd09d1"  # indicate: responses

MANUFACTURER_ID = 0x094A  # Zwift, Inc.

# Writing just "RideOn" (no public key) puts the controller in unencrypted mode.
RIDE_ON = b"RideOn"

# First byte of the manufacturer data in the advertisement.
DEVICE_TYPES = {
    0x02: "Play right",
    0x03: "Play left",
    0x07: "Ride right",
    0x08: "Ride left",
    0x09: "Click",
    0x0A: "Click v2 right",
    0x0B: "Click v2 left",
    0x0E: "Play (fw 2)",
}

# First byte of every notification.
PLAY_NOTIFICATION = 0x07
CLICK_NOTIFICATION = 0x37
RIDE_NOTIFICATION = 0x23
BATTERY_NOTIFICATION = 0x19

# PlayButtonStatus: buttons are active-low.
ON = 0

# PlayKeyPadStatus field number -> button. Field 1 tells which half sent it.
PLAY_RIGHT = {2: "y", 3: "z", 4: "a", 5: "b", 6: "onOffRight", 7: "sideButtonRight"}
PLAY_LEFT = {
    2: "navigationUp",
    3: "navigationLeft",
    4: "navigationRight",
    5: "navigationDown",
    6: "onOffLeft",
    7: "sideButtonLeft",
}
PLAY_PADDLE_THRESHOLD = 100

# ClickKeyPadStatus field number -> button.
CLICK = {1: "shiftUpRight", 2: "shiftUpLeft"}

# RideKeyPadStatus.ButtonMap bit -> button (bit cleared = pressed).
RIDE_MASKS = {
    0x00001: "navigationLeft",
    0x00002: "navigationUp",
    0x00004: "navigationRight",
    0x00008: "navigationDown",
    0x00010: "a",
    0x00020: "b",
    0x00040: "y",
    0x00080: "z",
    0x00100: "shiftUpLeft",
    0x00200: "shiftDownLeft",
    0x00400: "powerUpLeft",
    0x00800: "onOffLeft",
    0x01000: "shiftUpRight",
    0x02000: "shiftDownRight",
    0x04000: "powerUpRight",
    0x08000: "onOffRight",
}
RIDE_PADDLES = {0: "paddleLeft", 1: "paddleRight"}
RIDE_PADDLE_THRESHOLD = 25

BUTTONS = frozenset(
    [*PLAY_RIGHT.values(), *PLAY_LEFT.values(), *CLICK.values(), *RIDE_MASKS.values(), *RIDE_PADDLES.values()]
)


def controller_kind(manufacturer_data: dict[int, bytes]) -> str | None:
    """Return the controller type from advertisement data, or None if it isn't one."""
    data = manufacturer_data.get(MANUFACTURER_ID)
    if not data:
        return None
    return DEVICE_TYPES.get(data[0])


def decode_buttons(data: bytes) -> frozenset[str] | None:
    """Return the buttons held down in a button notification, None for other messages."""
    if not data:
        return None
    kind, payload = data[0], data[1:]
    if kind == PLAY_NOTIFICATION:
        return _decode_play(payload)
    if kind == CLICK_NOTIFICATION:
        fields = _fields(payload)
        return frozenset(name for num, name in CLICK.items() if _first(fields, num) == ON)
    if kind == RIDE_NOTIFICATION:
        return _decode_ride(payload)
    return None


def decode_battery(data: bytes) -> int | None:
    """Return the battery percentage from a battery notification, None for other messages."""
    # The level is the value of the payload's single varint field: field 1 on the Play, field 2 on the Click v2.
    if len(data) < 3 or data[0] != BATTERY_NOTIFICATION:
        return None
    return data[2]


def _decode_play(payload: bytes) -> frozenset[str]:
    fields = _fields(payload)
    right = _first(fields, 1) == ON
    names = PLAY_RIGHT if right else PLAY_LEFT
    pressed = {name for num, name in names.items() if _first(fields, num) == ON}
    if abs(_zigzag(_first(fields, 8))) >= PLAY_PADDLE_THRESHOLD:
        pressed.add("paddleRight" if right else "paddleLeft")
    return frozenset(pressed)


def _decode_ride(payload: bytes) -> frozenset[str]:
    fields = _fields(payload)
    button_map = _first(fields, 1)
    pressed = {name for mask, name in RIDE_MASKS.items() if not button_map & mask}
    for raw in fields.get(3, []):
        analog = _fields(raw)
        name = RIDE_PADDLES.get(_first(analog, 1))
        if name and abs(_zigzag(_first(analog, 2))) >= RIDE_PADDLE_THRESHOLD:
            pressed.add(name)
    return frozenset(pressed)


def _first(fields: dict[int, list], num: int) -> int:
    # Missing fields take the protobuf default (0, which is ON for buttons).
    return fields.get(num, [0])[0]


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _fields(buf: bytes) -> dict[int, list]:
    """Minimal protobuf decoder: field number -> list of varints or byte strings."""
    fields: dict[int, list] = {}
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        num, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 2:
            length, pos = _varint(buf, pos)
            value, pos = buf[pos : pos + length], pos + length
        elif wire == 1:
            value, pos = buf[pos : pos + 8], pos + 8
        elif wire == 5:
            value, pos = buf[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        fields.setdefault(num, []).append(value)
    return fields
