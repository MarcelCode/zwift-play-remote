from zwiftplay import protocol
from zwiftplay.events import ButtonDown, ButtonUp, diff

ON, OFF = 0, 1


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field(num: int, value: int | bytes) -> bytes:
    if isinstance(value, bytes):
        return varint(num << 3 | 2) + varint(len(value)) + value
    return varint(num << 3) + varint(value)


def zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 31)


def play(right: bool, pressed: set[int] = frozenset(), analog_lr: int = 0) -> bytes:
    body = field(1, ON if right else OFF)
    body += b"".join(field(n, ON if n in pressed else OFF) for n in range(2, 8))
    body += field(8, zigzag(analog_lr)) + field(9, 0)
    return bytes([protocol.PLAY_NOTIFICATION]) + body


def test_play_idle():
    assert protocol.decode_buttons(play(right=True)) == frozenset()
    assert protocol.decode_buttons(play(right=False)) == frozenset()


def test_play_right_buttons():
    assert protocol.decode_buttons(play(right=True, pressed={2, 4})) == {"y", "a"}
    assert protocol.decode_buttons(play(right=True, pressed={3, 5, 6, 7})) == {"z", "b", "onOffRight", "sideButtonRight"}


def test_play_left_buttons_are_the_dpad():
    assert protocol.decode_buttons(play(right=False, pressed={2, 3, 4, 5})) == {
        "navigationUp",
        "navigationLeft",
        "navigationRight",
        "navigationDown",
    }


def test_play_paddles_only_at_full_travel():
    assert protocol.decode_buttons(play(right=True, analog_lr=100)) == {"paddleRight"}
    assert protocol.decode_buttons(play(right=False, analog_lr=-100)) == {"paddleLeft"}
    assert protocol.decode_buttons(play(right=False, analog_lr=-60)) == frozenset()


def test_click():
    msg = bytes([protocol.CLICK_NOTIFICATION]) + field(1, ON) + field(2, OFF)
    assert protocol.decode_buttons(msg) == {"shiftUpRight"}


def test_ride_button_map_is_active_low():
    all_released = 0xFFFFFFFF
    msg = bytes([protocol.RIDE_NOTIFICATION]) + field(1, all_released & ~0x10 & ~0x02)
    assert protocol.decode_buttons(msg) == {"a", "navigationUp"}


def test_ride_analog_paddles():
    paddle = field(3, field(1, 1) + field(2, zigzag(-80)))
    weak = field(3, field(1, 0) + field(2, zigzag(10)))
    msg = bytes([protocol.RIDE_NOTIFICATION]) + field(1, 0xFFFFFFFF) + paddle + weak
    assert protocol.decode_buttons(msg) == {"paddleRight"}


def test_other_messages_are_not_buttons():
    assert protocol.decode_buttons(b"") is None
    assert protocol.decode_buttons(b"RideOn\x01\x04") is None
    assert protocol.decode_buttons(bytes([0x15])) is None


def test_battery():
    assert protocol.decode_battery(bytes([0x19, 0x08, 87])) == 87
    assert protocol.decode_battery(play(right=True)) is None


def test_controller_kind():
    assert protocol.controller_kind({0x094A: bytes([0x03, 0xAA])}) == "Play left"
    assert protocol.controller_kind({0x094A: bytes([0x09])}) == "Click"
    assert protocol.controller_kind({0x094A: bytes([0x99])}) is None
    assert protocol.controller_kind({0x004C: bytes([0x03])}) is None


def test_diff_releases_first():
    assert diff(frozenset({"a", "y"}), frozenset({"y", "z"})) == [ButtonUp("a"), ButtonDown("z")]


def test_click_v2_battery():
    # Captured from a Click v2: the level is in field 2, not field 1.
    assert protocol.decode_battery(bytes.fromhex("191064")) == 100


def test_click_v2_captured_presses():
    assert protocol.decode_buttons(bytes.fromhex("2308fffeffff0f")) == {"z"}
    assert protocol.decode_buttons(bytes.fromhex("2308fdffffff0f")) == {"navigationUp"}
    assert protocol.decode_buttons(bytes.fromhex("2308ffdfffff0f")) == {"shiftUpRight"}
    assert protocol.decode_buttons(bytes.fromhex("2308ffffffff0f")) == frozenset()
