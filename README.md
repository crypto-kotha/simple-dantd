# simple-dantd

A simple web UI to configure and manage a Dante SOCKS5 proxy (danted). It lets you:
- Manage allowed client subnets
- Create/update system users for proxy auth
- Write danted.conf safely
- Restart the service and test connectivity per user

## Prerequisites
- Linux with sudo access
- Dante server (danted) installed via your package manager
- Python 3.11+ (virtualenv is created by `run.sh`)

## Quick Start
1) Clone the repo

2) Create your `.env` from the example and set admin login credentials for the UI:
```
cp .env.example .env
# edit values
ADMIN_USER=admin
ADMIN_PASS=admin
```

3) Run the UI:
```
bash ./run.sh
```
This will:
- Ensure `127.0.0.50` is bound to loopback
- Create and activate a virtualenv `.venv/`
- Install dependencies
- Start the Flask UI at http://127.0.0.50:7000

4) Login using the admin credentials you set in `.env`.

## Using the UI
- Add rows for: subnet, user, password
- Click "Save and Deploy"
- You will be prompted for your sudo password (needed to write config, create users, restart service)
- After deploy, the UI tests connectivity per user and shows a sample curl command

## Environment Variables
The UI reads these from the `.env` file:
- `ADMIN_USER` - UI login username
- `ADMIN_PASS` - UI login password

The Flask session secret is managed in code (can be overridden via `DANTE_UI_SECRET` environment variable if you need to change it in an environment, but it is not read from `.env` by default).

## Important Notes
- The app writes state to `/etc/dante-ui.json` and manages `danted.conf` at `/etc/danted.conf`.
- The managed Linux group is `danteproxy` and proxy users are added to it.
- Default proxy port is `1080`.
- Network/service operations require sudo.

## Development
- Flask version is pinned in `webui/requirements.txt`. The UI server code lives in `webui/app.py`.
- Static assets and templates are under `webui/static/` and `webui/templates/`.

## Screenshots

### Add new subnet
![Add new subnet](webui/.asset/add_new_subnet.png)

### Deployment result
![Deployment result](webui/.asset/result.png)

## License
MIT
