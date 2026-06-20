# IQ.Pilot User Changelog

This changelog is written for everyday drivers and focuses on what you will notice on the road.


##  IQ.Pilot 1.0c:


**Speed Limit Control (SLC)**

IQ.Pilot can now read and act on speed limits from your dash, Mapbox, and offline maps. You pick what mode you want in settings: display only, warn you when you're over, or actually adjust your cruise speed. You also pick which source wins when they disagree (dash, Mapbox, map data, highest, or lowest reported limit). There's a look-ahead setting so IQ.Pilot can start reacting to an upcoming speed change before you hit the sign. GPS fix is required before any speed limit data is trusted.

**IQ.Dynamic**

In IQ.Dynamic blended mode, when IQ.Pilot sees a stop light ahead, the model agrees you need to stop, and there's no lead car to track, it will now commit to stopping on its own without needing lead car confirmation. Gas pedal overrides it instantly. The stop prediction horizon is adjustable in IQ.Dynamic settings.

**Dashcam toggle**

You can now fully disable dashcam recording from settings. Turning it off stops all recording, no logs, no video, no audio.

**Konn3kt app theme syncs to your device**

Whatever accent color you pick in the Konn3kt app's appearance settings now flows to your device in real time. The IQ.Pilot UI glows match your color within a couple of seconds of changing it in the app.

**Volkswagen improvements**

- MQB standstill on non-EPB ACC FtS cars (thanks to scarycrumb!) + Volkswagen Lateral Tuning, smoother accelerator overrides, better longitudinal control logic.
- Konn3kt can now code on LKAS for VW MQB cars, including enabling, disabling, and checking status and EPS compatibility with Comma Power plugged into your IQ.Pilot devices harness.

**Tesla updates**

Tesla control got another pass of improvements, including Turn Signal support for navigation, giving the ability for Navigate on IQ.Pilot to command turn signals according to route guidance.

**More vehicle fingerprints**

Hyundai/Kia fingerprint coverage was expanded to cover more variants that were previously unrecognized.

**Toyota Stop-and-Go**

New support added for Stop and Go for Toyota/Lexus! + SDSU Support

**New driving models**

IQ.Pilot updated to a new default driving model, `Pop!`

IQ.Pilot also got updated with the latest bleeding edge models, as always, including the latest DeepRL (v3) model, and OP Model 16 Deep!

**Settings expanded**

- IQ.Dynamic settings can now be accessed on device by double tapping IQ.Dynamic in longitudinal mode selection.

**UI Improvements**

IQ.Pilot's onroad UI got a few major improvements, notable including:

- AOL Border now has a lower portion to show AOL vs full engagement state.

- IQ Long Control modes can now be cycled by clicking the IQ.Standard/Dynamic/Pilot icon in the top left corner of the on-road UI on BIG UI devices when IQ Longitudinal Control is enabled prior to going on-road.

- IQ Long Personality can be now be cycled on-road by pressing the DM icon on BIG UI devices, it cycles when IQ Longitudinal Control is enabled prior to going on-road, the color of the DM icon shows the current personality selected.

**IQ.OS v3.4 Released**
- IQ.OS v3.4 is compatible with all devices that IQ.Pilot supports, including Comma 3, 3x, 4, Konik A1/M, Mr.One C3/C3(X)L.
- IQ.OS is a lightweight OS for IQ.Pilot devices based on Ubuntu 24.04, it includes Bluetooth (BLE), is highly optimized, and is stripped down to remove unnecessary components that IQ.Pilot doesn't need.


**Groundwork for future hardware**

eSIM management is now fully built into the device settings on supported hardware. The app can detect whether your device has an embedded SIM, provision it, and manage profiles without needing a physical SIM swap. FYI: eSIM is currently extremely experimental and is not compatible with most voice plans from first-party carriers as they IMEI filter, eSIM generally requires a data plan for hotspot-like devices, or a travel sim from an MVNO that does not IMEI filter.

