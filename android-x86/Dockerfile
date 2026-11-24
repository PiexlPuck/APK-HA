ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Install QEMU, noVNC, websockify (Python 3), ADB, and ISO extraction tools
# Dropped unused x11vnc/xvfb/curl packages to reduce image size
RUN apk update && apk add --no-cache \
    qemu-system-x86_64 \
    qemu-img \
    e2fsprogs \
    python3 \
    websockify \
    novnc \
    bash \
    wget \
    android-tools \
    libarchive-tools

# Copy runtime scripts and apkstart-powered Ingress UI
COPY start.sh /app/start.sh
COPY server.py /app/server.py
COPY index.html /usr/share/novnc/index.html

RUN sed -i 's/\r$//' /app/start.sh /app/server.py && \
    chmod a+x /app/start.sh /app/server.py

# Expose ports
EXPOSE 8099
EXPOSE 5555

WORKDIR /data

ENTRYPOINT ["/app/start.sh"]
