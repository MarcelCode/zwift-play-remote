"""Zwift controllers -> keystrokes for Claude Code's agent view.

`zwift-remote` starts `claude agents` (or `claude <flags>`) in a pseudo-terminal and
types into it when controller buttons are pressed. `zwift-remote events` only prints events.
"""

import argparse
import asyncio
import fcntl
import logging
import os
import pty
import signal
import sys
import termios
import time
import tomllib
import tty
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from inject.keys import encode
from zwiftplay import protocol
from zwiftplay.ble import WAKE_HINT, ControllerManager, disconnect_all
from zwiftplay.events import ButtonDown, ButtonUp

DEFAULT_CONFIG = Path(__file__).with_name("config.toml")
LOG_FILE = Path.home() / ".cache" / "zwift-play-remote.log"

log = logging.getLogger("zwift-remote")


@dataclass(frozen=True)
class Binding:
    tap: bytes | None = None  # sent on press (or on release if `long` is set and wasn't reached)
    long: bytes | None = None  # sent after a long press, repeated while held
    hold: bytes | None = None  # repeated while held, like keyboard auto-repeat (push-to-talk)
    toggle: bytes | None = None  # like `hold`, but from one press until the next press of any button


@dataclass(frozen=True)
class Config:
    command: list[str]
    controllers: int
    long_press_ms: int
    long_repeat_ms: int
    hold_repeat_ms: int
    buttons: dict[str, Binding]


def load_config(path: Path) -> Config:
    raw = tomllib.loads(path.read_text())
    buttons = {}
    for name, spec in raw.get("buttons", {}).items():
        if name not in protocol.BUTTONS:
            raise ValueError(f"{path}: unknown button {name!r}, expected one of {sorted(protocol.BUTTONS)}")
        if isinstance(spec, str):
            spec = {"tap": spec}
        buttons[name] = Binding(**{kind: encode(key) for kind, key in spec.items()})
    return Config(
        command=raw.get("command", ["claude", "agents"]),
        controllers=raw.get("controllers", 2),
        long_press_ms=raw.get("long_press_ms", 500),
        long_repeat_ms=raw.get("long_repeat_ms", 150),
        hold_repeat_ms=raw.get("hold_repeat_ms", 30),
        buttons=buttons,
    )


class Mapper:
    """Turns button events into key bytes according to the config."""

    def __init__(self, config: Config, send: Callable[[bytes], None]):
        self.config = config
        self.send = send
        self._held: dict[str, asyncio.Task] = {}
        self._long_fired: set[str] = set()
        self._toggled: dict[str, asyncio.Task] = {}

    def handle(self, event: ButtonDown | ButtonUp) -> None:
        binding = self.config.buttons.get(event.button)
        if binding is None:
            return
        if isinstance(event, ButtonDown):
            # Any press ends a running toggle first, so e.g. Escape isn't followed by more repeats.
            stopped = self._stop_toggles()
            if binding.toggle:
                if event.button not in stopped:
                    self._toggled[event.button] = asyncio.get_running_loop().create_task(
                        self._repeat(binding.toggle, self.config.hold_repeat_ms)
                    )
            elif binding.hold:
                self._start(event.button, self._repeat(binding.hold, self.config.hold_repeat_ms))
            elif binding.long:
                self._start(event.button, self._long_press(event.button, binding.long))
            elif binding.tap:
                self.send(binding.tap)
            return
        task = self._held.pop(event.button, None)
        if task is None:
            return
        task.cancel()
        if binding.long and binding.tap and event.button not in self._long_fired:
            self.send(binding.tap)
        self._long_fired.discard(event.button)

    def _stop_toggles(self) -> set[str]:
        for task in self._toggled.values():
            task.cancel()
        stopped = set(self._toggled)
        self._toggled.clear()
        return stopped

    def _start(self, button: str, coro) -> None:
        self._held[button] = asyncio.get_running_loop().create_task(coro)

    async def _repeat(self, key: bytes, interval_ms: int) -> None:
        while True:
            self.send(key)
            await asyncio.sleep(interval_ms / 1000)

    async def _long_press(self, button: str, key: bytes) -> None:
        await asyncio.sleep(self.config.long_press_ms / 1000)
        self._long_fired.add(button)
        await self._repeat(key, self.config.long_repeat_ms)


def _write_all(fd: int, data: bytes) -> None:
    while data:
        data = data[os.write(fd, data) :]


