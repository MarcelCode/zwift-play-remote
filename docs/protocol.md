# Zwift controller BLE protocol

What this project relies on. Sources:

- [ajchellew/zwiftplay](https://github.com/ajchellew/zwiftplay): original reverse engineering (Kotlin/C#)
- [OpenBikeControl/bikecontrol](https://github.com/OpenBikeControl/bikecontrol) (formerly SwiftControl): maintained Flutter app, `lib/bluetooth/devices/zwift/`
- [cagnulein/qdomyos-zwift](https://github.com/cagnulein/qdomyos-zwift): `zwift_hub.proto` has the keypad messages

No maintained Python port turned up, so `zwiftplay/` is a small reimplementation and doesn't depend on a protobuf library.

## Discovery

Controllers advertise manufacturer data with company ID `0x094A` (Zwift, Inc.). The first byte is the device type:

| Byte | Device |
|---|---|
| `0x02` | Zwift Play, right half (firmware 1.x) |
| `0x03` | Zwift Play, left half (firmware 1.x) |
| `0x0E` | Zwift Play on firmware 2.x (speaks the Ride protocol) |
| `0x09` | Zwift Click |
| `0x0A` / `0x0B` | Zwift Click v2 right / left (unconfirmed) |
| `0x07` / `0x08` | Zwift Ride right / left |

Controllers sleep when idle and only advertise for a while after **a button press**. Each Play half is a separate BLE peripheral, so you have to press a button on each. A controller can be connected to only one host at a time.

## GATT

Service `00000001-19ca-4651-86e5-fa29dcdd09d1`. Newer Ride-protocol devices use `0000fc82-0000-1000-8000-00805f9b34fb` with the same characteristics:

| UUID | Name | Properties | Use |
|---|---|---|---|
| `00000002-19ca-4651-86e5-fa29dcdd09d1` | ASYNC | notify | button state, battery |
| `00000003-19ca-4651-86e5-fa29dcdd09d1` | SYNC_RX | write (no response) | commands to the device |
| `00000004-19ca-4651-86e5-fa29dcdd09d1` | SYNC_TX | indicate | command responses |

## Handshake

Zwift's own app writes `RideOn` + `01 02` + a 64-byte P-256 public key and then speaks AES-encrypted messages. That isn't needed. Writing just the 6 ASCII bytes `RideOn` (`52 69 64 65 4f 6e`) to SYNC_RX makes the controller answer on SYNC_TX (`RideOn 01 03` from a Click, `RideOn 01 04` from a Play) and then send **unencrypted** notifications. BikeControl does it this way.

Order used here: subscribe to ASYNC and SYNC_TX, then write `RideOn`.

## Notifications

The first byte is the message type and the rest is a protobuf message.

| Type | Message |
|---|---|
| `0x07` | `PlayKeyPadStatus` (Zwift Play firmware 1.x) |
| `0x37` | `ClickKeyPadStatus` (Zwift Click) |
| `0x23` | `RideKeyPadStatus` (Ride, Play firmware 2.x, Click v2) |
| `0x19` | battery: field 1 = percent |
| `0x15` | empty / keep-alive, sent when nothing happens |

The device sends the full state on every change and resends identical states, so `ble.py` diffs consecutive states to produce `ButtonDown` / `ButtonUp`.

```proto
enum PlayButtonStatus { ON = 0; OFF = 1; }   // active-low

message PlayKeyPadStatus {
  optional PlayButtonStatus RightPad      = 1;  // ON = right half, OFF = left half
  optional PlayButtonStatus Button_Y_Up    = 2;  // Y  | D-pad up
  optional PlayButtonStatus Button_Z_Left  = 3;  // Z  | D-pad left
  optional PlayButtonStatus Button_A_Right = 4;  // A  | D-pad right
  optional PlayButtonStatus Button_B_Down  = 5;  // B  | D-pad down
  optional PlayButtonStatus Button_On      = 6;  // power button
  optional PlayButtonStatus Button_Shift   = 7;  // orange side button
  optional sint32 Analog_LR = 8;                 // paddle, ±100 at full travel
  optional sint32 Analog_UD = 9;
}

message ClickKeyPadStatus {
  optional PlayButtonStatus Button_Plus  = 1;
  optional PlayButtonStatus Button_Minus = 2;
}

message RideKeyPadStatus {
  optional uint32 ButtonMap = 1;                 // bitmask, bit cleared = pressed
  repeated RideAnalogKeyPress AnalogPaddles = 3;
}
message RideAnalogKeyPress {
  optional RideAnalogLocation Location = 1;      // 0 = left paddle, 1 = right paddle
  optional sint32 AnalogValue = 2;               // pressed at |value| >= 25
}
```

`ButtonMap` bits: `0x1` left, `0x2` up, `0x4` right, `0x8` down, `0x10` A, `0x20` B, `0x40` Y, `0x80` Z, `0x100` shift-up L, `0x200` shift-down L, `0x400` power-up L, `0x800` on/off L, `0x1000` shift-up R, `0x2000` shift-down R, `0x4000` power-up R, `0x8000` on/off R.

## Firmware

These are the latest firmware versions BikeControl supports, so treat them as known-good:

| Device | Firmware |
|---|---|
| Zwift Play | 1.3.1 (firmware 1.x protocol), 2.0.1 (Ride protocol) |
| Zwift Click | 1.1.0 |

A Click v2 or Ride v2 on newer firmware hides the custom service until it has been unlocked in the Zwift app. BikeControl implements that unlock, but this project doesn't.

Firmware updates only come through the Zwift Companion app. Before updating, check that the controllers still connect afterwards.

## Not used (yet)

- LEDs / vibration: write `12 12 08 0A 06 08 02 10 00 18 20` to SYNC_RX to vibrate a Play.
