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

# 3. Start websockify proxy to expose QEMU VNC to browser Ingress
echo "[INFO] Starting Websockify on Ingress port 8099..."
websockify --web /usr/share/novnc 8099 localhost:5900 &
WEBSOCKIFY_PID=$!

# 4. Launch QEMU Virtual Machine depending on installation mode
echo "[INFO] Starting QEMU with ${MEMORY}MB RAM and ${CORES} CPU cores..."
if [ "$INSTALLED" = "false" ] || [ "$INSTALLED" = "null" ]; then
    echo "[INFO] Booting in AUTOMATED INSTALLATION mode."
    echo "[INFO] Extracting kernel and initrd.img from ISO..."
    bsdtar -xf "$ISO_PATH" -C /tmp kernel initrd.img
    echo "[INFO] Extraction complete. Starting automated installation..."
    
    qemu-system-x86_64 \
        $KVM_ARGS \
        -m "$MEMORY" \
        -smp "$CORES" \
        -drive file="$DISK_PATH",format=qcow2,if=virtio \
        -cdrom "$ISO_PATH" \
        -kernel /tmp/kernel \
        -initrd /tmp/initrd.img \
        -append "root=/dev/ram0 androidboot.selinux=permissive AUTO_INSTALL=0" \
        -vga std \
        -display none \
        -vnc 0.0.0.0:0 \
        -net nic,model=virtio \
        -net user,hostfwd=tcp::5555-:5555 \
        -device virtio-tablet-pci &
else
    echo "[INFO] Booting in RUNNING mode."
    # Clean up the ISO and temporary boot files to save space
    rm -f "/tmp/kernel" "/tmp/initrd.img"
    if [ -f "$ISO_PATH" ]; then
        echo "[INFO] Deleting temporary installer ISO to free up space..."
        rm -f "$ISO_PATH"
    fi
    
    qemu-system-x86_64 \
        $KVM_ARGS \
        -m "$MEMORY" \
        -smp "$CORES" \
        -drive file="$DISK_PATH",format=qcow2,if=virtio \
        -boot order=c \
        -vga std \
        -display none \
        -vnc 0.0.0.0:0 \
        -net nic,model=virtio \
        -net user,hostfwd=tcp::5555-:5555 \
        -device virtio-tablet-pci &
fi
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
