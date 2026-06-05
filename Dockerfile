ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Install QEMU, VNC, noVNC, websockify, and ADB tools
RUN apk update && apk add --no-cache \
    qemu-system-x86_64 \
    qemu-img \
    websockify \
    novnc \
    x11vnc \
    xvfb \
    bash \
    curl \
    wget \
    android-tools

# Copy files
COPY start.sh /app/start.sh
COPY index.html /usr/share/novnc/index.html

RUN chmod a+x /app/start.sh

# Expose ports
EXPOSE 8099
EXPOSE 5555

WORKDIR /data

ENTRYPOINT ["/app/start.sh"]
