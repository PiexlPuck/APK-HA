# Installation and Setup Guide (ApkStart Engine v2.0)

Follow this guide to start the add-on, drop in your `.apk` files, and automate inputs from Home Assistant.

---

## 🛠️ Step 1: One-Click Start & Automatic Installation

1. Install and **Start** the Add-on.
2. Open the **Web UI** (Ingress).
3. On your very first start, the Web UI displays a locked **First-Time Android Setup** progress screen (hiding all controls and VNC until setup completes) while the Add-on downloads the Android-x86 image, runs the unattended disk installer (`AUTO_INSTALL=0`), deletes the 900MB installer ISO to reclaim disk space, and automatically unlocks and boots into Running Mode.
4. Once Android finishes its first boot, the **ApkStart Watchdog** automatically:
   * Disables all Android UI animations (`0.0x`) for instant tap responsiveness,
   * Deep-trims ~14 background Android system services (`pm disable-user`), and
   * Saves a **Quickboot VM Snapshot** so future restarts boot in **~3–5 seconds**.

---

## 📥 Step 2: Installing & Launching APK Files

### Method A: Drag-and-Drop in the ApkStart Sidebar (Recommended)
1. Open the Add-on Web UI in Home Assistant.
2. Drag and drop any `.apk` file onto the **"Drop APK to Install & Run"** box in the left sidebar (or click to browse).
3. The built-in `apkstart` binary manifest parser extracts the app icon, label, package name, and main launcher activity offline, installs the APK via `adb install -r -g -t`, stops any other background apps, and launches your app immediately.
4. Your app is saved in the **Installed Apps** dock for 1-click launching, stopping, or copying its Home Assistant YAML snippet.

### Method B: Via Remote ADB (Command Line)
From any computer or terminal on the same network:
```bash
adb connect <your-home-assistant-ip>:5555
adb install -r path_to_your_app.apk
```

---

## 💤 Step 3: Speed, Snapshots & 0% CPU Idle Parking

In the left sidebar under **Speed & Power Controls**:
* **💤 Park VM (0% CPU) / ⚡ Wake VM:** Clears background caches (`am kill-all`), forces Android into deep Doze (`dumpsys deviceidle force-idle`), and pauses QEMU guest vCPUs (`stop`). While parked, the add-on consumes **0.0% host CPU**. Clicking **Wake VM** or **▶ Run** on any app resumes execution in milliseconds.
* **💾 Save Quickboot / ⚡ Load Quickboot:** Saves or restores the full running VM memory state inside `android.qcow2`. Tip: Log into your app once, get to the main dashboard screen, and click **Save Quickboot** so the emulator always restores directly to your logged-in app screen!
* **✂️ Deep Trim RAM:** Re-applies the `apkstart` background package trimmer and kills cached processes on demand.

---

## 🤖 Step 4: Automating Inputs from Home Assistant

### 1. Add the Integration
1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **Android Debug Bridge (ADB)**.
3. Configure it with:
   * **Host:** `127.0.0.1` (or your Home Assistant IP)
   * **Port:** `5555`
4. This creates a `media_player` entity (e.g., `media_player.android_x86_emulator`).

### 2. Generate & Run Automations
You can test taps and text directly from the **Home Assistant ADB Helper** card in the add-on sidebar and click the generated YAML box to copy the exact `androidtv.adb_command` service call:

#### Launching an App (Direct Activity or Monkey)
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "am start -n com.amber.app/.MainActivity"
```

#### Tapping Coordinates
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "input tap 450 1200"
```

#### Typing Text
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "input text 'myusername@email.com'"
```
