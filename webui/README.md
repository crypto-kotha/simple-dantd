# Dante SOCKS5 Web UI

A Flask-based web UI to manage your Dante (danted) SOCKS5 server.

- Binds UI on 127.0.0.50:7000
- Login required (default: admin/admin; change via env)
- Shows existing allowed IP subnets and managed users
- Add/update rows with Allowed IP/Subnet + Proxy User + Proxy Pass
- Saves to /etc/danted.conf, restarts danted, and tests each user via curl

## Directory

- `app.py` — Flask app
- `templates/` — UI pages
- `static/` — CSS
- `requirements.txt` — Python deps
- `run.sh` — helper to run UI

## Prereqs

- Python 3.9+
- curl installed (for connectivity tests)
- Systemd-managed danted service installed and working

## Install deps (virtualenv recommended)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Configure admin login (optional but recommended)

```bash
export ADMIN_USER="youradmin"
export ADMIN_PASS="strongpassword"
export DANTE_UI_SECRET="random-secret-key"
```

## Bind UI host 127.0.0.50

Add a loopback alias once per boot (or persist via network config):

```bash
sudo ip addr add 127.0.0.50/32 dev lo
```

## Run the UI

```bash
./run.sh
```

If you don’t use run.sh, you can run directly:

```bash
python app.py
```

Visit: http://127.0.0.50:7000

## Notes

- Users are managed as system users in group `danteproxy`. Deleting a user here removes it from that group (account remains unless you extend delete logic).
- The UI writes `/etc/danted.conf` and restarts the `danted` service (sudo required). Ensure your sudoers allows the current user to run the required systemctl, useradd/usermod, chpasswd, mv, cp commands without TTY.
- The app auto-adds `127.0.0.1/32` and the server’s primary IP `/32` to allowed subnets to avoid lockout.
