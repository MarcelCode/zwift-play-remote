import asyncio
from pathlib import Path

import pytest

from daemon import DEFAULT_CONFIG, Binding, Config, Mapper, claude_command, load_config, parse_args
from inject.keys import encode
from zwiftplay.events import ButtonDown, ButtonUp


def make_config(**buttons: Binding) -> Config:
    return Config(
        command=["true"],
        controllers=1,
        long_press_ms=50,
        long_repeat_ms=20,
        hold_repeat_ms=10,
        buttons=buttons,
    )


def press(mapper: Mapper, button: str, seconds: float) -> None:
    async def go():
        mapper.handle(ButtonDown(button))
        await asyncio.sleep(seconds)
        mapper.handle(ButtonUp(button))
        await asyncio.sleep(0.03)

    asyncio.run(go())


def test_encode():
    assert encode("up") == b"\x1b[A"
    assert encode("Shift+Tab") == b"\x1b[Z"
    assert encode("ctrl+c") == b"\x03"
    assert encode("1") == b"1"
    with pytest.raises(ValueError):
        encode("hyper")


def test_tap_is_sent_on_press_once():
    sent = []
    press(Mapper(make_config(a=Binding(tap=b"\r")), sent.append), "a", 0.1)
    assert sent == [b"\r"]


def test_unmapped_button_is_ignored():
    sent = []
    press(Mapper(make_config(), sent.append), "a", 0.01)
    assert sent == []


def test_short_press_on_long_binding_sends_tap_on_release():
    sent = []
    press(Mapper(make_config(navigationUp=Binding(tap=b"U", long=b"P")), sent.append), "navigationUp", 0.01)
    assert sent == [b"U"]


def test_long_press_repeats_long_key_and_skips_tap():
    sent = []
    press(Mapper(make_config(navigationUp=Binding(tap=b"U", long=b"P")), sent.append), "navigationUp", 0.12)
    assert sent and set(sent) == {b"P"}


def test_hold_repeats_until_release():
    sent = []
    press(Mapper(make_config(y=Binding(hold=b" ")), sent.append), "y", 0.1)
    assert 5 <= len(sent) <= 12 and set(sent) == {b" "}


def test_default_config_loads():
    config = load_config(DEFAULT_CONFIG)
    assert config.command == ["claude", "agents"]
    assert config.buttons["a"] == Binding(tap=b"\r")
    assert config.buttons["y"] == Binding(toggle=b" ")


def test_unknown_button_is_rejected(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[buttons]\nX = "up"\n')
    with pytest.raises(ValueError, match="unknown button"):
        load_config(path)


def click(mapper: Mapper, button: str) -> None:
    mapper.handle(ButtonDown(button))
    mapper.handle(ButtonUp(button))


def test_toggle_repeats_from_first_press_until_second_press():
    sent = []
    mapper = Mapper(make_config(y=Binding(toggle=b" ")), sent.append)

    async def go():
        click(mapper, "y")
        await asyncio.sleep(0.1)
        click(mapper, "y")
        stopped_at = len(sent)
        await asyncio.sleep(0.05)
        return stopped_at

    stopped_at = asyncio.run(go())
    assert 5 <= len(sent) <= 12 and set(sent) == {b" "}
    assert len(sent) == stopped_at


def test_other_button_stops_toggle_before_its_key():
    sent = []
    mapper = Mapper(make_config(y=Binding(toggle=b" "), b=Binding(tap=b"\x1b")), sent.append)

    async def go():
        click(mapper, "y")
        await asyncio.sleep(0.05)
        click(mapper, "b")
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert sent[-1] == b"\x1b" and set(sent[:-1]) == {b" "}


@pytest.mark.parametrize(
    "argv, mode, wait, flags",
    [
        ([], "run", 30, []),
        (["--continue"], "run", 30, ["--continue"]),
        (["run", "--resume", "abc"], "run", 30, ["--resume", "abc"]),
        (["--wait", "0", "-r", "abc", "--model", "opus"], "run", 0, ["-r", "abc", "--model", "opus"]),
        (["events"], "events", 30, []),
    ],
)
def test_parse_args_forwards_unknown_flags_to_claude(argv, mode, wait, flags):
    parsed_mode, args, claude_flags = parse_args(argv)
    assert (parsed_mode, args.wait, claude_flags) == (mode, wait, flags)


def test_claude_command():
    config = make_config()
    config = Config(**{**config.__dict__, "command": ["claude", "agents"]})
    assert claude_command(config, []) == ["claude", "agents"]
    assert claude_command(config, ["--continue"]) == ["claude", "--continue"]
