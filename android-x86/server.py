#!/usr/bin/env python3
"""
ApkStart Engine Control Server & Websockify Proxy for Home Assistant Ingress.

Ports core capabilities from RoutineMiku/apkstart to Python 3 (zero external deps):
  1. Offline binary APK parser (zip.js + axml.js + arsc.js + apk.js):
     Extracts package name, localized label, version, launchable activity, ABIs,
     screen orientation, and app icon PNG directly from .apk files without aapt2.
  2. Single-App Container & Deep Trimmer (container.js):
     Disables dead-weight Android background packages, enforces single-app foreground
     execution (am force-stop on background user apps + am kill-all), and zeroes out
     UI animation scales for instant responsiveness.
  3. Quickboot VM Snapshot & 0% CPU Idle Parking:
     Communicates with QEMU's Unix monitor socket to save/restore VM snapshots
     (savevm/loadvm quickboot) and pause/resume guest vCPUs (stop/cont) when idle.
"""

import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http import HTTPStatus

# ==============================================================================
# 1. Port of apkstart/src/core/axml.js & arsc.js & apk.js (Binary APK Parser)
# ==============================================================================

RES_STRING_POOL_TYPE = 0x0001
RES_TABLE_TYPE = 0x0002
RES_XML_TYPE = 0x0003
RES_XML_START_NAMESPACE = 0x0100
RES_XML_END_NAMESPACE = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_TABLE_PACKAGE_TYPE = 0x0200
RES_TABLE_TYPE_TYPE = 0x0201

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

ANDROID_NS = "http://schemas.android.com/apk/res/android"
SAFE_PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

ORI_PORTRAIT = {1, 5, 7, 13}
ORI_LANDSCAPE = {2, 4, 6, 12}


def _u8(buf, off):
    return buf[off]


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


def read_string_pool(buf, start):
    header_size = _u16(buf, start + 2)
    chunk_size = _u32(buf, start + 4)
    count = _u32(buf, start + 8)
    flags = _u32(buf, start + 16)
    strings_start = _u32(buf, start + 20)
    is_utf8 = (flags & 0x100) != 0

    base = start + strings_start
    strings = []
    for i in range(count):
        off_pos = start + header_size + i * 4
        if off_pos + 4 > len(buf):
            strings.append("")
            continue
        p = base + _u32(buf, off_pos)
        if p >= len(buf):
            strings.append("")
            continue
        try:
            if is_utf8:
                u16_len = buf[p]
                p += 1
                if u16_len & 0x80:
                    u16_len = ((u16_len & 0x7F) << 8) | buf[p]
                    p += 1
                byte_len = buf[p]
                p += 1
                if byte_len & 0x80:
                    byte_len = ((byte_len & 0x7F) << 8) | buf[p]
                    p += 1
                strings.append(buf[p : p + byte_len].decode("utf-8", errors="replace"))
            else:
                u16_len = _u16(buf, p)
                p += 2
                if u16_len & 0x8000:
                    u16_len = ((u16_len & 0x7FFF) << 16) | _u16(buf, p)
                    p += 2
                strings.append(buf[p : p + u16_len * 2].decode("utf-16le", errors="replace"))
        except Exception:
            strings.append("")
    return strings, chunk_size


def parse_axml(buf):
    if len(buf) < 8 or _u16(buf, 0) != RES_XML_TYPE:
        raise ValueError("Not a valid Android binary XML (AXML)")
    pos = _u16(buf, 2)
    total = min(len(buf), _u32(buf, 4))

    pool = []
    root = {"name": "#document", "attrs": [], "children": []}
    stack = [root]

    while pos + 8 <= total:
        ctype = _u16(buf, pos)
        chunk_size = _u32(buf, pos + 4)
        if chunk_size <= 0:
            break

        if ctype == RES_STRING_POOL_TYPE:
            pool, _ = read_string_pool(buf, pos)
        elif ctype == RES_XML_START_ELEMENT:
            name_idx = _u32(buf, pos + 20)
            attr_start = _u16(buf, pos + 24)
            attr_size = _u16(buf, pos + 26)
            attr_count = _u16(buf, pos + 28)

            el_name = pool[name_idx] if name_idx < len(pool) else ""
            node = {"name": el_name, "attrs": [], "children": []}
            attr_base = pos + 16 + attr_start

            for i in range(attr_count):
                a = attr_base + i * attr_size
                if a + 20 > len(buf):
                    break
                ns_idx = _u32(buf, a)
                a_name_idx = _u32(buf, a + 4)
                raw_idx = _u32(buf, a + 8)
                data_type = _u8(buf, a + 15)
                data = _u32(buf, a + 16)

                ns = "" if ns_idx == 0xFFFFFFFF or ns_idx >= len(pool) else pool[ns_idx]
                aname = pool[a_name_idx] if a_name_idx < len(pool) else ""
                val = None
                ref_id = None

                if raw_idx != 0xFFFFFFFF and raw_idx < len(pool):
                    val = pool[raw_idx]
                elif data_type == TYPE_STRING and data < len(pool):
                    val = pool[data]
                elif data_type == TYPE_REFERENCE:
                    ref_id = data
                elif data_type == TYPE_INT_BOOLEAN:
                    val = data != 0
                elif data_type in (TYPE_INT_DEC, TYPE_INT_HEX):
                    val = _i32(buf, a + 16)

                node["attrs"].append({
                    "ns": ns,
                    "name": aname,
                    "value": val,
                    "refId": ref_id,
                    "dataType": data_type,
                    "typed": None if data_type == TYPE_REFERENCE else val,
                })

            stack[-1]["children"].append(node)
            stack.append(node)
        elif ctype == RES_XML_END_ELEMENT:
            if len(stack) > 1:
                stack.pop()

        pos += chunk_size

    for child in root["children"]:
        if child["name"] == "manifest":
            return child
    if root["children"]:
        return root["children"][0]
    raise ValueError("Empty AndroidManifest.xml")


