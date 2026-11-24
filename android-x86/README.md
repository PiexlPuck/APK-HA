# Android-x86 Emulator (ApkStart Engine v2.0)

A lightweight, fast Android APK runner running as a local Home Assistant Add-on. Powered by the container trimming and offline APK parsing backbone of **[RoutineMiku/apkstart](https://github.com/RoutineMiku/apkstart)**, this add-on runs a trimmed Android-x86 virtual machine inside QEMU with **Quickboot VM snapshots**, **0% CPU idle parking**, a **drag-and-drop APK installer & Single-App launcher** in the Home Assistant sidebar (via Ingress), and full automation control via **ADB (Android Debug Bridge)**.

## Key Features
* **Zero-Toggle Auto-Install:** Automatically detects and completes first-time Android-x86 disk installation, removes the 900MB installer ISO, and transitions straight into Running Mode.
* **Quickboot VM Snapshots (`savevm` / `loadvm`):** Automatically saves a VM memory snapshot after the first clean boot so subsequent restarts take **~3–5 seconds**.
* **Drag-and-Drop Offline APK Parser & Installer:** Drop any `.apk` into the Ingress sidebar to parse `AndroidManifest.xml` (AXML) and `resources.arsc` offline, extract the app icon/label/launcher activity, install via `adb install -r -g -t`, and launch immediately.
* **Single-App Container Isolation & Deep Trim:** Disables ~14 unnecessary Android background services, sets UI animation scales to `0.0`, and stops background user apps when launching a target APK.
* **0% CPU Idle Parking:** Places Android in deep Doze and pauses QEMU guest vCPUs (`stop`/`cont`) when idle, waking up in milliseconds when needed.
