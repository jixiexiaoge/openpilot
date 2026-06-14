# IQ.Pilot User Changelog

This changelog is written for everyday drivers and focuses on what you will notice on the road.

## February 9, 2026 - IQ.Pilot Launch
- IQ.Pilot v1.0a launched.
- You got first-release IQ.Pilot + Konn3kt integration.
- The UI was rebranded and cleaned up for a more consistent look.
- Unused legacy UI/debug elements were removed.
- Early setup and reliability issues were fixed (better error handling and cleaner setup flow).

## February 10, 2026 - Device Support and Stability
- Better mici and tizi device support.
- You can now use manual QR registration.
- Volkswagen PQ support was enabled and expanded.
- A major bugfix pass improved stability and controls behavior.
- Cruise/button behavior was refined for more consistent response.

## February 11, 2026 - Major Vehicle Expansion
- Tesla control support was expanded.
- Honda MVL tuning (lateral + longitudinal) was added.
- Volkswagen support grew across PQ and MLB with multiple fixes.
- PQ bring-up continued, including Passat NMS-focused improvements.
- More runtime fixes landed (including joystick and icon issues).

## February 12, 2026 - Sensor/Data Fixes
- Steering-angle offset tolerance was increased, helping with temporary steering sensor misalignment.
- Fuel level handling was fixed and improved.
- Additional Volkswagen PQ follow-up fixes were added.

## February 13, 2026 - Driver Monitoring Rollback
- Driver Monitoring was rolled back to previous behavior to reduce over aggressive alerts from a regression caused by a new comma DM model.

## February 15-16, 2026 - Volkswagen PQ Maturity
- Volkswagen PQ received heavy control tuning and bugfixes.
- You should see more consistent engagement and smoother overall behavior.
- Lateral/longitudinal interaction and cruise response were improved.

## February 17, 2026 - Volkswagen Stopping Behavior Tuning
- Volkswagen stopping and braking behavior received additional tuning.
- Comfort and stop-response were further refined for real-world driving.

## February 27, 2026 - Major Refactor
- IQ.Pilot completed a major refactor and is now independent of any other fork.
- Driving logic cleanup removed legacy compatibility paths that could cause inconsistent behavior between vehicles and branches.
- New (way better) Always On Lateral logic!
- Better longitudinal controls for clearer choices for everyday use: `IQ.Pilot`, `IQ.Dynamic`, `IQ.Standard`, and your vehicles `Stock ACC`.
- Device/System controls were reworked for better offroad management, including a timed Force On-Road workflow for diagnostics/testing.
- Volkswagen MEB/MQBEvo platform support!
- Offroad UI and settings UI rework!

## March 16th - IQ.Pilot 1.0c Pre-Release
- IQ.Pilot has continued refactoring componenets to be more efficient, and better written, with better logic.
- Navigation, with On-Screen maps, online routing, fully offline routing

## April 21, 2026 - IQ.Pilot 1.0c


**Speed Limit Control (SLC)**

IQ.Pilot can now read and act on speed limits from your dash, Mapbox, and offline maps. You pick what mode you want in settings: display only, warn you when you're over, or actually adjust your cruise speed. You also pick which source wins when they disagree (dash, Mapbox, map data, highest, or lowest reported limit). There's a look-ahead setting so IQ.Pilot can start reacting to an upcoming speed change before you hit the sign. GPS fix is required before any speed limit data is trusted.

**IQ.Dynamic Force Stop**

In IQ.Dynamic blended mode, when IQ.Pilot sees a stop light ahead, the model agrees you need to stop, and there's no lead car to track, it will now commit to stopping on its own without needing lead car confirmation. Gas pedal overrides it instantly. The stop prediction horizon is adjustable in IQ.Dynamic settings.

**Dashcam toggle**

You can now fully disable dashcam recording from settings. Turning it off stops all recording, no logs, no video, no audio. Default is on.

**Konn3kt app theme syncs to your device**

Whatever accent color you pick in the Konn3kt app's appearance settings now flows to your device in real time. The IQ.Pilot UI glows match your color within a couple of seconds of changing it in the app.

**Volkswagen improvements**

- MQBevo (Golf 8, etc.) now has IQ.Pilot Longitudinal, not just lateral
- MQB got standstill! + VW Tuning, smoother accelerator overrides, less phantom cruise faults, better overall longitudinal control logic.
- Konn3kt can now code LKAS, including enabling, disabling, and checking status and EPS compatibility with Comma Power plugged into your IQ.Pilot devices hardware relay!

**Tesla updates**

Tesla control got another pass of improvements (lateral and longitudinal behavior), including updates to support the new Tesla fingerprint in the latest Tesla software update.

**More vehicle fingerprints**

Hyundai/Kia fingerprint coverage was expanded to cover more variants that were previously unrecognized.

**Toyota Stop-and-Go**

New support added for Stop and Go for Toyota/Lexus!

**New driving model**

IQ.Pilot updated to a new driving model `Pop!`, as always we support all models ASAP to be on the bleeding edge in our pre-release branches.

**Settings expanded**

- IQ.Dynamic got its own dedicated settings page with controls for stop prediction horizon and force stop tuning
- Cruise settings gained speed limit mode, SLC source priority, speed limit look-ahead, lane turn desire speed threshold, and steer actuator delay adjustment
- Steer delay settings now show the value formatted in seconds

**Laying groundwork for future hardware**

eSIM management is now fully built into the device settings on supported hardware. The app can detect whether your device has an embedded SIM, provision it, and manage profiles without needing a physical SIM swap.