def get_attr(node, name, ns=ANDROID_NS):
    if not node:
        return None
    for a in node.get("attrs", []):
        if a["name"] == name and (ns is None or a["ns"] == ns):
            return a
    return None


def get_attr_value(node, name, ns=ANDROID_NS):
    a = get_attr(node, name, ns)
    return a["typed"] if a else None


def get_children(node, name):
    if not node:
        return []
    return [c for c in node.get("children", []) if c["name"] == name]


class ResTable:
    """Port of apkstart/src/core/arsc.js to resolve @0x7f... labels & icon paths."""

    def __init__(self, buf):
        self.buf = buf
        self.global_strings = []
        self.packages = []
        self._parse()

    def _parse(self):
        buf = self.buf
        if len(buf) < 12 or _u16(buf, 0) != RES_TABLE_TYPE:
            return
        header_size = _u16(buf, 2)
        total = min(len(buf), _u32(buf, 4))
        pos = header_size
        while pos + 8 <= total:
            ctype = _u16(buf, pos)
            chunk_size = _u32(buf, pos + 4)
            if chunk_size <= 0:
                break
            if ctype == RES_STRING_POOL_TYPE and not self.global_strings:
                self.global_strings, _ = read_string_pool(buf, pos)
            elif ctype == RES_TABLE_PACKAGE_TYPE:
                pkg = self._parse_package(pos, chunk_size)
                if pkg:
                    self.packages.append(pkg)
            pos += chunk_size

    def _parse_package(self, start, size):
        buf = self.buf
        if start + 280 > len(buf):
            return None
        pkg_id = _u32(buf, start + 8)
        header_size = _u16(buf, start + 2)
        types = {}
        pos = start + header_size
        end = min(len(buf), start + size)
        while pos + 8 <= end:
            ctype = _u16(buf, pos)
            chunk_size = _u32(buf, pos + 4)
            if chunk_size <= 0:
                break
            if ctype == RES_TABLE_TYPE_TYPE:
                t = self._parse_type(pos)
                if t:
                    types.setdefault(t["id"], []).append(t)
            pos += chunk_size
        return {"id": pkg_id, "types": types}

    def _parse_type(self, start):
        buf = self.buf
        if start + 24 > len(buf):
            return None
        header_size = _u16(buf, start + 2)
        tid = _u8(buf, start + 8)
        flags = _u8(buf, start + 9)
        entry_count = _u32(buf, start + 12)
        entries_start = _u32(buf, start + 16)

        cfg_size = _u32(buf, start + 20)
        lang = ""
        density = 0
        if cfg_size >= 16 and start + 36 <= len(buf):
            lang = buf[start + 28 : start + 30].decode("latin1", errors="ignore").strip("\x00").strip()
            density = _u16(buf, start + 34)

        entries = {}
        offsets_base = start + header_size
        entries_base = start + entries_start

        if flags & 0x01:  # FLAG_SPARSE
            for i in range(entry_count):
                if offsets_base + i * 4 + 4 > len(buf):
                    break
                idx = _u16(buf, offsets_base + i * 4)
                off = _u16(buf, offsets_base + i * 4 + 2) * 4
                v = self._read_value(entries_base + off)
                if v:
                    entries[idx] = v
        elif flags & 0x02:  # FLAG_OFFSET16
            for i in range(entry_count):
                if offsets_base + i * 2 + 2 > len(buf):
                    break
                off = _u16(buf, offsets_base + i * 2)
                if off == 0xFFFF:
                    continue
                v = self._read_value(entries_base + off * 4)
                if v:
                    entries[i] = v
        else:
            for i in range(entry_count):
                if offsets_base + i * 4 + 4 > len(buf):
                    break
                off = _u32(buf, offsets_base + i * 4)
                if off == 0xFFFFFFFF:
                    continue
                v = self._read_value(entries_base + off)
                if v:
                    entries[i] = v

        return {"id": tid, "lang": lang, "density": density, "entries": entries}

    def _read_value(self, at):
        buf = self.buf
        if at + 16 > len(buf):
            return None
        entry_size = _u16(buf, at)
        flags = _u16(buf, at + 2)
        if flags & 0x0001:
            return None
        val_at = at + entry_size
        if val_at + 8 > len(buf):
            return None
        return {"dataType": _u8(buf, val_at + 3), "data": _u32(buf, val_at + 4)}

    def resolve(self, ref, prefer="any", depth=0):
        if depth > 6 or not ref or not self.packages:
            return None
        pkg_id = (ref >> 24) & 0xFF
        type_id = (ref >> 16) & 0xFF
        entry_idx = ref & 0xFFFF

        pkg = next((p for p in self.packages if p["id"] == pkg_id), self.packages[0])
        chunks = pkg["types"].get(type_id)
        if not chunks:
            return None

        best = None
        best_score = -1e9
        for c in chunks:
            if entry_idx not in c["entries"]:
                continue
            s = 0
            if prefer == "file":
                s += c["density"]
                if c["density"] == 0xFFFE:
                    s -= 500
            else:
                s -= 0 if c["density"] == 0 else 10
                if c["lang"]:
                    s -= 40
            if s > best_score:
                best_score = s
                best = c["entries"][entry_idx]

        if not best:
            return None
        if best["dataType"] == TYPE_STRING:
            idx = best["data"]
            return self.global_strings[idx] if idx < len(self.global_strings) else None
        if best["dataType"] == TYPE_REFERENCE:
            return self.resolve(best["data"], prefer, depth + 1)
        return None