async def run_in_pty(command: list[str], on_start: Callable[[Callable[[bytes], None]], None]) -> int:
    """Run `command` in a pseudo-terminal wired to ours. `on_start` gets a function that types into it."""
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.execvp(command[0], command)
        finally:
            os._exit(127)

    loop = asyncio.get_running_loop()
    stdin, stdout = sys.stdin.fileno(), sys.stdout.fileno()
    done = loop.create_future()

    def resize() -> None:
        fcntl.ioctl(master, termios.TIOCSWINSZ, fcntl.ioctl(stdout, termios.TIOCGWINSZ, b"\0" * 8))

    def from_child() -> None:
        try:
            data = os.read(master, 65536)
        except OSError:  # EIO once the child has exited
            data = b""
        if not data:
            loop.remove_reader(master)
            if not done.done():
                done.set_result(None)
            return
        _write_all(stdout, data)

    resize()
    saved = termios.tcgetattr(stdin)
    tty.setraw(stdin)
    loop.add_reader(stdin, lambda: _write_all(master, os.read(stdin, 65536)))
    loop.add_reader(master, from_child)
    loop.add_signal_handler(signal.SIGWINCH, resize)
    on_start(lambda data: _write_all(master, data))
    try:
        await done
    finally:
        loop.remove_signal_handler(signal.SIGWINCH)
        loop.remove_reader(stdin)
        termios.tcsetattr(stdin, termios.TCSAFLUSH, saved)
        os.close(master)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


async def run(config: Config, command: list[str], wait_seconds: float, console: logging.Handler) -> int:
    mapper: Mapper | None = None

    def on_event(event: ButtonDown | ButtonUp) -> None:
        log.debug("%s", event)
        if mapper:
            mapper.handle(event)

    def on_start(send: Callable[[bytes], None]) -> None:
        nonlocal mapper
        mapper = Mapper(config, send)

    manager = ControllerManager(on_event)
    ble_task = asyncio.create_task(manager.run())
    print(WAKE_HINT)
    print(f"Waiting up to {wait_seconds:.0f}s for {config.controllers} controller(s)... (Ctrl+C to skip)")
    deadline = time.monotonic() + wait_seconds
    try:
        while len(manager.connected) < config.controllers and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        pass
    # From here on the terminal belongs to Claude Code; keep logging to the file only.
    logging.getLogger().removeHandler(console)
    try:
        return await run_in_pty(command, on_start)
    finally:
        logging.getLogger().addHandler(console)
        ble_task.cancel()
        await asyncio.gather(ble_task, return_exceptions=True)


async def print_events() -> None:
    def on_event(event: ButtonDown | ButtonUp) -> None:
        print(f"{type(event).__name__:<10} {event.button}", flush=True)

    print(WAKE_HINT)
    await ControllerManager(on_event).run()


def parse_args(argv: list[str]) -> tuple[str, argparse.Namespace, list[str]]:
    """Split the command line into mode, our own options and the flags meant for Claude Code."""
    parser = argparse.ArgumentParser(
        prog="zwift-remote",
        usage="zwift-remote [run | events] [--config PATH] [--wait SECONDS] [CLAUDE_FLAGS ...]",
        description=__doc__.splitlines()[0],
        epilog="Without CLAUDE_FLAGS this starts `claude agents`. Any other flags go to `claude`, "
        "e.g. `zwift-remote --continue` or `zwift-remote --resume`.",
        allow_abbrev=False,
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--wait", type=float, default=30, help="seconds to wait for controllers before starting")
    mode = argv[0] if argv[:1] in (["run"], ["events"]) else "run"
    args, claude_flags = parser.parse_known_args(argv[1:] if argv[:1] == [mode] else argv)
    return mode, args, claude_flags


def claude_command(config: Config, claude_flags: list[str]) -> list[str]:
    # `claude agents` doesn't take session flags like --continue/--resume, so flags go to plain `claude`.
    return [config.command[0], *claude_flags] if claude_flags else config.command


def main() -> None:
    mode, args, claude_flags = parse_args(sys.argv[1:])

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), console],
    )

    try:
        if mode == "events":
            asyncio.run(print_events())
        else:
            config = load_config(args.config)
            sys.exit(asyncio.run(run(config, claude_command(config, claude_flags), args.wait, console)))
    except KeyboardInterrupt:
        pass
    finally:
        # A second Ctrl+C interrupts the graceful disconnect; make sure the controllers are released anyway.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        asyncio.run(disconnect_all())


if __name__ == "__main__":
    main()
