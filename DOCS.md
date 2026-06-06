# Installation and Setup Guide

Follow this guide to perform the one-time Android-x86 installation and set up automation triggers from Home Assistant.

---

## 🛠️ Step 1: Initial Installation (60 Seconds)

1.  Leave the Add-on config option **`installed`** set to **`false`** (default).
2.  Start the Add-on.
3.  The Add-on will automatically extract the installation files and boot headlessly into auto-installation mode. It will partition and format the virtual drive, copy files, and install the bootloader automatically.
4.  Open the Web UI. You will see a blue terminal screen showing installation status.
5.  Wait about 30–60 seconds. When you see **"Android-x86 is installed successfully"** on the screen, go back to the Home Assistant Add-on dashboard and **STOP** the Add-on.


---

## 🚀 Step 2: Switch to Running Mode

1.  In the Add-on **Configuration** tab, toggle **`installed`** to **`true`**.
2.  Click **Save**.
3.  Start the Add-on.
4.  Android-x86 will now boot directly from your virtual disk in less than 10 seconds. The installer ISO is deleted automatically to reclaim host disk space.

---

## 📥 Step 3: Installing APK Files

You can install any APK using three different methods:

### Method A: Via Android Web Browser (e.g. Chrome/WebView)
Open the browser inside Android, navigate to your favorite APK repository (e.g. APKPure, APKMirror, or official download pages), download the APK, and run it.

### Method B: Drag and Drop
Open the Add-on Web UI and **drag and drop any `.apk` file from your desktop directly into the noVNC browser window**. The file is uploaded to the Android emulator. Open a file manager inside Android, go to `Downloads`, and tap to install.

### Method C: Via Remote ADB (Command Line)
From your computer or any terminal on the same network:
```bash
adb connect <your-home-assistant-ip>:5555
adb install path_to_your_app.apk
```

---

## 🤖 Step 4: Automating Inputs from Home Assistant

To automate clicking buttons (like "Force Charge" or "Preserve" in your Amber app), you can send commands directly from Home Assistant automations.

### 1. Add the Integration
1. Go to **Settings > Devices & Services > Add Integration**.
2. Search for **Android Debug Bridge (ADB)**.
3. Configure it with:
   * **Host:** `127.0.0.1` (or `localhost`)
   * **Port:** `5555`
4. This will create a `media_player` entity (e.g., `media_player.android_x86_emulator`).

### 2. Example Automations

To execute controls, call the **`androidtv.adb_command`** service.

#### Launching an App
Specify the target package name:
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "monkey -p com.amber.app -c android.intent.category.LAUNCHER 1"
```

#### Tapping a Coordinates Button
Simulate a screen tap at a specific X/Y coordinate:
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "input tap 450 1200"
```

#### Typing a Value (e.g. Login credentials)
```yaml
service: androidtv.adb_command
target:
  entity_id: media_player.android_x86_emulator
data:
  command: "input text 'myusername@email.com'"
```
