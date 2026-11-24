#!/usr/bin/env bashio

# ==============================================================================
# Android-x86 QEMU Emulator Add-on (ApkStart Engine v2.0)
# Features:
#   - Zero-toggle auto-installation detection & ISO cleanup
#   - QEMU Quickboot VM snapshots (savevm/loadvm) with config change detection
#   - ApkStart single-app container system trimmer & zero-animation latency
#   - QMP/Monitor Unix sockets for 0% CPU idle parking & instant wake
# ==============================================================================

read_opt() {
    local key="$1"
    local default_val="$2"
    if command -v bashio::config >/dev/null 2>&1; then
        local val
        val=$(bashio::config "$key" 2>/dev/null || true)
        if [ -n "$val" ] && [ "$val" != "null" ]; then
            echo "$val"
            return
        fi
    fi
    echo "$default_val"
}

MEMORY=$(read_opt 'memory' '1536')
CORES=$(read_opt 'cores' '2')
QUICKBOOT=$(read_opt 'quickboot' 'true')
DEEP_TRIM=$(read_opt 'deep_trim' 'true')
IDLE_PARK_MINUTES=$(read_opt 'idle_park_minutes' '10')
FORCE_REINSTALL=$(read_opt 'force_reinstall' 'false')
LEGACY_INSTALLED=$(read_opt 'installed' 'auto')

export APKSTART_MEMORY="$MEMORY"
export APKSTART_CORES="$CORES"
export APKSTART_QUICKBOOT="$QUICKBOOT"
export APKSTART_DEEP_TRIM="$DEEP_TRIM"
export APKSTART_IDLE_PARK_MINUTES="$IDLE_PARK_MINUTES"

ISO_PATH="/data/android-x86.iso"
DISK_PATH="/data/android.qcow2"
KERNEL_PATH="/data/kernel"
INITRD_PATH="/data/initrd.img"
INSTALLED_MARKER="/data/.installed"
QUICKBOOT_META="/data/.quickboot_meta"
STATE_FILE="/data/runtime_state.json"
QMP_SOCK="/data/qmp.sock"
MON_SOCK="/data/monitor.sock"

write_state() {
    local phase="$1"
    local message="$2"
    cat > "$STATE_FILE" <<EOF
{
  "phase": "$phase",
  "message": "$message",
  "kvm": $KVM_AVAILABLE,
  "memory": $MEMORY,
  "cores": $CORES,
  "quickboot": $QUICKBOOT,
  "deep_trim": $DEEP_TRIM,
  "idle_park_minutes": $IDLE_PARK_MINUTES,
  "timestamp": $(date +%s)
}
EOF
}

echo "======================================================"
echo " Starting Android-x86 Emulator (ApkStart Engine v2.0) "
echo "======================================================"

# 1. Detect KVM hardware acceleration
if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "[INFO] KVM Hardware Acceleration is available! Enabling native virtualization."
    KVM_ARGS="-enable-kvm -cpu host"
    KVM_AVAILABLE="true"
    KVM_MODE="kvm"
else
    echo "[WARNING] KVM Hardware Acceleration is NOT available or writable!"
    echo "[WARNING] Running in QEMU software emulation mode (-cpu max)."
    KVM_ARGS="-cpu max"
    KVM_AVAILABLE="false"
    KVM_MODE="tcg"
fi

write_state "starting" "Initializing ApkStart runtime and Ingress control server..."

# 2. Start the ApkStart Ingress Web UI + Websockify + REST API Server on port 8099 immediately
#    so the user always gets live progress in Home Assistant Ingress.
echo "[INFO] Starting ApkStart Ingress Server & Websockify proxy on port 8099..."
python3 /app/server.py &
SERVER_PID=$!

QEMU_PID=""
cleanup() {
    echo "[INFO] Shutting down Add-on gracefully..."
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
    [ -n "$QEMU_PID" ] && kill "$QEMU_PID" 2>/dev/null || true
    [ -n "$QEMU_PID" ] && wait "$QEMU_PID" 2>/dev/null || true
    rm -f "$QMP_SOCK" "$MON_SOCK"
    exit 0
}
trap cleanup SIGTERM SIGINT

# 3. Check installation state automatically (no manual config toggle required)
if [ "$FORCE_REINSTALL" = "true" ]; then
    echo "[WARN] force_reinstall=true requested. Wiping existing virtual disk and snapshot state..."
    rm -f "$INSTALLED_MARKER" "$QUICKBOOT_META" "$DISK_PATH"
fi

# Migrate existing v1.x installations seamlessly
if [ ! -f "$INSTALLED_MARKER" ]; then
    if [ "$LEGACY_INSTALLED" = "true" ]; then
        echo "[INFO] Migrating existing v1.x installation (installed=true)..."
        touch "$INSTALLED_MARKER"
    elif [ -f "$DISK_PATH" ]; then
        DISK_BYTES=$(stat -c%s "$DISK_PATH" 2>/dev/null || echo 0)
        if [ "$DISK_BYTES" -gt 314572800 ]; then
            echo "[INFO] Existing initialized virtual disk detected ($((DISK_BYTES / 1048576)) MB). Marking as installed."
            touch "$INSTALLED_MARKER"
        fi
    fi
fi

ensure_boot_media() {
    if [ ! -f "$ISO_PATH" ]; then
        write_state "downloading" "Downloading Android-x86 9.0-r2 ISO (~900 MB)..."
        echo "[INFO] Downloading Android-x86 9.0-r2 ISO (approx. 900MB)..."
        wget -q --show-progress -O "${ISO_PATH}.part" \
            "https://downloads.sourceforge.net/project/android-x86/Release%209.0/android-x86_64-9.0-r2.iso"
        mv "${ISO_PATH}.part" "$ISO_PATH"
        echo "[INFO] ISO download complete!"
    fi

    if [ ! -f "$KERNEL_PATH" ] || [ ! -f "$INITRD_PATH" ]; then
        write_state "extracting" "Extracting direct-boot kernel and initrd from ISO..."
        echo "[INFO] Extracting boot kernel and initrd from ISO to /data..."
        bsdtar -xf "$ISO_PATH" -C /data kernel initrd.img
        echo "[INFO] Kernel extraction complete."
    fi
}

