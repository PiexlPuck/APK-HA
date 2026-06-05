# Android-x86 Home Assistant Add-on

A lightweight, universal Android environment running as a local Home Assistant Add-on. This add-on runs an Android-x86 virtual machine inside a headless QEMU container, exposing a graphical interface directly in the Home Assistant sidebar using **noVNC** (via Ingress) and allowing full automation control via **ADB (Android Debug Bridge)**.

You can upload and run **any APK** (such as the Amber Electric app, proprietary smart device apps, etc.) and automate inputs remotely from your Home Assistant scripts.

---

## ⚡ Hardware & System Requirements

Running a virtualized Android environment requires specific hardware capabilities. Please verify your system setup before installing.

### 1. Host Architecture
*   **Supported:** `x86_64` (`amd64`) systems (e.g., Intel NUC, Mini PCs, standard x86 servers, Proxmox/unRAID hosts).
*   **Unsupported:** `ARM` architectures (e.g., Raspberry Pi 3/4/5, Home Assistant Green, Apple Silicon hosts). Running this on ARM requires full CPU instruction emulation, which will overload the host and run too slowly to be usable.

### 2. Hypervisor / VM Configuration (Crucial for Proxmox/VM Users)
If your Home Assistant is running inside a virtual machine (like Proxmox VE, ESXi, VirtualBox, or Hyper-V):
*   **Nested Virtualization (KVM) must be enabled** for the VM.
*   **In Proxmox:** Go to your Home Assistant VM -> **Hardware** -> **Processor** -> **Edit** -> Set **Type** to `host`.
*   *Why?* Without nested virtualization, QEMU will fall back to software emulation, causing Android to boot extremely slowly and consume 100% of your host CPU.

### 3. Resource Allocation
*   **RAM:** Minimum 512MB, recommended 1GB–2GB allocated to the Android VM.
*   **Disk space:** The add-on itself is tiny (~300MB), but the virtual disk (`android.qcow2`) will allocate up to 16GB (thin-provisioned, meaning it only uses space as you install apps).

---

## 🚀 Key Features

*   **Universal Compatibility:** Runs any standard Android-x86 compatible `.apk` file.
*   **Zero-Google Footprint:** De-Googled (no Google Play Services) to keep memory usage under 512MB and idle CPU usage at ~0%.
*   **Home Assistant Ingress:** Native web screen integration directly inside the Home Assistant UI. No external VNC clients needed.
*   **ADB Bridge:** Standard ADB port `5555` exposed to Home Assistant, allowing automation scripts to tap buttons, read screens, and launch apps.

---

## 🛠️ File Structure

*   `repository.json`: Manifest for the Home Assistant repository.
*   `android-x86/config.json`: Home Assistant Add-on manifest defining permissions, ports, and schema.
*   `android-x86/Dockerfile`: Builds the virtualization environment (QEMU + VNC + WebSockets + ADB).
*   `android-x86/start.sh`: Handles automated virtual disk creation, ISO downloading, and booting.
*   `android-x86/index.html`: Web redirector for noVNC Ingress WebSocket routing.
*   `.gitignore`: Prevents temporary virtual disks (`.qcow2`), ISOs, and the local `brainstorm/` folder from being pushed to Git.
*   `brainstorm/deep_dive.md`: A detailed technical breakdown of the architecture, graphics piping, and automation methods.
