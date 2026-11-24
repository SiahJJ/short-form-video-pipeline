#!/usr/bin/env bash
# pi_guard.sh - keep the always-on Pi from running out of memory or disk. Run once (safe to re-run):
#   sudo bash ~/automation-mirror/pi_guard.sh
# What it sets up:
#   Memory  - each web app is capped (MemoryMax) and restarted automatically if it ever exceeds it,
#             so one app can never starve the Pi; systemd restarts crashed apps after 5 s.
#   Logs    - the system journal is capped at 100 MB (it otherwise grows for months on an SD card).
#   Disk    - a daily cleanup (pi-cleanup.timer): apt download cache, temp files older than 3 days,
#             leftover mirror uploads, and keeps the newest 30 files in ~/bill-tracker/backups (if present).
#             If free space ever drops under 1 GB it also clears old journal entries and logs a warning.
set -euo pipefail
[ "$EUID" -eq 0 ] || { echo "Run with sudo."; exit 1; }
U="${SUDO_USER:-pi}"; H="/home/$U"

# 1) memory caps for the apps (only for services that exist)
for svc in automation-mirror bill-tracker; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1 && [ -f "/etc/systemd/system/$svc.service" ]; then
    mkdir -p "/etc/systemd/system/$svc.service.d"
    cat > "/etc/systemd/system/$svc.service.d/limits.conf" <<EOF
[Service]
MemoryMax=200M
MemoryHigh=150M
Restart=always
RestartSec=5
EOF
    echo "memory cap set: $svc (200 MB, auto-restart)"
  fi
done

# 2) cap the system journal
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/size.conf <<'EOF'
[Journal]
SystemMaxUse=100M
RuntimeMaxUse=50M
EOF
systemctl restart systemd-journald
echo "journal capped at 100 MB"

# 3) daily disk cleanup
cat > /usr/local/bin/pi-cleanup <<EOF
#!/usr/bin/env bash
apt-get clean -y >/dev/null 2>&1 || true
find /tmp /var/tmp -xdev -type f -mtime +3 -delete 2>/dev/null || true
rm -rf "$H/automation-mirror/incoming/"* 2>/dev/null || true
if [ -d "$H/bill-tracker/backups" ]; then
  ls -1t "$H/bill-tracker/backups" | tail -n +31 | while read -r f; do rm -f "$H/bill-tracker/backups/\$f"; done
fi
free_kb=\$(df --output=avail -k / | tail -1)
if [ "\$free_kb" -lt 1048576 ]; then
  journalctl --vacuum-size=50M >/dev/null 2>&1 || true
  logger -t pi-cleanup "LOW DISK: \$((free_kb/1024)) MB free after cleanup"
fi
logger -t pi-cleanup "done: \$((free_kb/1024)) MB free"
EOF
chmod +x /usr/local/bin/pi-cleanup
cat > /etc/systemd/system/pi-cleanup.service <<'EOF'
[Unit]
Description=Daily disk cleanup
[Service]
Type=oneshot
ExecStart=/usr/local/bin/pi-cleanup
EOF
cat > /etc/systemd/system/pi-cleanup.timer <<'EOF'
[Unit]
Description=Run pi-cleanup daily
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now pi-cleanup.timer >/dev/null
for svc in automation-mirror bill-tracker; do systemctl is-active --quiet "$svc" && systemctl restart "$svc" || true; done
/usr/local/bin/pi-cleanup
echo "daily cleanup scheduled"
echo; echo "Memory:"; free -h | head -2
echo "Disk:"; df -h / | tail -1