def _is_launcher_activity(node):
    for f in get_children(node, "intent-filter"):
        actions = [get_attr_value(a, "name") for a in get_children(f, "action")]
        cats = [get_attr_value(c, "name") for c in get_children(f, "category")]
        if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in cats:
            return True
    return False


def _pick_icon_from_zip(zf):
    candidates = []
    for info in zf.infolist():
        n = info.filename
        if re.match(r"^res/.*\.(png|webp|jpe?g)$", n, re.IGNORECASE):
            score = float(info.file_size)
            if re.search(r"ic_launcher|app_icon|ic_app", n, re.IGNORECASE):
                score *= 6.0
            if re.search(r"_round|_foreground|_background", n, re.IGNORECASE):
                score *= 0.4
            if "xxxhdpi" in n:
                score *= 1.6
            elif "xxhdpi" in n:
                score *= 1.4
            elif "xhdpi" in n:
                score *= 1.2
            candidates.append((score, n))
    candidates.sort(reverse=True)
    for _, name in candidates[:15]:
        try:
            data = zf.read(name)
            if len(data) > 100:
                return data
        except Exception:
            pass
    return None


def parse_apk(file_path):
    """Offline APK parser ported from apkstart/src/core/apk.js."""
    size_bytes = os.path.getsize(file_path)
    if size_bytes < 1024:
        raise ValueError("File is too small to be a valid APK")

    with zipfile.ZipFile(file_path, "r") as zf:
        names = set(zf.namelist())
        if "AndroidManifest.xml" not in names:
            raise ValueError("Missing AndroidManifest.xml (not a standard single APK)")

        manifest = parse_axml(zf.read("AndroidManifest.xml"))
        pkg_name = get_attr_value(manifest, "package", None)
        if not pkg_name or not SAFE_PKG_RE.match(str(pkg_name)):
            raise ValueError(f"Invalid or missing package name in APK manifest: {pkg_name!r}")

        version_name = str(get_attr_value(manifest, "versionName") or "1.0")
        version_code_raw = get_attr_value(manifest, "versionCode")
        version_code = int(version_code_raw) if isinstance(version_code_raw, int) else 0

        uses_sdk = (get_children(manifest, "uses-sdk") or [None])[0]
        min_sdk = int(get_attr_value(uses_sdk, "minSdkVersion") or 0) if uses_sdk else 0
        target_sdk = int(get_attr_value(uses_sdk, "targetSdkVersion") or 0) if uses_sdk else 0

        app = (get_children(manifest, "application") or [{"children": [], "attrs": []}])[0]

        res = None
        if "resources.arsc" in names:
            try:
                res = ResTable(zf.read("resources.arsc"))
            except Exception:
                res = None

        # Resolve App Label
        label = None
        label_attr = get_attr(app, "label")
        if label_attr:
            if label_attr["refId"] and res:
                label = res.resolve(label_attr["refId"], "string")
            elif isinstance(label_attr["typed"], str):
                label = label_attr["typed"]
        if not label or not isinstance(label, str):
            tail = pkg_name.split(".")[-1]
            label = tail.capitalize()

        # Resolve Launchable Activity
        launch_activity = None
        acts = get_children(app, "activity") + get_children(app, "activity-alias")
        launcher = next((a for a in acts if _is_launcher_activity(a)), None)
        if launcher:
            n = get_attr_value(launcher, "name")
            target = get_attr_value(launcher, "targetActivity")
            if n:
                if n.startswith("."):
                    launch_activity = pkg_name + n
                elif "." not in n:
                    launch_activity = f"{pkg_name}.{n}"
                else:
                    launch_activity = n
                if launcher["name"] == "activity-alias" and target:
                    launch_activity = (pkg_name + target) if target.startswith(".") else target

        # Detect Screen Orientation
        portrait = 0
        landscape = 0
        for a in acts:
            raw = get_attr_value(a, "screenOrientation")
            if isinstance(raw, int):
                w = 4 if a is launcher else 1
                if raw in ORI_PORTRAIT:
                    portrait += w
                elif raw in ORI_LANDSCAPE:
                    landscape += w
        orientation = None
        if portrait > landscape:
            orientation = "portrait"
        elif landscape > portrait:
            orientation = "landscape"

        # Resolve App Icon
        icon_bytes = None
        icon_attr = get_attr(app, "icon") or get_attr(app, "roundIcon")
        if icon_attr:
            icon_file = None
            if icon_attr["refId"] and res:
                icon_file = res.resolve(icon_attr["refId"], "file")
            elif isinstance(icon_attr["typed"], str):
                icon_file = icon_attr["typed"]
            if icon_file and icon_file in names and not icon_file.lower().endswith(".xml"):
                try:
                    icon_bytes = zf.read(icon_file)
                except Exception:
                    icon_bytes = None
        if not icon_bytes:
            icon_bytes = _pick_icon_from_zip(zf)

        icon_data_url = None
        if icon_bytes:
            b64 = base64.b64encode(icon_bytes).decode("ascii")
            icon_data_url = f"data:image/png;base64,{b64}"

        # Detect Native ABIs
        abis = sorted({
            parts[1]
            for name in names
            if name.startswith("lib/") and len(parts := name.split("/")) >= 3 and parts[1]
        })

        return {
            "ok": True,
            "sizeBytes": size_bytes,
            "package": pkg_name,
            "label": re.sub(r"\s+", " ", label).strip()[:60],
            "versionName": version_name,
            "versionCode": version_code,
            "minSdk": min_sdk,
            "targetSdk": target_sdk,
            "launchActivity": launch_activity,
            "abis": abis,
            "orientation": orientation,
            "icon": icon_data_url,
        }


