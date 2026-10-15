"""Scan for Zwift controllers, connect, handshake and emit button events."""

import asyncio
import logging
import shutil
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from . import protocol
from .events import ButtonDown, ButtonUp, diff

log = logging.getLogger(__name__)

WAKE_HINT = (
    "Press any button on each Zwift controller to wake it up. "
    "Controllers only advertise for a short while after a button press and fall asleep when idle."
)


class ControllerManager:
    """Keeps every Zwift controller in range connected and forwards its button events."""

    def __init__(self, on_event: Callable[[ButtonDown | ButtonUp], None], scan_seconds: float = 5.0):
        self.on_event = on_event
        self.scan_seconds = scan_seconds
        self.connected: dict[str, str] = {}  # address -> controller kind
        self._pressed: dict[str, frozenset[str]] = {}  # address -> buttons it reports held

    def _update(self, address: str, buttons: frozenset[str]) -> None:
        # A button is held while any controller reports it: the left Click v2 relays
        # the right one's buttons, so the same press arrives from both.
        before = frozenset().union(*self._pressed.values())
        self._pressed[address] = buttons
        for event in diff(before, frozenset().union(*self._pressed.values())):
            self.on_event(event)

    async def run(self) -> None:
        await disconnect_all()
        sessions: set[asyncio.Task] = set()
        try:
            while True:
                found = await BleakScanner.discover(timeout=self.scan_seconds, return_adv=True)
                for address, (device, adv) in found.items():
                    kind = protocol.controller_kind(adv.manufacturer_data)
                    if kind is None or address in self.connected:
                        continue
                    self.connected[address] = kind
                    task = asyncio.create_task(self._session(device, kind))
                    sessions.add(task)
                    task.add_done_callback(sessions.discard)
                await asyncio.sleep(1)
        finally:
            if sessions:
                log.info("Disconnecting %d controller(s)...", len(sessions))
            for task in sessions:
                task.cancel()
            await asyncio.gather(*sessions, return_exceptions=True)

    async def _session(self, device, kind: str) -> None:
        battery = None

        def on_notify(_, data: bytearray) -> None:
            nonlocal battery
            data = bytes(data)
            buttons = protocol.decode_buttons(data)
            if buttons is not None:
                self._update(device.address, buttons)
            elif (level := protocol.decode_battery(data)) is not None and level != battery:
                battery = level
                log.info("%s battery %d%%", kind, level)

        disconnected = asyncio.Event()
        try:
            async with BleakClient(device, disconnected_callback=lambda _: disconnected.set()) as client:
                await client.start_notify(protocol.ASYNC_UUID, on_notify)
                await client.start_notify(protocol.SYNC_TX_UUID, on_notify)
                await client.write_gatt_char(protocol.SYNC_RX_UUID, protocol.RIDE_ON, response=False)
                log.info("Connected %s (%s)", kind, device.address)
                await disconnected.wait()
        except (BleakError, TimeoutError) as e:
            log.warning("%s (%s): %s", kind, device.address, e)
        finally:
            self._update(device.address, frozenset())
            del self._pressed[device.address]
            del self.connected[device.address]
        log.info("Disconnected %s. Press a button on it to wake it and reconnect.", kind)


async def disconnect_all() -> None:
    """Disconnect every Zwift controller BlueZ holds, e.g. from a run that was killed or crashed.

    BlueZ keeps a connection open after its client dies, and a connected controller
    doesn't advertise, so the scan would never find it again.
    """
    if not shutil.which("bluetoothctl"):
        return
    devices = await _bluetoothctl("devices", "Connected")
    for line in devices.splitlines():
        parts = line.split(" ", 2)  # "Device <address> <name>"
        if len(parts) == 3 and parts[2].startswith("Zwift"):
            log.info("Disconnecting %s (%s)", parts[2], parts[1])
            await _bluetoothctl("disconnect", parts[1])


async def _bluetoothctl(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    return stdout.decode(errors="replace")
