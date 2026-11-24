# Android-x86 Home Assistant Add-on (ApkStart Engine v2.0)

A lightweight, fast Android APK runner running as a local Home Assistant Add-on. Powered by the container trimming and offline APK parsing backbone of **[RoutineMiku/apkstart](https://github.com/RoutineMiku/apkstart)**, this add-on runs a trimmed Android-x86 virtual machine inside QEMU with **Quickboot VM snapshots**, **0% CPU idle parking**, a **drag-and-drop APK installer & Single-App launcher** in the Home Assistant sidebar (via Ingress), and full automation control via **ADB (Android Debug Bridge)**.

You can drag-and-drop **any `.apk`** (such as the Amber Electric app, proprietary smart device apps, etc.) directly into the Ingress UI to install, launch, and generate ready-to-paste Home Assistant automation YAML.

---

## ⚡ Hardware & System Requirements

### 1. Host Architecture
*   **Supported:** `x86_64` (`amd64`) systems (e.g., Intel NUC, Mini PCs, standard x86 servers, Proxmox/unRAID hosts).
*   **Unsupported:** `ARM` architectures (e.g., Raspberry Pi 3/4/5, Home Assistant Green, Apple Silicon hosts).

### 2. Hypervisor / VM Configuration (Crucial for Proxmox/VM Users)
If your Home Assistant is running inside a virtual machine (like Proxmox VE, ESXi, VirtualBox, or Hyper-V):
*   **Nested Virtualization (KVM) must be enabled** for the VM.
*   **In Proxmox:** Go to your Home Assistant VM -> **Hardware** -> **Processor** -> **Edit** -> Set **Type** to `host`.
*   *Why?* With KVM active, Android runs at native CPU speed and restores Quickboot snapshots in ~3 seconds. The Ingress UI displays a live **KVM Accel: Active** badge so you can verify hardware acceleration at a glance.

### 3. Resource Allocation
*   **RAM:** Default `1536MB` (configurable from `512MB` to `8192MB`).
*   **Idle CPU:** **0.0%** when parked via the ApkStart Idle Freezer (`Park VM`), or ~1% when idling in Android Doze.
*   **Disk space:** Thin-provisioned 16GB virtual disk (`android.qcow2`). The 900MB installer ISO is automatically deleted as soon as initial setup finishes.

---

## 🚀 Key Features (ApkStart Engine v2.0)

*   **Zero-Toggle Auto-Install:** No need to manually switch `installed: false` to `true`. On first start, the add-on automatically installs Android-x86 to the virtual disk, cleans up the 900MB ISO, and boots straight into running mode.
*   **Quickboot VM Snapshots (`savevm` / `loadvm`):** Automatically saves a VM memory snapshot after the first clean boot so subsequent restarts take **~3–5 seconds** instead of a 60-second cold boot.
*   **Offline Binary APK Parser & Drag-and-Drop Installer:** Drop any `.apk` into the Ingress sidebar—the built-in `apkstart` parser extracts the binary `AndroidManifest.xml` (AXML), `resources.arsc` app label, launchable activity, and icon offline, installs via `adb install -r -g -t`, and launches your app automatically.
*   **Single-App Container Isolation & Deep Trim:** Automatically disables ~14 unnecessary Android background services (`pm disable-user`), sets UI animation scales to `0.0` for instant tap response, and runs `am force-stop` on background user apps when launching a target APK.
*   **0% CPU Idle Parking:** Puts Android into deep Doze (`dumpsys deviceidle force-idle`) and pauses QEMU vCPUs via QMP/Monitor (`stop`/`cont`), waking up in milliseconds whenever you launch an app or send an ADB command.

---

## 🛠️ File Structure

*   `repository.json`: Manifest for the Home Assistant repository.
*   `android-x86/config.json`: Home Assistant Add-on manifest defining permissions, ports, and schema.
*   `android-x86/Dockerfile`: Builds the virtualization environment (QEMU + Python 3 ApkStart Server + noVNC + ADB).
*   `android-x86/start.sh`: Handles automated installation detection, ISO cleanup, Quickboot snapshot loading/invalidation, and QEMU execution.
*   `android-x86/server.py`: Unified Websockify VNC proxy + ApkStart REST API (binary AXML/ARSC/APK parser, single-app container trimmer, and QEMU monitor controller).
*   `android-x86/index.html`: Split-pane ApkStart Control Sidebar + embedded noVNC console for Home Assistant Ingress.
