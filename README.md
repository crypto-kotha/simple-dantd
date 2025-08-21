# Dante (danted) SOCKS5 Proxy – Auto Setup Script

Automated installer for the Dante (danted) SOCKS5 proxy. It auto-detects the server IP and interface, configures secure IP allowlists, sets up a systemd service, and verifies connectivity.

## Features
* **Auto-detect IP/interface**: Finds the public IPv4 and the correct NIC automatically.
* **Single prompt**: Only asks for allowed client subnets (comma-separated). Press Enter to keep defaults.
* **No-auth SOCKS by default**: `socksmethod: none` and `clientmethod: none` — access is restricted by IP allowlists and firewall rules.
* **Firewall integration**: Configures ufw or firewalld (if present) to allow TCP 1080 only from allowed subnets.
* **Systemd service**: Ensures, enables, and starts `danted`.
* **Modern config**: Uses `socksmethod`/`clientmethod` (no deprecated `method`).

## Supported
* Debian/Ubuntu (apt)
* RHEL/CentOS/Rocky/Alma (yum/dnf)
* Systemd-based systems

## Requirements
* Run as `root` (or with `sudo`).
* Internet access (to install packages and to run the connectivity test).

## Quick start
```bash
# 1) Copy to the server (example)
scp -o StrictHostKeyChecking=no -P 22 -r danted-setup/ root@<SERVER_IP>:/root/

# 2) SSH to the server
ssh -p 22 root@<SERVER_IP>

# 3) Install and configure
cd /root/danted-setup
chmod +x setup.sh
sudo ./setup.sh
```

During the run, you will be asked once for allowed client subnets. Provide a comma-separated list like:
```
37.111.0.0/16, 103.112.0.0/16, 182.160.0.0/16
```

The generated config uses `socksmethod: none` and `clientmethod: none`. Access is controlled by IP allowlists and firewall rules.

## Verify on the server
```bash
systemctl status danted --no-pager
journalctl -u danted -e --no-pager
ss -lntp | grep ":1080 " || netstat -lntp | grep ":1080 "
```

## Use from a client
Test from an allowed client (replace SERVER_IP):
```bash
curl -v --max-time 15 --socks5-hostname <SERVER_IP>:1080 https://ifconfig.me
```

## Troubleshooting
* __Timeout / connection refused__
  - Ensure your client public IP is in the allowed subnets and firewall permits TCP 1080.
* __No authentication method was acceptable__
  - Confirm `/etc/danted.conf` contains `socksmethod: none` and restart: `sudo systemctl restart danted`.
* __Check logs__
  ```bash
  journalctl -u danted -f --no-pager
  ```

## Uninstall / revert
```bash
systemctl disable --now danted || true
rm -f /etc/systemd/system/danted.service
systemctl daemon-reload
rm -f /etc/danted.conf
# Optionally remove package
apt-get remove -y dante-server danted 2>/dev/null || dnf remove -y dante-server danted 2>/dev/null || yum remove -y dante-server danted 2>/dev/null || true
```

## License
MIT

## Disclaimer
Exposing a proxy to the internet can be risky. Keep your allowlists narrow and your firewalls strict. Change defaults if your security policy requires user authentication.
