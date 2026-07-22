FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    ALPECCA_DESKTOP_ONLY=1 \
    ALPECCA_DESKTOP_STATE_DIR=/data/alpecca-desktop \
    DISPLAY=:1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        dbus-x11 \
        mousepad \
        novnc \
        python3 \
        python3-websockify \
        thunar \
        tigervnc-standalone-server \
        tini \
        xfce4 \
        xfce4-terminal \
        xfonts-base \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 1000 -g 1000 /data /home/alpecca /opt/alpecca-desktop \
    && cp /usr/share/novnc/vnc.html /usr/share/novnc/index.html

COPY --chown=1000:1000 start-desktop.sh /opt/alpecca-desktop/start-desktop.sh
COPY --chown=1000:1000 healthz /usr/share/novnc/healthz
RUN chmod 0555 /opt/alpecca-desktop/start-desktop.sh \
    && chmod 0444 /usr/share/novnc/healthz

USER 1000
WORKDIR /home/alpecca
EXPOSE 7860

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/alpecca-desktop/start-desktop.sh"]
