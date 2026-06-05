## 1.1.0
- **Fix:** Removed the deprecated `-soundhw ac97` flag that caused newer QEMU versions to crash on startup.
- **Improvement:** Refactored files into the `android-x86/` subdirectory for proper Home Assistant Supervisor repository compliance.

## 1.0.0
- **Feature:** Initial release containing a headless QEMU container running Android-x86.
- **Feature:** Added dynamic Ingress WebSocket route resolution to embed noVNC directly in the Home Assistant sidebar.
- **Feature:** Exposed port `5555` for native remote ADB script automation.
