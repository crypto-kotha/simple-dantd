import os
import re
import subprocess
import json
from urllib.parse import quote as urlquote
import time
import socket
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify

# Load environment variables from a .env file if present
from dotenv import load_dotenv
load_dotenv()

# Allow host/port override from environment to support external access when desired
APP_HOST = os.environ.get("APP_HOST", "127.0.0.50")
APP_PORT = int(os.environ.get("APP_PORT", 7000))
CONF = "/etc/danted.conf"
STATE_FILE = "/etc/dante-ui.json"
MANAGED_GROUP = "danteproxy"
DEFAULT_PORT = 1080

app = Flask(__name__)
# Note: The UI session secret is intentionally managed in code and not via .env
# You can override with an environment variable DANTE_UI_SECRET if needed, otherwise this default is used.
app.secret_key = os.environ.get("DANTE_UI_SECRET", "change-me-secret")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")

# --------- Helpers ---------

def cmd_exists(cmd: str) -> bool:
    return subprocess.call(["bash", "-lc", f"command -v {cmd} >/dev/null 2>&1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def run(cmd: str, require_root: bool = False, sudo_password: str = None) -> subprocess.CompletedProcess:
    """Run a shell command. If require_root, execute entire command under a single sudo context.

    Important: wrap the full command in a shell (bash -lc) when using sudo so that all chained
    operations (e.g., with &&, ||, redirects) run with elevated privileges, not just the first token.
    """
    if require_root and os.geteuid() != 0:
        # Escape single quotes for safe embedding inside a single-quoted bash -lc string
        escaped = cmd.replace("'", "'\"'\"'")
        if sudo_password:
            # Use printf to pass password via stdin; run entire chain inside sudo bash -lc
            cmd = f"printf '%s\\n' '{sudo_password}' | sudo -S bash -lc '{escaped}'"
        else:
            # Non-interactive; still ensure the whole chain runs under sudo
            cmd = f"sudo -n bash -lc '{escaped}'"
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def detect_iface() -> str:
    cp = run("ip route get 1.1.1.1 | awk '/dev/ {for (i=1;i<=NF;i++) if ($i==\"dev\") print $(i+1)}' | head -n1")
    iface = cp.stdout.strip()
    return iface or "lo"


def primary_ip_for_iface(iface: str) -> str:
    cp = run(f"ip -4 -o addr show dev {iface} scope global | awk '{{print $4}}' | cut -d/ -f1 | head -n1")
    return cp.stdout.strip()


def load_state():
    """Load subnet-user-password mappings from state file"""
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_state(entries, sudo_password=None):
    """Save subnet-user-password mappings to state file"""
    try:
        tmp_path = "/tmp/dante-ui.json.new"
        with open(tmp_path, 'w') as f:
            json.dump(entries, f, indent=2)
        
        # Create directory if it doesn't exist and move file with proper sudo
        res = run(f"mkdir -p /etc && mv {tmp_path} {STATE_FILE} && chown root:root {STATE_FILE} && chmod 644 {STATE_FILE} 2>&1", require_root=True, sudo_password=sudo_password)
        if res.returncode != 0:
            print(f"Error moving state file: {res.stdout} {res.stderr}")
            # Try alternative approach - copy then remove
            res2 = run(f"cp {tmp_path} {STATE_FILE} && chown root:root {STATE_FILE} && chmod 644 {STATE_FILE} && rm -f {tmp_path}", require_root=True, sudo_password=sudo_password)
            if res2.returncode != 0:
                print(f"Alternative copy failed: {res2.stdout} {res2.stderr}")
                return False
        return True
    except Exception as e:
        print(f"Error saving state: {e}")
        return False

def parse_allowed_clients(conf_text: str):
    allowed = []
    for m in re.finditer(r"client\s+pass\s*\{[^}]*?from:\s*([^\s]+)\s+to:\s*0.0.0.0/0", conf_text, flags=re.S):
        subnet = m.group(1).strip()
        if subnet not in allowed:
            allowed.append(subnet)
    return allowed


def read_conf():
    try:
        with open(CONF, "r") as f:
            text = f.read()
        return text
    except Exception:
        return ""


def list_proxy_users():
    out = run(f"getent group {MANAGED_GROUP} | awk -F: '{{print $4}}' ").stdout.strip()
    users = [u for u in out.split(',') if u]
    return users


def ensure_group(sudo_password=None):
    run(f"getent group {MANAGED_GROUP} || groupadd {MANAGED_GROUP}", require_root=True, sudo_password=sudo_password)


def ensure_user(username: str, password: str, sudo_password=None):
    ensure_group(sudo_password)
    nologin = "/usr/sbin/nologin" if os.path.exists("/usr/sbin/nologin") else "/sbin/nologin"
    run(f"id -u {username} >/dev/null 2>&1 || useradd -M -s {nologin} {username}", require_root=True, sudo_password=sudo_password)
    run(f"echo '{username}:{password}' | chpasswd", require_root=True, sudo_password=sudo_password)
    run(f"id -nG {username} | grep -qw {MANAGED_GROUP} || usermod -aG {MANAGED_GROUP} {username}", require_root=True, sudo_password=sudo_password)


def delete_user(username: str, sudo_password=None):
    run(f"id -u {username} >/dev/null 2>&1 && gpasswd -d {username} {MANAGED_GROUP}", require_root=True, sudo_password=sudo_password)


def write_danted_conf(allowed_subnets, sudo_password=None):
    iface = detect_iface()
    # Ensure self access for local testing and to avoid lockout
    bind_ip = primary_ip_for_iface(iface)
    # Normalize and append required /32s
    allowed_set = []
    for s in allowed_subnets:
        s = (s or "").strip()
        if s and s not in allowed_set:
            allowed_set.append(s)
    if bind_ip and f"{bind_ip}/32" not in allowed_set:
        allowed_set.append(f"{bind_ip}/32")
    if "127.0.0.1/32" not in allowed_set:
        allowed_set.append("127.0.0.1/32")

    content = []
    content.append(f"# Managed by dante-ui\nlogoutput: syslog\n")
    content.append(f"internal: {iface} port = {DEFAULT_PORT}\nexternal: {iface}\n")
    content.append("socksmethod: username\nclientmethod: none\n")
    content.append("user.privileged: root\nuser.unprivileged: nobody\n")
    for subnet in allowed_set:
        subnet = subnet.strip()
        if not subnet:
            continue
        content.append("client pass {\n   from: %s to: 0.0.0.0/0\n   log: connect disconnect\n}\n" % subnet)
    content.append("client block {\n   from: 0.0.0.0/0 to: 0.0.0.0/0\n   log: connect disconnect\n}\n")
    for subnet in allowed_set:
        subnet = subnet.strip()
        if not subnet:
            continue
        content.append("socks pass {\n   from: %s to: 0.0.0.0/0\n   command: bind connect udpassociate\n   log: connect disconnect\n}\n" % subnet)
    content.append("socks block {\n   from: 0.0.0.0/0 to: 0.0.0.0/0\n   log: connect disconnect\n}\n")
    tmp_path = "/tmp/danted.conf.new"
    with open(tmp_path, "w") as f:
        f.write("".join(content))
    run(f"[ -f {CONF} ] && cp -a {CONF} {CONF}.bak.$(date +%s) || true", require_root=True, sudo_password=sudo_password)
    res = run(f"mv {tmp_path} {CONF} && chown root:root {CONF} && chmod 644 {CONF}", require_root=True, sudo_password=sudo_password)
    return res.returncode == 0, res.stderr


def restart_danted(sudo_password=None):
    return run("systemctl restart danted && systemctl is-active --quiet danted", require_root=True, sudo_password=sudo_password).returncode == 0


def detect_public_ip():
    for cmd in [
        "curl -4 -sS --max-time 5 https://ifconfig.me",
        "curl -4 -sS --max-time 5 https://icanhazip.com",
        "curl -4 -sS --max-time 5 https://ipinfo.io/ip",
        "curl -4 -sS --max-time 5 http://ipecho.net/plain",
    ]:
        cp = run(cmd)
        ip = cp.stdout.strip()
        if re.match(r"^([0-9]{1,3}\.){3}[0-9]{1,3}$", ip or ""):
            return ip
    return ""


def test_user(username: str, password: str, host: str, port: int):
    if not cmd_exists("curl"):
        return False, "curl not installed"
    # Retry a few times to handle race after service restart
    attempts = 3
    last_out = ""
    for i in range(attempts):
        cmd = f"curl -sS --max-time 15 -x 'socks5h://{username}:{password}@{host}:{port}' https://api.ipify.org"
        cp = run(cmd)
        out = (cp.stdout or '').strip() or (cp.stderr or '').strip()
        last_out = out
        if cp.returncode == 0 and re.match(r"^([0-9]{1,3}\.){3}[0-9]{1,3}$", out or ''):
            return True, out
        time.sleep(1)
    return False, last_out


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    """Wait until a TCP port is accepting connections."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False

# --------- Auth ---------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = request.form.get('username', '')
        p = request.form.get('password', '')
        if u == ADMIN_USER and p == ADMIN_PASS:
            session['auth'] = True
            return redirect(url_for('index'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')


def require_auth():
    if not session.get('auth'):
        return redirect(url_for('login'))
    return None

# --------- Routes ---------

@app.get('/logout')
def logout():
    session.pop('auth', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    ra = require_auth()
    if ra: return ra
    
    # Load state entries (subnet-user-password mappings)
    entries = load_state()
    
    # Don't merge old config entries - only show state entries
    # This prevents old danted.conf entries from appearing in the UI
    
    return render_template('index.html', entries=entries)


@app.post('/save')
def save():
    ra = require_auth()
    if ra: return ra

    # Get sudo password
    sudo_password = request.form.get('sudo_password', '').strip()
    if not sudo_password:
        flash('Sudo password is required for system operations', 'error')
        return redirect(url_for('index'))

    # Collect all entries from form
    entries = []
    for i in range(1, 101):
        subnet = request.form.get(f'row[{i}][ip]', '').strip()
        user = request.form.get(f'row[{i}][user]', '').strip()
        password = request.form.get(f'row[{i}][pass]', '').strip()
        if any([subnet, user, password]):
            entries.append({'subnet': subnet, 'user': user, 'password': password})

    # Save state
    if not save_state(entries, sudo_password):
        flash('Failed to save state file', 'error')
        return redirect(url_for('index'))

    # Extract unique subnets for danted.conf
    allowed = []
    for entry in entries:
        if entry['subnet'] and entry['subnet'] not in allowed:
            allowed.append(entry['subnet'])

    # Create/update system users
    for entry in entries:
        if entry['user'] and entry['password']:
            ensure_user(entry['user'], entry['password'], sudo_password)

    # Write danted config
    ok, err = write_danted_conf(allowed, sudo_password)
    if not ok:
        flash(f'Failed to write config: {err}', 'error')
        return redirect(url_for('index'))

    # Restart service
    if not restart_danted(sudo_password):
        flash('Failed to restart danted service', 'error')
        return redirect(url_for('index'))

    # Test connectivity for each user
    iface = detect_iface()
    host_ip = primary_ip_for_iface(iface) or detect_public_ip() or '127.0.0.1'
    # Wait briefly for port to be ready to accept connections
    wait_for_port(host_ip, DEFAULT_PORT, timeout=10.0)
    results = []
    for entry in entries:
        if entry['user'] and entry['password']:
            ok, out = test_user(entry['user'], entry['password'], host_ip, DEFAULT_PORT)
            # Build real and display commands
            u_enc = urlquote(entry['user'])
            p_enc = urlquote(entry['password'])
            real_cmd = f"curl -sS --max-time 20 -x 'socks5h://{u_enc}:{p_enc}@{host_ip}:{DEFAULT_PORT}' https://api.ipify.org"
            display_cmd = f"curl -sS --max-time 20 -x 'socks5h://{entry['user']}:PASSWORD@{host_ip}:{DEFAULT_PORT}' https://api.ipify.org"
            results.append({
                "user": entry['user'],
                "password": entry['password'],
                "subnet": entry['subnet'],
                "ok": ok,
                "output": out,
                "cmd": real_cmd,
                "cmd_display": display_cmd
            })

    flash(f'Successfully deployed {len(entries)} entries and tested {len(results)} users', 'success')
    return render_template('result.html', results=results, host=host_ip, port=DEFAULT_PORT)


@app.post('/delete-user')
def delete_user_route():
    ra = require_auth()
    if ra: return ra
    username = request.form.get('username', '').strip()
    sudo_password = request.form.get('sudo_password', '').strip()
    if username and sudo_password:
        delete_user(username, sudo_password)
        flash(f"User {username} deleted from {MANAGED_GROUP}", 'info')
    return redirect(url_for('index'))


@app.get('/api/state')
def api_state():
    conf_text = read_conf()
    return jsonify({
        'config_subnets': parse_allowed_clients(conf_text),
        'managed_users': list_proxy_users(),
        'state_entries': load_state(),
    })

@app.post('/delete-entry')
def delete_entry():
    ra = require_auth()
    if ra: return ra
    
    index = request.form.get('index', type=int)
    if index is not None:
        entries = load_state()
        if 0 <= index < len(entries):
            deleted = entries.pop(index)
            save_state(entries)
            flash(f'Deleted entry: {deleted["subnet"]}', 'info')
        else:
            flash('Invalid entry index', 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Ensure loopback alias note: run `sudo ip addr add 127.0.0.50/32 dev lo` if needed
    app.run(host=APP_HOST, port=APP_PORT)