# ==============================================================================
# 2. Port of apkstart/src/core/container.js (Single-App Container & Deep Trim)
# ==============================================================================

NEVER_TRIM = {
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.inputmethod.latin",
    "com.google.android.inputmethod.latin",
    "com.android.webview",
    "com.google.android.webview",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.android.providers.settings",
    "com.android.server.telecom",
    "com.android.launcher3",
}

OPTIONAL_SYSTEM = [
    "com.android.vending",
    "com.google.android.setupwizard",
    "com.android.printspooler",
    "com.android.wallpapercropper",
    "com.android.dreams.basic",
    "com.android.providers.calendar",
    "com.android.providers.contacts",
    "com.android.managedprovisioning",
    "com.android.statementservice",
    "com.android.backupconfirm",
    "com.android.email",
    "com.android.exchange",
    "com.android.music",
    "com.android.gallery3d",
]

SYSTEM_PREFIXES = (
    "android",
    "com.android.",
    "com.google.android.",
    "com.qualcomm.",
    "com.qti.",
    "vendor.",
    "com.mediatek.",
    "org.lineageos.",
    "org.android_x86.",
)


def is_system_package(pkg):
    p = str(pkg or "").strip()
    if not p or not SAFE_PKG_RE.match(p):
        return True
    return any(p == pre or p.startswith(pre) for pre in SYSTEM_PREFIXES)


def build_session_commands(target_pkg, installed_pkgs, deep_trim=False, kill_background=True):
    """Port of apkstart container.js buildSessionCommands."""
    target = target_pkg.strip() if SAFE_PKG_RE.match(str(target_pkg or "").strip()) else ""
    commands = []
    stopped = []

    for raw in installed_pkgs:
        p = str(raw or "").strip()
        if not p or p == target or is_system_package(p) or p in NEVER_TRIM:
            continue
        stopped.append(p)
        commands.append(f"am force-stop {p}")

    if kill_background:
        commands.append("am kill-all 2>/dev/null || true")

    if deep_trim:
        for p in OPTIONAL_SYSTEM:
            if p not in NEVER_TRIM:
                commands.append(f"pm disable-user --user 0 {p} 2>/dev/null || true")
        commands.append("settings put global restricted_background_data 1 2>/dev/null || true")

    return {"commands": commands, "stopped": stopped}


def build_idle_commands(deep_trim=True):
    """Port of apkstart container.js buildIdleCommands."""
    cmds = [
        "am kill-all 2>/dev/null || true",
        "dumpsys deviceidle force-idle 2>/dev/null || true",
    ]
    if deep_trim:
        cmds.append("settings put global restricted_background_data 1 2>/dev/null || true")
    return cmds