# 4. Direct Userspace First-Time Disk Provisioning (No QEMU Installer VM Needed!)
#    Wait-free replacement for AUTO_INSTALL: extracts ramdisk.img & system.sfs from ISO
#    and builds the ext4 virtual disk directly in userspace via mke2fs -d in ~5-10 seconds.
if [ ! -f "$INSTALLED_MARKER" ]; then
    ensure_boot_media

    STAGING_DIR="/data/staging"
    ANDROID_DIR="${STAGING_DIR}/android-9.0-r2"
    RAW_DISK="/data/android.raw"

    rm -rf "$STAGING_DIR" "$RAW_DISK" "$DISK_PATH"
    mkdir -p "${ANDROID_DIR}/data"

    write_state "extracting" "Extracting Android system image (ramdisk.img & system.sfs) from ISO..."
    echo "[INFO] Extracting ramdisk.img and system.sfs from ISO to staging directory..."
    bsdtar -xf "$ISO_PATH" -C "$ANDROID_DIR" ramdisk.img system.sfs
    chmod -R 755 "$ANDROID_DIR"
    chmod 771 "${ANDROID_DIR}/data"

    write_state "installing" "Building 16GB ext4 Android virtual disk directly in userspace (~10s)..."
    echo "[INFO] Building 16GB ext4 filesystem image directly via mke2fs -d (no QEMU installer hang)..."
    truncate -s 16G "$RAW_DISK"
    mke2fs -t ext4 -F -L "Android-x86" -d "$STAGING_DIR" "$RAW_DISK"

    write_state "installing" "Converting virtual disk to thin-provisioned qcow2 format..."
    echo "[INFO] Converting raw ext4 image to thin-provisioned qcow2..."
    qemu-img convert -f raw -O qcow2 "$RAW_DISK" "$DISK_PATH"

    rm -rf "$STAGING_DIR" "$RAW_DISK"
    touch "$INSTALLED_MARKER"
    echo "[INFO] Direct userspace disk provisioning finished in seconds! Transitioning to RUNNING mode..."
fi

# 5. Fallback: Create persistent virtual hard disk if somehow missing
if [ ! -f "$DISK_PATH" ]; then
    echo "[INFO] Creating persistent virtual hard disk (16GB thin-provisioned qcow2)..."
    qemu-img create -f qcow2 "$DISK_PATH" 16G
fi

# 6. Ensure kernel & initrd exist for direct booting, then reclaim 900MB ISO
if [ ! -f "$KERNEL_PATH" ] || [ ! -f "$INITRD_PATH" ]; then
    ensure_boot_media
fi
if [ -f "$ISO_PATH" ]; then
    echo "[INFO] Deleting 900MB installer ISO to reclaim host storage..."
    rm -f "$ISO_PATH"
fi

# 7. Check Quickboot Snapshot validity (ApkStart layers.js invalidation pattern)
CURRENT_META="${MEMORY}_${CORES}_${KVM_MODE}"
LOADVM_ARGS=""
if [ "$QUICKBOOT" = "true" ]; then
    if qemu-img snapshot -l "$DISK_PATH" 2>/dev/null | grep -q "quickboot"; then
        SAVED_META=$(cat "$QUICKBOOT_META" 2>/dev/null || echo "")
        if [ "$SAVED_META" = "$CURRENT_META" ]; then
            echo "[INFO] Valid Quickboot snapshot found! Restoring running Android state in seconds..."
            LOADVM_ARGS="-loadvm quickboot"
            write_state "restoring" "Restoring Quickboot VM snapshot..."
        else
            echo "[INFO] Hardware config changed ($SAVED_META -> $CURRENT_META). Discarding stale Quickboot snapshot..."
            qemu-img snapshot -d quickboot "$DISK_PATH" 2>/dev/null || true
            rm -f "$QUICKBOOT_META"
        fi
    fi
fi

# 8. Boot QEMU in RUNNING mode with QMP & Monitor sockets
if [ -z "$LOADVM_ARGS" ]; then
    write_state "booting" "Booting Android-x86 guest kernel (${MEMORY}MB RAM, ${CORES} cores)..."
fi
echo "[INFO] Starting QEMU in RUNNING mode (${MEMORY}MB RAM, ${CORES} CPU cores)..."
rm -f "$QMP_SOCK" "$MON_SOCK"

qemu-system-x86_64 \
    $KVM_ARGS \
    -m "$MEMORY" \
    -smp "$CORES" \
    -drive file="$DISK_PATH",format=qcow2,if=virtio,cache=writeback \
    -kernel "$KERNEL_PATH" \
    -initrd "$INITRD_PATH" \
    -append "root=/dev/ram0 androidboot.selinux=permissive nomodeset xforcevesa quiet SRC=/android-9.0-r2" \
    -vga std \
    -display none \
    -vnc 0.0.0.0:0 \
    -qmp "unix:${QMP_SOCK},server,nowait" \
    -monitor "unix:${MON_SOCK},server,nowait" \
    -net nic,model=virtio \
    -net user,hostfwd=tcp::5555-:5555 \
    -device virtio-tablet-pci \
    $LOADVM_ARGS &
QEMU_PID=$!

#Wait for QEMU process to exit
wait "$QEMU_PID"
