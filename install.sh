#!/bin/bash
# One-time system setup for the ROCKEY dongle bridge. Run with: sudo ./install.sh
# Remove again with: sudo ./install.sh --uninstall
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
here="$(dirname "$(readlink -f "$0")")"

BIN=/usr/local/lib/rockey-hid-bridge.py
RULES=/etc/udev/rules.d/70-rockey-hid-bridge.rules
UNIT=/etc/systemd/system/rockey-hid-bridge@.service

if [ "${1:-}" = "--uninstall" ]; then
    systemctl stop 'rockey-hid-bridge@*.service' 2>/dev/null || true
    rm -f "$BIN" "$RULES" "$UNIT"
    systemctl daemon-reload
    udevadm control --reload
    echo "Removed."
    exit 0
fi

install -m 755 "$here/rockey-hid-bridge.py" "$BIN"

cat > "$UNIT" <<EOF
[Unit]
Description=ROCKEY HID dongle bridge (%i)

[Service]
ExecStart=$BIN %i
Restart=no
EOF

cat > "$RULES" <<'EOF'
# Feitian ROCKEY "HID Dongle": start the hidraw bridge when it is plugged in
ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="096e", ATTR{idProduct}=="0006", TAG+="systemd", ENV{SYSTEMD_WANTS}+="rockey-hid-bridge@%k.service"
# Let the logged-in user open the bridged hidraw device (Wine needs this)
SUBSYSTEM=="hidraw", KERNELS=="0003:096E:0006.*", TAG+="uaccess"
EOF

systemctl daemon-reload
udevadm control --reload

# Start the bridge for dongles that are already plugged in
for d in /sys/bus/usb/devices/*; do
    [ -r "$d/idVendor" ] || continue
    if [ "$(cat "$d/idVendor")" = 096e ] && [ "$(cat "$d/idProduct")" = 0006 ]; then
        systemctl restart "rockey-hid-bridge@$(basename "$d").service"
        echo "Bridge started for dongle at $(basename "$d")."
    fi
done
echo "Done."
