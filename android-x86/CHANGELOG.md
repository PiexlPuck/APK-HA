## 2.0.1
- **Improvement (Short Sidebar Title):** Shortened the add-on name to `Android APK` and added `panel_title: "Android"` (`panel_icon: "mdi:android"`) in `config.json` so the Home Assistant sidebar label is compact and clean.
- **Feature (First-Time Installation Lock Screen):** Locked and hid the entire control workspace and VNC console behind a full-screen installation progress overlay during first-time setup (`downloading`, `extracting`, `installing`). The UI automatically unlocks and connects noVNC only after installation completes.

## 2.0.0
- **Feature (ApkStart Engine):** Integrated the core container trimming and APK parsing engine from `RoutineMiku/apkstart`.
- **Feature (Offline Binary APK Parser & Drag-and-Drop Installer):** Added a unified Python 3 + Websockify Ingress control server (`server.py`) that parses binary `AndroidManifest.xml` (AXML) and `resources.arsc` offline, extracts app icons/labels/launch activities, installs `.apk` files via `adb install -r -g -t`, and launches them automatically.
- **Feature (Single-App Container & Deep System Trim):** Automatically disables dead-weight Android background packages (`pm disable-user`), zeroes out UI animation latency (`window_animation_scale 0`), and stops background user apps (`am force-stop` + `am kill-all`) when launching an app.
- **Feature (Quickboot VM Snapshots):** Automatically saves a QEMU `quickboot` VM snapshot after first boot so subsequent add-on restarts restore into a ready state in ~3–5 seconds (with automatic invalidation when RAM/CPU config changes).
- **Feature (0% CPU Idle Parking):** Added automatic and manual VM parking (`dumpsys deviceidle force-idle` + QEMU monitor `stop`/`cont`) to drop idle host CPU usage to 0%.
- **Feature (Zero-Toggle Auto-Install):** Replaced the manual 2-step `installed: false -> true` toggle with automatic disk installation detection and live transition into Running Mode.
- **Optimization:** Removed unused `x11vnc`, `xvfb`, and `curl` packages from `Dockerfile` and lowered default RAM allocation to `1536` MB.

## 1.3.4
- **Fix:** Reverted CPU emulation model in software mode back to `max`. This ensures Android-x86 has access to modern SSE4.1/SSE4.2 instruction sets required to boot the guest kernel, resolving the black screen hang.

## 1.3.3
- **Feature:** Direct persistent kernel booting for both install and run phases. Extracted boot files are stored in `/data/` to keep kernel arguments configurable from the start script.
- **Fix:** Switched RUNNING mode graphics to use `nomodeset xforcevesa` compat flags, resolving the graphical freeze on the "android" logo screen (especially under software-only emulation).
- **Optimization:** Switched emulator CPU model to `qemu64` in software mode to optimize translation speed when KVM is unavailable.

## 1.3.2
- **Fix:** Attached the installation ISO as a CD-ROM device during direct kernel booting so the automated installer can locate and copy the system files, resolving the hang on "Detecting Android-x86...".

## 1.3.1
- **Fix:** Fixed a shell word-splitting bug where QEMU parsed kernel parameters as separate files, causing the emulator to fail to start.

## 1.3.0
- **Feature:** Automated installation mode. The add-on now automatically extracts the boot kernel and runs a headless installation script (`AUTO_INSTALL=0`), completely bypassing manual partitioning and wizard setups.

## 1.2.0
- **Fix:** Changed QEMU display driver from `virtio` to `std` (`-vga std`) to resolve startup crash on systems where VirtIO VGA is not compiled into QEMU.

## 1.1.0
- **Fix:** Removed the deprecated `-soundhw ac97` flag that caused newer QEMU versions to crash on startup.
- **Improvement:** Refactored files into the `android-x86/` subdirectory for proper Home Assistant Supervisor repository compliance.

## 1.0.0
- **Feature:** Initial release containing a headless QEMU container running Android-x86.
- **Feature:** Added dynamic Ingress WebSocket route resolution to embed noVNC directly in the Home Assistant sidebar.
- **Feature:** Exposed port `5555` for native remote ADB script automation.