# ==============================================================================
# 3. Runtime Orchestrator (ADB + QEMU Monitor + Persistent App Store)
# ==============================================================================

DATA_DIR = os.environ.get("APKSTART_DATA_DIR", "/data")
APPS_FILE = os.path.join(DATA_DIR, "apps.json")
STATE_FILE = os.path.join(DATA_DIR, "runtime_state.json")
INSTALLED_MARKER = os.path.join(DATA_DIR, ".installed")
QUICKBOOT_META = os.path.join(DATA_DIR, ".quickboot_meta")
DISK_PATH = os.path.join(DATA_DIR, "android.qcow2")
MON_SOCK = os.path.join(DATA_DIR, "monitor.sock")
ADB_TARGET = "127.0.0.1:5555"


class RuntimeManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.adb_connected = False
        self.boot_completed = False
        self.trimmed_once = False
        self.parked = False
        self.foreground_pkg = None
        self.last_activity = time.time()
        self.apps = self._load_apps()

        self.memory = int(os.environ.get("APKSTART_MEMORY", "1536"))
        self.cores = int(os.environ.get("APKSTART_CORES", "2"))
        self.quickboot = os.environ.get("APKSTART_QUICKBOOT", "true").lower() == "true"
        self.deep_trim = os.environ.get("APKSTART_DEEP_TRIM", "true").lower() == "true"
        self.idle_park_minutes = int(os.environ.get("APKSTART_IDLE_PARK_MINUTES", "10"))
        self.kvm = os.path.exists("/dev/kvm") and os.access("/dev/kvm", os.W_OK)

    def _load_apps(self):
        if os.path.exists(APPS_FILE):
            try:
                with open(APPS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {}

    def _save_apps(self):
        tmp = APPS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.apps, f, indent=2)
            os.replace(tmp, APPS_FILE)
        except Exception:
            pass

    def touch_activity(self):
        self.last_activity = time.time()

    def qemu_monitor_cmd(self, cmd, timeout=15.0):
        """Send a human monitor command (HMP) to QEMU over /data/monitor.sock."""
        if not os.path.exists(MON_SOCK):
            return False, "QEMU monitor socket not ready"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(MON_SOCK)
                time.sleep(0.05)
                try:
                    s.recv(4096)
                except Exception:
                    pass
                s.sendall((cmd.strip() + "\n").encode("utf-8"))
                time.sleep(0.25)
                out = b""
                s.settimeout(1.0)
                while True:
                    try:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        out += chunk
                        if b"(qemu)" in out:
                            break
                    except socket.timeout:
                        break
                return True, out.decode("utf-8", errors="replace")
        except Exception as e:
            return False, str(e)

    def run_adb(self, args, timeout=30):
        cmd = ["adb", "-s", ADB_TARGET] + list(args)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode == 0, (res.stdout + "\n" + res.stderr).strip()
        except Exception as e:
            return False, str(e)

    def run_adb_shell(self, shell_cmd, timeout=20):
        return self.run_adb(["shell", shell_cmd], timeout=timeout)

    def ensure_awake(self):
        self.touch_activity()
        if self.parked:
            self.qemu_monitor_cmd("cont")
            self.parked = False
            self.run_adb_shell(
                "dumpsys deviceidle unforce 2>/dev/null || true; input keyevent 224",
                timeout=8,
            )

    def park_vm(self, freeze_cpu=True):
        """Park Android in deep Doze and optionally pause QEMU vCPUs for 0.0% host CPU."""
        for cmd in build_idle_commands(self.deep_trim):
            self.run_adb_shell(cmd, timeout=8)
        if freeze_cpu:
            ok, msg = self.qemu_monitor_cmd("stop")
            if ok:
                self.parked = True
                return True, "Android placed in Doze & QEMU vCPUs paused (0% CPU)"
            return False, f"Doze applied, but QEMU pause failed: {msg}"
        return True, "Android background processes cleared and placed in Doze mode"

    def wake_vm(self):
        self.touch_activity()
        ok, msg = self.qemu_monitor_cmd("cont")
        self.parked = False
        self.run_adb_shell(
            "dumpsys deviceidle unforce 2>/dev/null || true; input keyevent 224; wm dismiss-keyguard 2>/dev/null || true",
            timeout=8,
        )
        return ok, "VM resumed and Android woken up"

    def apply_apkstart_optimizations(self):
        """Disable animations, prevent lockscreen sleep, and run ApkStart deep trim."""
        cmds = [
            "settings put global window_animation_scale 0.0",
            "settings put global transition_animation_scale 0.0",
            "settings put global animator_duration_scale 0.0",
            "settings put global stay_on_while_plugged_in 7",
            "settings put system screen_off_timeout 2147483647",
            "wm dismiss-keyguard 2>/dev/null || true",
        ]
        if self.deep_trim:
            for p in OPTIONAL_SYSTEM:
                if p not in NEVER_TRIM:
                    cmds.append(f"pm disable-user --user 0 {p} 2>/dev/null || true")
            cmds.append("settings put global restricted_background_data 1 2>/dev/null || true")
        cmds.append("am kill-all 2>/dev/null || true")
        joined = "; ".join(cmds)
        return self.run_adb_shell(joined, timeout=25)

    def sync_installed_packages(self):
        ok, out = self.run_adb_shell("pm list packages -3", timeout=10)
        if not ok:
            return
        changed = False
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line.split("package:", 1)[1].strip()
                if SAFE_PKG_RE.match(pkg) and pkg not in self.apps:
                    tail = pkg.split(".")[-1].capitalize()
                    self.apps[pkg] = {
                        "package": pkg,
                        "label": tail,
                        "versionName": "Installed",
                        "launchActivity": None,
                        "abis": [],
                        "icon": None,
                        "installedAt": int(time.time()),
                    }
                    changed = True
        if changed:
            self._save_apps()

    def has_quickboot_snapshot(self):
        if not os.path.exists(DISK_PATH):
            return False
        try:
            res = subprocess.run(
                ["qemu-img", "snapshot", "-l", DISK_PATH],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "quickboot" in res.stdout
        except Exception:
            return False

    def manage_snapshot(self, action):
        self.ensure_awake()
        kvm_mode = "kvm" if self.kvm else "tcg"
        meta_str = f"{self.memory}_{self.cores}_{kvm_mode}"
        if action == "save":
            ok, msg = self.qemu_monitor_cmd("savevm quickboot", timeout=45.0)
            if ok:
                try:
                    with open(QUICKBOOT_META, "w", encoding="utf-8") as f:
                        f.write(meta_str)
                except Exception:
                    pass
                return True, "Quickboot VM snapshot saved! Future restarts will boot in ~3 seconds."
            return False, f"Failed to save snapshot: {msg}"
        elif action == "load":
            ok, msg = self.qemu_monitor_cmd("loadvm quickboot", timeout=30.0)
            return ok, "Quickboot snapshot restored!" if ok else f"Failed to load snapshot: {msg}"
        elif action == "delete":
            self.qemu_monitor_cmd("delvm quickboot", timeout=15.0)
            try:
                if os.path.exists(QUICKBOOT_META):
                    os.remove(QUICKBOOT_META)
            except Exception:
                pass
            return True, "Quickboot snapshot deleted."
        return False, f"Unknown snapshot action: {action}"

    def install_apk_file(self, apk_path, auto_launch=True):
        self.ensure_awake()
        meta = parse_apk(apk_path)
        pkg = meta["package"]

        ok, out = self.run_adb(["install", "-r", "-g", "-t", apk_path], timeout=120)
        if not ok or "Failure" in out:
            # Fallback without -g/-t for older pm implementations
            ok, out = self.run_adb(["install", "-r", apk_path], timeout=120)
            if not ok or "Failure" in out:
                raise RuntimeError(f"ADB install failed: {out}")

        app_record = {
            "package": pkg,
            "label": meta["label"],
            "versionName": meta["versionName"],
            "launchActivity": meta["launchActivity"],
            "abis": meta["abis"],
            "orientation": meta["orientation"],
            "icon": meta["icon"],
            "installedAt": int(time.time()),
        }
        self.apps[pkg] = app_record
        self._save_apps()

        launch_msg = ""
        if auto_launch:
            _, launch_msg = self.launch_app(pkg, meta["launchActivity"], single_app=True)

        return {
            "ok": True,
            "app": app_record,
            "adbOutput": out,
            "launchMessage": launch_msg,
        }

    def launch_app(self, pkg, activity=None, single_app=True):
        if not SAFE_PKG_RE.match(str(pkg or "")):
            return False, "Invalid package name"
        self.ensure_awake()

        if not activity and pkg in self.apps:
            activity = self.apps[pkg].get("launchActivity")

        stopped = []
        if single_app:
            plan = build_session_commands(
                pkg,
                list(self.apps.keys()),
                deep_trim=False,
                kill_background=True,
            )
            stopped = plan["stopped"]
            if plan["commands"]:
                self.run_adb_shell("; ".join(plan["commands"]), timeout=15)

        if activity:
            component = f"{pkg}/{activity}"
            ok, out = self.run_adb_shell(f"am start -n {component}", timeout=15)
            if not ok or "Error:" in out:
                ok, out = self.run_adb_shell(
                    f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
                    timeout=15,
                )
        else:
            ok, out = self.run_adb_shell(
                f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
                timeout=15,
            )

        if ok:
            self.foreground_pkg = pkg
        stop_note = f" (stopped {len(stopped)} background app(s))" if stopped else ""
        return ok, f"Launched {pkg}{stop_note}"

    def stop_app(self, pkg):
        if not SAFE_PKG_RE.match(str(pkg or "")):
            return False, "Invalid package name"
        self.ensure_awake()
        ok, out = self.run_adb_shell(f"am force-stop {pkg}", timeout=10)
        if self.foreground_pkg == pkg:
            self.foreground_pkg = None
        return ok, f"Stopped {pkg}"

    def uninstall_app(self, pkg):
        if not SAFE_PKG_RE.match(str(pkg or "")):
            return False, "Invalid package name"
        self.ensure_awake()
        ok, out = self.run_adb(["uninstall", pkg], timeout=30)
        if pkg in self.apps:
            del self.apps[pkg]
            self._save_apps()
        if self.foreground_pkg == pkg:
            self.foreground_pkg = None
        return ok, out or f"Uninstalled {pkg}"

    def send_input(self, payload):
        self.ensure_awake()
        itype = payload.get("type")
        if itype == "tap":
            x = int(payload.get("x", 0))
            y = int(payload.get("y", 0))
            cmd = f"input tap {x} {y}"
        elif itype == "swipe":
            x1 = int(payload.get("x1", 0))
            y1 = int(payload.get("y1", 0))
            x2 = int(payload.get("x2", 0))
            y2 = int(payload.get("y2", 0))
            dur = int(payload.get("duration", 300))
            cmd = f"input swipe {x1} {y1} {x2} {y2} {dur}"
        elif itype == "key":
            key = int(payload.get("keycode", 3))
            cmd = f"input keyevent {key}"
        elif itype == "text":
            raw = str(payload.get("text", ""))
            escaped = raw.replace(" ", "%s").replace("'", "")
            cmd = f"input text '{escaped}'"
        else:
            return False, "Unknown input type", ""

        ok, out = self.run_adb_shell(cmd, timeout=10)
        yaml_snippet = (
            "service: androidtv.adb_command\n"
            "target:\n"
            "  entity_id: media_player.android_x86_emulator\n"
            "data:\n"
            f'  command: "{cmd}"'
        )
        return ok, out or f"Executed: {cmd}", yaml_snippet

    def get_status(self):
        state = {
            "phase": "starting",
            "message": "Starting emulator...",
            "kvm": self.kvm,
            "memory": self.memory,
            "cores": self.cores,
            "quickboot": self.quickboot,
            "deep_trim": self.deep_trim,
            "idle_park_minutes": self.idle_park_minutes,
        }
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    state.update(json.load(f))
            except Exception:
                pass

        if self.parked:
            state["phase"] = "parked"
            state["message"] = "Parked in 0% CPU Idle Mode (Wake or launch any app to resume)"
        elif self.boot_completed:
            state["phase"] = "ready"
            state["message"] = "Android ready (ApkStart Single-App Container active)"

        disk_mb = 0
        if os.path.exists(DISK_PATH):
            try:
                disk_mb = round(os.path.getsize(DISK_PATH) / 1048576, 1)
            except Exception:
                pass

        return {
            **state,
            "installed": os.path.exists(INSTALLED_MARKER),
            "adbConnected": self.adb_connected,
            "bootCompleted": self.boot_completed,
            "parked": self.parked,
            "trimmed": self.trimmed_once,
            "hasSnapshot": self.has_quickboot_snapshot(),
            "foregroundPackage": self.foreground_pkg,
            "diskSizeMb": disk_mb,
            "idleSeconds": int(time.time() - self.last_activity),
            "apps": list(self.apps.values()),
        }

    def background_loop(self):
        """Watchdog thread: connects ADB, trims system on boot, saves snapshot, and auto-parks."""
        while True:
            time.sleep(5)
            try:
                if not os.path.exists(INSTALLED_MARKER):
                    continue
                if self.parked:
                    continue

                subprocess.run(
                    ["adb", "connect", ADB_TARGET],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                ok, out = self.run_adb_shell("getprop sys.boot_completed", timeout=5)
                if ok and out.strip() == "1":
                    self.adb_connected = True
                    self.boot_completed = True

                    if not self.trimmed_once:
                        print("[ApkStart] Android boot completed! Applying ApkStart container trim & 0-animation tweaks...")
                        self.apply_apkstart_optimizations()
                        self.sync_installed_packages()
                        self.trimmed_once = True

                        if self.quickboot and not os.path.exists(QUICKBOOT_META):
                            print("[ApkStart] Saving initial Quickboot VM snapshot for instant future startups...")
                            self.manage_snapshot("save")
                else:
                    self.adb_connected = False

                # Auto-park watchdog (like apkstart engine.js idleShutdownMinutes)
                if (
                    self.boot_completed
                    and not self.parked
                    and self.idle_park_minutes > 0
                    and (time.time() - self.last_activity) > (self.idle_park_minutes * 60)
                ):
                    print(f"[ApkStart] Idle for >{self.idle_park_minutes}m. Parking Android in Doze mode...")
                    self.park_vm(freeze_cpu=False)
                    self.touch_activity()
            except Exception as e:
                print(f"[ApkStart] Watchdog warning: {e}")


RUNTIME = RuntimeManager()


# ==============================================================================
# 4. Unified Websockify + ApkStart REST API Handler on Port 8099
# ==============================================================================

try:
    from websockify.websocketproxy import ProxyRequestHandler, WebSocketProxy
except ImportError:
    from http.server import SimpleHTTPRequestHandler as ProxyRequestHandler
    WebSocketProxy = None


class ApkStartIngressHandler(ProxyRequestHandler):
    """Serves noVNC static files, proxies /websockify to QEMU VNC :5900, and handles /api/*."""

    def _api_route(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        idx = path.find("/api/")
        if idx != -1:
            return path[idx:]
        return None

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        route = self._api_route()
        if route == "/api/status":
            self._send_json(RUNTIME.get_status())
            return
        if route == "/api/apps":
            RUNTIME.sync_installed_packages()
            self._send_json({"ok": True, "apps": list(RUNTIME.apps.values())})
            return
        super().do_GET()

    def do_POST(self):
        route = self._api_route()
        if not route:
            self._send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            if route in ("/api/install-apk", "/api/parse-apk"):
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    self._send_json({"ok": False, "error": "Empty APK upload"}, HTTPStatus.BAD_REQUEST)
                    return
                auto_launch = self.headers.get("X-Auto-Launch", "true").lower() != "false"
                with tempfile.NamedTemporaryFile(dir="/tmp", suffix=".apk", delete=False) as tf:
                    temp_path = tf.name
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            break
                        tf.write(chunk)
                        remaining -= len(chunk)
                try:
                    if route == "/api/parse-apk":
                        meta = parse_apk(temp_path)
                        self._send_json(meta)
                    else:
                        res = RUNTIME.install_apk_file(temp_path, auto_launch=auto_launch)
                        self._send_json(res)
                finally:
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                return

            payload = self._read_json_body()

            if route == "/api/launch":
                ok, msg = RUNTIME.launch_app(
                    payload.get("package"),
                    payload.get("activity"),
                    single_app=payload.get("single_app", True),
                )
                self._send_json({"ok": ok, "message": msg})
            elif route == "/api/stop-app":
                ok, msg = RUNTIME.stop_app(payload.get("package"))
                self._send_json({"ok": ok, "message": msg})
            elif route == "/api/uninstall":
                ok, msg = RUNTIME.uninstall_app(payload.get("package"))
                self._send_json({"ok": ok, "message": msg})
            elif route == "/api/park":
                freeze = payload.get("freeze_cpu", True)
                ok, msg = RUNTIME.park_vm(freeze_cpu=freeze)
                self._send_json({"ok": ok, "message": msg, "parked": RUNTIME.parked})
            elif route == "/api/wake":
                ok, msg = RUNTIME.wake_vm()
                self._send_json({"ok": ok, "message": msg, "parked": RUNTIME.parked})
            elif route == "/api/snapshot":
                ok, msg = RUNTIME.manage_snapshot(payload.get("action", "save"))
                self._send_json({"ok": ok, "message": msg, "hasSnapshot": RUNTIME.has_quickboot_snapshot()})
            elif route == "/api/trim":
                RUNTIME.ensure_awake()
                ok, msg = RUNTIME.apply_apkstart_optimizations()
                self._send_json({"ok": ok, "message": "Applied ApkStart deep system trim & 0-animation settings."})
            elif route == "/api/finish-install":
                with open(INSTALLED_MARKER, "w", encoding="utf-8") as f:
                    f.write(str(int(time.time())))
                self._send_json({"ok": True, "message": "Marked installation complete. Transitioning to Running Mode..."})
            elif route == "/api/input":
                ok, msg, yaml_str = RUNTIME.send_input(payload)
                self._send_json({"ok": ok, "message": msg, "yaml": yaml_str})
            else:
                self._send_json({"ok": False, "error": f"Unknown route {route}"}, HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main():
    watchdog = threading.Thread(target=RUNTIME.background_loop, daemon=True)
    watchdog.start()

    web_dir = "/usr/share/novnc" if os.path.exists("/usr/share/novnc") else "."
    port = int(os.environ.get("APKSTART_PORT", "8099"))

    if WebSocketProxy is not None:
        print(f"[ApkStart] Starting unified Websockify + ApkStart API server on 0.0.0.0:{port} -> 127.0.0.1:5900")
        server = WebSocketProxy(
            RequestHandlerClass=ApkStartIngressHandler,
            listen_host="0.0.0.0",
            listen_port=port,
            target_host="127.0.0.1",
            target_port=5900,
            web=web_dir,
        )
        server.start_server()
    else:
        from http.server import ThreadingHTTPServer
        os.chdir(web_dir)
        httpd = ThreadingHTTPServer(("0.0.0.0", port), ApkStartIngressHandler)
        print(f"[ApkStart] Starting standalone HTTP API server on 0.0.0.0:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
