"""Scan for Zwift controllers, connect, handshake and emit button events."""

import asyncio
import logging
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

    async def run(self) -> None:
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
            for task in sessions:
                task.cancel()
            await asyncio.gather(*sessions, return_exceptions=True)

    async def _session(self, device, kind: str) -> None:
        pressed: frozenset[str] = frozenset()
        battery = None

        def on_notify(_, data: bytearray) -> None:
            nonlocal pressed, battery
            data = bytes(data)
            buttons = protocol.decode_buttons(data)
            if buttons is not None:
                for event in diff(pressed, buttons):
                    self.on_event(event)
                pressed = buttons
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
            for event in diff(pressed, frozenset()):
                self.on_event(event)
            del self.connected[device.address]
        log.info("Disconnected %s. Press a button on it to wake it and reconnect.", kind)
