#!/usr/bin/env bashio

# Read add-on options using bashio
INSTALLED=$(bashio::config 'installed')
MEMORY=$(bashio::config 'memory')
CORES=$(bashio::config 'cores')

echo "==========================================="
echo " Starting Android-x86 QEMU Emulator Add-on "
echo "==========================================="

# Check for KVM hardware acceleration
if [ -e /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "[INFO] KVM Hardware Acceleration is available! Enabling native CPU speed virtualization."
    KVM_ARGS="-enable-kvm -cpu host"
else
    echo "[WARNING] KVM Hardware Acceleration is NOT available or writable!"
    echo "Android will run in software emulation mode, which is extremely CPU-heavy and slow."
    KVM_ARGS="-cpu max"
fi

ISO_PATH="/data/android-x86.iso"
DISK_PATH="/data/android.qcow2"

# 1. Download Android ISO if not already installed
if [ "$INSTALLED" = "false" ] || [ "$INSTALLED" = "null" ]; then
    if [ ! -f "$ISO_PATH" ]; then
        echo "[INFO] Downloading Android-x86 9.0-r2 ISO (approx. 900MB)..."
        # Download from SourceForge
        wget -q --show-progress -O "$ISO_PATH" "https://downloads.sourceforge.net/project/android-x86/Release%209.0/android-x86_64-9.0-r2.iso"
        echo "[INFO] Download complete!"
    else
        echo "[INFO] Android-x86 ISO already exists."
    fi
fi

# 2. Create the virtual hard drive if it doesn't exist
if [ ! -f "$DISK_PATH" ]; then
    echo "[INFO] Creating persistent virtual hard disk (16GB thin-provisioned)..."
    qemu-img create -f qcow2 "$DISK_PATH" 16G
    echo "[INFO] Virtual disk created successfully at $DISK_PATH"
else
    echo "[INFO] Existing virtual disk found at $DISK_PATH"
fi

# 3. Configure boot arguments depending on installation mode
if [ "$INSTALLED" = "false" ] || [ "$INSTALLED" = "null" ]; then
    echo "[INFO] Booting in INSTALLATION mode."
    echo "[INFO] Please open the Web UI (noVNC) to partition and install Android-x86 to the virtual disk."
    BOOT_ARGS="-cdrom $ISO_PATH -boot order=d"
else
    echo "[INFO] Booting in RUNNING mode."
    BOOT_ARGS="-boot order=c"
    # Clean up the ISO to save 900MB of space in /data
    if [ -f "$ISO_PATH" ]; then
        echo "[INFO] Deleting temporary installer ISO to free up space..."
        rm -f "$ISO_PATH"
    fi
fi

# 4. Start websockify proxy to expose QEMU VNC to browser Ingress
echo "[INFO] Starting Websockify on Ingress port 8099..."
websockify --web /usr/share/novnc 8099 localhost:5900 &
WEBSOCKIFY_PID=$!

# 5. Launch QEMU Virtual Machine in background
echo "[INFO] Starting QEMU with ${MEMORY}MB RAM and ${CORES} CPU cores..."
qemu-system-x86_64 \
    $KVM_ARGS \
    -m "$MEMORY" \
    -smp "$CORES" \
    -drive file="$DISK_PATH",format=qcow2,if=virtio \
    $BOOT_ARGS \
    -vga virtio \
    -display none \
    -vnc 0.0.0.0:0 \
    -net nic,model=virtio \
    -net user,hostfwd=tcp::5555-:5555 \
    -device virtio-tablet-pci \
    -soundhw ac97 &
QEMU_PID=$!

# Cleanup trap to shut down processes gracefully on stop
cleanup() {
    echo "[INFO] Stopping Add-on..."
    kill "$WEBSOCKIFY_PID"
    kill "$QEMU_PID"
    wait "$QEMU_PID" 2>/dev/null
    exit 0
}
trap cleanup SIGTERM SIGINT

# Wait for QEMU process to exit
wait "$QEMU_PID"
