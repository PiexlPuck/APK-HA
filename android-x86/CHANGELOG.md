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
