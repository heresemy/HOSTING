import os
import sys
import subprocess
import threading
import time
import signal
import json
import shutil
import hashlib
from datetime import datetime
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify

# ============================================================
#  CONFIG
# ============================================================
APP_SECRET = "your-secret-key-here"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
FILES_DIR = "files"
PID_FILE = "bot.pid"
LOG_FILE = "bot.log"
SETTINGS_FILE = "settings.json"
REQUIREMENTS_HASH_FILE = "requirements_hash.txt"
VENV_DIR = "venv"

os.makedirs(FILES_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = APP_SECRET

# ============================================================
#  SETTINGS
# ============================================================
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {"main_file": "bot.py"}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_main_file():
    return load_settings().get("main_file", "bot.py")

def set_main_file(filename):
    settings = load_settings()
    settings["main_file"] = filename
    save_settings(settings)

def get_requirements_hash():
    req_path = os.path.join(FILES_DIR, "requirements.txt")
    if not os.path.exists(req_path):
        return None
    with open(req_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def get_stored_hash():
    hash_path = os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)
    if os.path.exists(hash_path):
        with open(hash_path, "r") as f:
            return f.read().strip()
    return None

def store_hash(hash_value):
    hash_path = os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)
    with open(hash_path, "w") as f:
        f.write(hash_value)

def get_venv_python():
    if sys.platform == "win32":
        return os.path.join(FILES_DIR, VENV_DIR, "Scripts", "python.exe")
    return os.path.join(FILES_DIR, VENV_DIR, "bin", "python")

def get_venv_pip():
    if sys.platform == "win32":
        return os.path.join(FILES_DIR, VENV_DIR, "Scripts", "pip.exe")
    return os.path.join(FILES_DIR, VENV_DIR, "bin", "pip")

# ============================================================
#  GLOBAL STATE
# ============================================================
bot_process = None
bot_log_lines = []
bot_log_lock = threading.Lock()
bot_running = False
bot_status = "Stopped"
bot_status_msg = ""
bot_start_time = None
MAX_LOG_LINES = 5000

# ============================================================
#  LOGGING
# ============================================================
def add_log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {msg}"
    with bot_log_lock:
        bot_log_lines.append(entry)
        if len(bot_log_lines) > MAX_LOG_LINES:
            bot_log_lines = bot_log_lines[-MAX_LOG_LINES:]
    log_path = os.path.join(FILES_DIR, LOG_FILE)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except:
        pass

def clear_logs():
    with bot_log_lock:
        bot_log_lines.clear()

def get_logs(limit=200):
    with bot_log_lock:
        return bot_log_lines[-limit:] if bot_log_lines else []

# ============================================================
#  VENV & REQUIREMENTS MANAGEMENT
# ============================================================
def setup_venv_and_requirements():
    """Create venv if needed, install requirements if changed."""
    venv_path = os.path.join(FILES_DIR, VENV_DIR)
    req_path = os.path.join(FILES_DIR, "requirements.txt")
    
    current_hash = get_requirements_hash()
    stored_hash = get_stored_hash()
    
    # If requirements.txt doesn't exist, remove venv and hash
    if current_hash is None:
        if os.path.exists(venv_path):
            add_log("Requirements.txt removed, deleting venv...", "WARN")
            shutil.rmtree(venv_path, ignore_errors=True)
        if os.path.exists(os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)):
            os.remove(os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE))
        return True
    
    # If hash changed or venv doesn't exist, rebuild
    if current_hash != stored_hash or not os.path.exists(venv_path):
        add_log("Requirements changed or venv missing, rebuilding...", "INFO")
        
        # Delete old venv if exists
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path, ignore_errors=True)
            add_log("Old venv deleted", "INFO")
        
        # Create new venv
        add_log("Creating virtual environment...", "INFO")
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", venv_path],
                cwd=FILES_DIR,
                check=True,
                capture_output=True,
                timeout=60
            )
            add_log("Virtual environment created", "INFO")
        except Exception as e:
            add_log(f"Failed to create venv: {e}", "ERROR")
            return False
        
        # Install requirements
        add_log("Installing requirements in venv...", "INFO")
        try:
            pip_path = get_venv_pip()
            result = subprocess.run(
                [pip_path, "install", "-r", "requirements.txt"],
                cwd=FILES_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            add_log("Requirements installed successfully", "INFO")
            for line in result.stdout.splitlines()[-10:]:
                if line.strip():
                    add_log(f"pip: {line.strip()}", "OUT")
            # Store new hash
            store_hash(current_hash)
            return True
        except subprocess.TimeoutExpired:
            add_log("Requirements installation timed out", "ERROR")
            return False
        except Exception as e:
            add_log(f"Requirements installation failed: {e}", "ERROR")
            return False
    
    add_log("Requirements already up to date", "INFO")
    return True

# ============================================================
#  BOT CONTROL
# ============================================================
def start_bot():
    global bot_process, bot_running, bot_status, bot_status_msg, bot_start_time

    if bot_running:
        add_log("Bot already running", "WARN")
        return False

    main_file = get_main_file()
    main_path = os.path.join(FILES_DIR, main_file)
    if not os.path.exists(main_path):
        add_log(f"Main file '{main_file}' not found", "ERROR")
        bot_status = "Error"
        bot_status_msg = "Main file missing"
        return False

    # Setup venv and install requirements
    if not setup_venv_and_requirements():
        bot_status = "Error"
        bot_status_msg = "Venv/requirements setup failed"
        return False

    add_log(f"Starting bot: {main_file}", "INFO")
    bot_status = "Starting"
    bot_status_msg = "Starting..."

    try:
        # Use venv python to run bot
        python_path = get_venv_python()
        if not os.path.exists(python_path):
            add_log("Venv python not found, falling back to system python", "WARN")
            python_path = sys.executable

        bot_process = subprocess.Popen(
            [python_path, main_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=FILES_DIR,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        with open(os.path.join(FILES_DIR, PID_FILE), "w") as f:
            f.write(str(bot_process.pid))

        def reader():
            while True:
                line = bot_process.stdout.readline()
                if not line:
                    break
                add_log(line.strip(), "OUT")
        threading.Thread(target=reader, daemon=True).start()

        bot_running = True
        bot_start_time = datetime.now()
        bot_status = "Running"
        bot_status_msg = "Bot running"
        add_log(f"Started with PID {bot_process.pid}", "INFO")
        return True

    except Exception as e:
        add_log(f"Start failed: {e}", "ERROR")
        bot_status = "Error"
        bot_status_msg = str(e)
        bot_running = False
        return False

def stop_bot():
    global bot_process, bot_running, bot_status, bot_status_msg, bot_start_time

    if not bot_running or bot_process is None:
        add_log("Bot not running", "WARN")
        return False

    add_log("Stopping bot...", "INFO")
    bot_status = "Stopping"
    bot_status_msg = "Stopping..."

    try:
        bot_process.terminate()
        bot_process.wait(timeout=5)
    except:
        try:
            bot_process.kill()
        except:
            pass
    finally:
        bot_running = False
        bot_status = "Stopped"
        bot_status_msg = "Bot stopped"
        bot_process = None
        bot_start_time = None
        pid_path = os.path.join(FILES_DIR, PID_FILE)
        if os.path.exists(pid_path):
            os.remove(pid_path)
        add_log("Bot stopped", "INFO")
        return True

def restart_bot():
    add_log("Restarting...", "INFO")
    stop_bot()
    time.sleep(1)
    return start_bot()

def get_status():
    global bot_running, bot_status, bot_status_msg, bot_start_time, bot_process

    if bot_running and bot_process is not None:
        poll = bot_process.poll()
        if poll is not None:
            add_log(f"Bot crashed with code {poll}", "ERROR")
            bot_running = False
            bot_status = "Stopped"
            bot_status_msg = f"Crashed ({poll})"
            bot_process = None
            bot_start_time = None
            pid_path = os.path.join(FILES_DIR, PID_FILE)
            if os.path.exists(pid_path):
                os.remove(pid_path)

    uptime = None
    if bot_start_time and bot_running:
        diff = datetime.now() - bot_start_time
        secs = int(diff.total_seconds())
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        uptime = f"{h}h {m}m {s}s"

    return {
        "running": bot_running,
        "status": bot_status,
        "message": bot_status_msg,
        "uptime": uptime,
        "pid": bot_process.pid if bot_process else None,
        "main_file": get_main_file()
    }

# ============================================================
#  FILE OPERATIONS
# ============================================================
def list_files():
    files = []
    for f in os.listdir(FILES_DIR):
        if f.startswith(".") or f in [PID_FILE, LOG_FILE, REQUIREMENTS_HASH_FILE, VENV_DIR, SETTINGS_FILE]:
            continue
        path = os.path.join(FILES_DIR, f)
        if os.path.isfile(path):
            files.append({
                "name": f,
                "size": os.path.getsize(path),
                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
            })
    return sorted(files, key=lambda x: x["name"])

# ============================================================
#  ROUTES
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template_string(LOGIN_PAGE, error="Invalid credentials")
    return render_template_string(LOGIN_PAGE, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    status = get_status()
    logs = get_logs(200)
    return render_template_string(DASHBOARD_PAGE, status=status, logs=logs)

# API endpoints
@app.route("/api/status")
def api_status():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(get_status())

@app.route("/api/logs")
def api_logs():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    limit = request.args.get("limit", 200, type=int)
    return jsonify({"logs": get_logs(limit)})

@app.route("/api/start", methods=["POST"])
def api_start():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    success = start_bot()
    return jsonify({"success": success, "message": bot_status_msg})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    success = stop_bot()
    return jsonify({"success": success, "message": bot_status_msg})

@app.route("/api/restart", methods=["POST"])
def api_restart():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    success = restart_bot()
    return jsonify({"success": success, "message": bot_status_msg})

@app.route("/api/clear_logs", methods=["POST"])
def api_clear_logs():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    clear_logs()
    return jsonify({"success": True})

# File manager
@app.route("/files")
def files_page():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    files = list_files()
    return render_template_string(FILES_PAGE, files=files)

@app.route("/files/edit/<filename>", methods=["GET", "POST"])
def edit_file(filename):
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if ".." in filename or "/" in filename:
        return "Invalid path", 400
    path = os.path.join(FILES_DIR, filename)
    if request.method == "POST":
        content = request.form.get("content", "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        # If requirements.txt was edited, trigger reinstall on next start
        if filename == "requirements.txt":
            # Delete stored hash so venv rebuilds on next start
            hash_path = os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)
            if os.path.exists(hash_path):
                os.remove(hash_path)
            add_log("requirements.txt updated, venv will rebuild on next start", "INFO")
        return redirect(url_for("files_page"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        content = "Cannot read file"
    return render_template_string(EDIT_PAGE, filename=filename, content=content)

@app.route("/files/delete/<filename>", methods=["POST"])
def delete_file(filename):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid"}), 400
    path = os.path.join(FILES_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
    # If requirements.txt was deleted, remove hash so venv gets cleaned
    if filename == "requirements.txt":
        hash_path = os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)
        if os.path.exists(hash_path):
            os.remove(hash_path)
        # Delete venv too
        venv_path = os.path.join(FILES_DIR, VENV_DIR)
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path, ignore_errors=True)
        add_log("requirements.txt deleted, venv removed", "INFO")
    return jsonify({"success": True})

@app.route("/files/upload", methods=["POST"])
def upload_file():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty"}), 400
    filename = file.filename
    # Sanitize
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    file.save(os.path.join(FILES_DIR, filename))
    # If requirements.txt uploaded, trigger rebuild on next start
    if filename == "requirements.txt":
        hash_path = os.path.join(FILES_DIR, REQUIREMENTS_HASH_FILE)
        if os.path.exists(hash_path):
            os.remove(hash_path)
        add_log("requirements.txt uploaded, venv will rebuild on next start", "INFO")
    return jsonify({"success": True, "filename": filename})

# Settings page
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if request.method == "POST":
        main_file = request.form.get("main_file", "").strip()
        if main_file:
            set_main_file(main_file)
        return redirect(url_for("settings_page"))
    settings = load_settings()
    return render_template_string(SETTINGS_PAGE, settings=settings)

# ============================================================
#  HTML TEMPLATES
# ============================================================

LOGIN_PAGE = '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#16161f;padding:40px;border-radius:20px;border:1px solid #2a2a3a;width:100%;max-width:400px}
h1{color:#fff;text-align:center;margin-bottom:8px}
.sub{color:#888;text-align:center;margin-bottom:30px}
.sub span{color:#7c5cfc}
input{width:100%;padding:12px;background:#0f0f18;border:1px solid #2a2a3a;border-radius:12px;color:#fff;font-size:15px;outline:none;margin-bottom:18px}
input:focus{border-color:#7c5cfc}
button{width:100%;padding:14px;background:linear-gradient(135deg,#7c5cfc,#5c3cfc);border:none;border-radius:12px;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
button:hover{box-shadow:0 8px 30px rgba(124,92,252,0.3)}
.error{background:#ff6b6b22;border:1px solid #ff6b6b44;color:#ff6b6b;padding:10px;border-radius:8px;text-align:center;margin-bottom:16px}
.footer{color:#555;text-align:center;font-size:12px;margin-top:20px}
</style>
</head>
<body>
<div class="box">
<h1>🔐 Bot Panel</h1>
<p class="sub">Manage your bot with <span>VPS Control</span></p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="POST">
<input type="text" name="username" placeholder="Username" required>
<input type="password" name="password" placeholder="Password" required>
<button type="submit">Login</button>
</form>
<p class="footer">Default: admin / admin123</p>
</div>
</body>
</html>
'''

DASHBOARD_PAGE = '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0f0;font-family:sans-serif;padding:20px}
.container{max-width:1100px;margin:auto}
.header{display:flex;justify-content:space-between;align-items:center;padding:16px 0 20px;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;gap:12px}
.header h1{font-size:24px;background:linear-gradient(135deg,#7c5cfc,#a88cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header a{color:#ff6b6b;text-decoration:none;padding:6px 14px;border:1px solid #ff6b6b33;border-radius:8px}
.nav{display:flex;gap:4px;margin:20px 0 24px;background:#12121c;padding:6px;border-radius:14px;flex-wrap:nowrap;overflow-x:auto}
.nav a{color:#888;text-decoration:none;padding:10px 22px;border-radius:10px;font-size:14px;white-space:nowrap}
.nav a.active{background:#7c5cfc;color:#fff}
.nav a:hover:not(.active){background:#1a1a2a;color:#fff}
.status-card{background:#12121c;border:1px solid #1a1a2a;border-radius:16px;padding:24px 28px;margin-bottom:24px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}
.status-dot{width:14px;height:14px;border-radius:50%;display:inline-block;flex-shrink:0}
.status-dot.running{background:#4ade80;box-shadow:0 0 20px #4ade8044}
.status-dot.stopped{background:#f87171;box-shadow:0 0 20px #f8717144}
.status-dot.starting{background:#fbbf24}
.status-dot.error{background:#f87171}
.status-text{font-size:18px;font-weight:600}
.status-text .sub{font-size:14px;font-weight:400;color:#888}
.controls{display:flex;gap:10px;flex-wrap:wrap}
.controls button{padding:10px 24px;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;color:#fff}
.controls button:active{transform:scale(0.96)}
.btn-start{background:#4ade80;color:#0a0a0f}
.btn-start:hover{box-shadow:0 4px 24px #4ade8055}
.btn-stop{background:#f87171;color:#0a0a0f}
.btn-stop:hover{box-shadow:0 4px 24px #f8717155}
.btn-restart{background:#7c5cfc}
.btn-restart:hover{box-shadow:0 4px 24px #7c5cfc55}
.controls button:disabled{opacity:0.4;cursor:not-allowed;pointer-events:none}
.console-section{background:#0f0f18;border:1px solid #1a1a2a;border-radius:16px;overflow:hidden;margin-bottom:24px}
.console-header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;background:#12121c;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;gap:8px}
.console-header h3{font-size:15px;font-weight:600;color:#c8c8e0}
.console-header .actions{display:flex;gap:6px}
.console-header .actions button{background:none;border:none;color:#555;cursor:pointer;font-size:13px;padding:4px 12px;border-radius:6px;transition:0.2s}
.console-header .actions button:hover{background:#1a1a2a;color:#fff}
.console-header .actions .copy-btn{color:#7c5cfc}
.console-header .actions .copy-btn:hover{background:#7c5cfc22;color:#7c5cfc}
.console-body{padding:16px 20px;height:500px;overflow-y:auto;font-family:monospace;font-size:13px;line-height:1.7;background:#08080e;color:#b0b0d0}
.console-body::-webkit-scrollbar{width:6px}
.console-body::-webkit-scrollbar-track{background:#0a0a12}
.console-body::-webkit-scrollbar-thumb{background:#2a2a3a;border-radius:4px}
.console-body .log-line{white-space:pre-wrap;word-break:break-all;border-bottom:1px solid #0f0f1a;padding:2px 0}
.console-body .log-line .time{color:#555;margin-right:10px}
.console-body .log-line .level-INFO{color:#4ade80}
.console-body .log-line .level-OUT{color:#b0b0d0}
.console-body .log-line .level-ERR{color:#f87171}
.console-body .log-line .level-WARN{color:#fbbf24}
.console-body .log-line .level-ERROR{color:#ff4444}
.console-empty{color:#444;text-align:center;padding:30px 0}
.info-row{display:flex;flex-wrap:wrap;gap:20px 40px;padding:12px 20px;background:#12121c;border-radius:12px;border:1px solid #1a1a2a;font-size:14px;color:#888}
.info-row strong{color:#e0e0f0}
@media(max-width:700px){.status-card{flex-direction:column;align-items:stretch}.controls{justify-content:center}.console-body{height:350px}}
@media(max-width:480px){.nav a{padding:8px 14px;font-size:12px}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>⚡ Bot Panel</h1><a href="{{ url_for('logout') }}">Logout</a></div>
<div class="nav"><a href="#" class="active">📊 Dashboard</a><a href="{{ url_for('files_page') }}">📁 Files</a><a href="{{ url_for('settings_page') }}">⚙️ Settings</a></div>

<div class="status-card">
<div class="left">
<span class="status-dot {{ status.status|lower }}" id="statusDot"></span>
<div>
<div class="status-text" id="statusText">{{ status.status }} <span class="sub">— <span id="statusMsg">{{ status.message }}</span></span></div>
<div id="uptimeDisplay">{% if status.uptime %}⏱ Uptime: <strong>{{ status.uptime }}</strong>{% endif %}</div>
</div>
</div>
<div class="controls">
<button class="btn-start" id="btnStart" onclick="controlBot('start')">▶ Start</button>
<button class="btn-stop" id="btnStop" onclick="controlBot('stop')">⏹ Stop</button>
<button class="btn-restart" onclick="controlBot('restart')">🔄 Restart</button>
</div>
</div>

<div class="info-row">
<span>📄 Main File: <strong id="mainFileDisplay">{{ status.main_file }}</strong></span>
<span>🆔 PID: <strong id="pidDisplay">{% if status.pid %}{{ status.pid }}{% else %}—{% endif %}</strong></span>
</div>

<div class="console-section">
<div class="console-header">
<h3>📟 Console</h3>
<div class="actions">
<button class="copy-btn" onclick="copyLogs()">📋 Copy Logs</button>
<button onclick="clearConsole()">🗑️ Clear</button>
</div>
</div>
<div class="console-body" id="console-body">
{% if logs %}
  {% for log in logs %}
  <div class="log-line">{{ log }}</div>
  {% endfor %}
{% else %}
<div class="console-empty">⏳ Console is empty — start your bot to see logs</div>
{% endif %}
</div>
</div>
</div>

<script>
let lastLogCount = 0;

function fetchStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            document.getElementById('statusDot').className = 'status-dot ' + data.status.toLowerCase();
            document.getElementById('statusText').innerHTML = data.status + ' <span class="sub">— <span id="statusMsg">' + data.message + '</span></span>';
            const uptimeEl = document.getElementById('uptimeDisplay');
            if (data.uptime) uptimeEl.innerHTML = '⏱ Uptime: <strong>' + data.uptime + '</strong>';
            else uptimeEl.innerHTML = '';
            document.getElementById('pidDisplay').textContent = data.pid || '—';
            document.getElementById('mainFileDisplay').textContent = data.main_file || 'bot.py';
            const btnStart = document.getElementById('btnStart');
            const btnStop = document.getElementById('btnStop');
            if (data.running) {
                btnStart.disabled = true;
                btnStop.disabled = false;
            } else {
                btnStart.disabled = false;
                btnStop.disabled = true;
            }
        })
        .catch(err => console.error('Status error:', err));
}

function fetchLogs() {
    fetch('/api/logs?limit=200')
        .then(r => r.json())
        .then(data => {
            const logs = data.logs || [];
            if (logs.length !== lastLogCount) {
                lastLogCount = logs.length;
                const body = document.getElementById('console-body');
                if (logs.length === 0) {
                    body.innerHTML = '<div class="console-empty">⏳ Console is empty — start your bot to see logs</div>';
                } else {
                    let html = '';
                    logs.forEach(log => {
                        html += `<div class="log-line">${escapeHtml(log)}</div>`;
                    });
                    body.innerHTML = html;
                }
                body.scrollTop = body.scrollHeight;
            }
        })
        .catch(err => console.error('Logs error:', err));
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function controlBot(action) {
    const btn = document.querySelector(`.btn-${action}`);
    if (btn && btn.disabled) {
        alert('Button is disabled');
        return;
    }
    if (btn) btn.textContent = '⏳ ...';
    fetch(`/api/${action}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (!data.success) alert('Action failed: ' + data.message);
            setTimeout(fetchStatus, 1000);
        })
        .catch(err => alert('Network error: ' + err.message))
        .finally(() => {
            if (btn) btn.textContent = action === 'start' ? '▶ Start' : action === 'stop' ? '⏹ Stop' : '🔄 Restart';
        });
}

function clearConsole() {
    fetch('/api/clear_logs', { method: 'POST' })
        .then(() => {
            document.getElementById('console-body').innerHTML = '<div class="console-empty">⏳ Console cleared</div>';
            lastLogCount = 0;
        })
        .catch(() => alert('Failed to clear logs'));
}

function copyLogs() {
    const lines = document.querySelectorAll('.console-body .log-line');
    if (!lines.length) { alert('No logs to copy'); return; }
    let text = '';
    lines.forEach(line => text += line.textContent + '\n');
    navigator.clipboard.writeText(text).then(() => alert('✅ Logs copied!'))
        .catch(() => {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            alert('✅ Logs copied!');
        });
}

fetchStatus();
fetchLogs();
setInterval(() => { fetchStatus(); fetchLogs(); }, 3000);
</script>
</body>
</html>
'''

FILES_PAGE = '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Files</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0f0;font-family:sans-serif;padding:20px}
.container{max-width:1100px;margin:auto}
.header{display:flex;justify-content:space-between;align-items:center;padding:16px 0 20px;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;gap:12px}
.header h1{font-size:22px;background:linear-gradient(135deg,#7c5cfc,#a88cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .user{display:flex;gap:16px;align-items:center}
.header .user a{color:#ff6b6b;text-decoration:none;padding:6px 14px;border:1px solid #ff6b6b33;border-radius:8px}
.nav{display:flex;gap:4px;margin:20px 0 24px;background:#12121c;padding:6px;border-radius:14px;flex-wrap:nowrap;overflow-x:auto}
.nav a{color:#888;text-decoration:none;padding:10px 22px;border-radius:10px;font-size:14px;white-space:nowrap}
.nav a.active{background:#7c5cfc;color:#fff}
.nav a:hover:not(.active){background:#1a1a2a;color:#fff}
.upload-area{display:flex;gap:12px;background:#12121c;padding:12px 20px;border-radius:12px;border:1px solid #1a1a2a;margin-bottom:20px;flex-wrap:wrap;align-items:center}
.upload-area input[type=file]{display:none}
.upload-area label{background:#7c5cfc33;color:#7c5cfc;padding:6px 14px;border-radius:6px;cursor:pointer}
.upload-area button{background:#7c5cfc;border:none;color:#fff;padding:6px 18px;border-radius:6px;cursor:pointer}
.upload-status{color:#4ade80;font-size:13px;word-break:break-all}
.file-list{background:#12121c;border:1px solid #1a1a2a;border-radius:16px;overflow:hidden}
.file-item{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;border-bottom:1px solid #0f0f1a;flex-wrap:wrap;gap:8px}
.file-item:last-child{border-bottom:none}
.file-item .name{color:#c8c8e0;flex:1;min-width:120px;word-break:break-all}
.file-item .name a{color:#c8c8e0;text-decoration:none}
.file-item .name a:hover{color:#7c5cfc}
.file-item .size{color:#555;font-size:13px;min-width:80px}
.file-item .actions{display:flex;gap:6px;flex-wrap:wrap}
.file-item .actions a,.file-item .actions button{padding:2px 12px;border-radius:4px;font-size:12px;border:none;cursor:pointer;background:#1a1a2a;color:#c8c8e0;text-decoration:none}
.file-item .actions a:hover,.file-item .actions button:hover{background:#2a2a3a}
.file-item .actions .del{color:#ff6b6b}
.file-item .actions .del:hover{background:#ff6b6b22}
.empty{text-align:center;padding:40px;color:#555}
@media(max-width:480px){.nav a{padding:8px 14px;font-size:12px}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>📁 File Manager</h1><div class="user"><span>{{ session.username }}</span><a href="{{ url_for('logout') }}">Logout</a></div></div>
<div class="nav"><a href="{{ url_for('dashboard') }}">📊 Dashboard</a><a href="#" class="active">📁 Files</a><a href="{{ url_for('settings_page') }}">⚙️ Settings</a></div>

<div class="upload-area">
<span style="color:#888;">Upload files (multiple allowed):</span>
<form id="uploadForm" method="POST" action="{{ url_for('upload_file') }}" enctype="multipart/form-data" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
<input type="file" id="fileInput" name="file" multiple>
<label for="fileInput">Choose files</label>
<button type="button" onclick="uploadFiles()">Upload</button>
<span id="uploadStatus" class="upload-status"></span>
</form>
</div>

<div class="file-list">
{% for f in files %}
<div class="file-item">
<span class="name"><a href="{{ url_for('edit_file', filename=f.name) }}">{{ f.name }}</a></span>
<span class="size">{{ f.size }} bytes</span>
<div class="actions">
<a href="{{ url_for('edit_file', filename=f.name) }}">✏️ Edit</a>
<button class="del" onclick="deleteFile('{{ f.name }}')">🗑️ Delete</button>
</div>
</div>
{% else %}
<div class="empty">📭 No files found</div>
{% endfor %}
</div>
</div>

<script>
function deleteFile(name) {
    if (!confirm('Delete "'+name+'"?')) return;
    fetch('/files/delete/'+encodeURIComponent(name), { method: 'POST' })
        .then(r => r.json())
        .then(data => { if (data.success) location.reload(); else alert('Delete failed'); })
        .catch(() => alert('Network error'));
}

async function uploadFiles() {
    const input = document.getElementById('fileInput');
    const status = document.getElementById('uploadStatus');
    const files = input.files;
    if (!files || files.length === 0) {
        status.textContent = '⚠️ Please select at least one file.';
        status.style.color = '#fbbf24';
        return;
    }
    status.textContent = '⏳ Uploading...';
    status.style.color = '#fbbf24';
    let success = 0, fail = 0;
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch('/files/upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.success) success++; else fail++;
        } catch (e) {
            fail++;
        }
        status.textContent = `⏳ ${i+1}/${files.length} ... (${success} ok, ${fail} fail)`;
    }
    if (fail === 0) {
        status.textContent = `✅ All ${files.length} files uploaded successfully!`;
        status.style.color = '#4ade80';
        setTimeout(() => location.reload(), 1200);
    } else {
        status.textContent = `⚠️ ${success} uploaded, ${fail} failed.`;
        status.style.color = '#fbbf24';
        setTimeout(() => location.reload(), 2000);
    }
}
</script>
</body>
</html>
'''

EDIT_PAGE = '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Edit {{ filename }}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0f0;font-family:sans-serif;padding:20px;height:100vh;display:flex;flex-direction:column}
.header{display:flex;justify-content:space-between;align-items:center;padding:10px 0 16px;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;gap:10px}
.header h3{font-size:18px;background:linear-gradient(135deg,#7c5cfc,#a88cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.actions{display:flex;gap:10px}
.actions button,.actions a{padding:8px 20px;border-radius:8px;border:none;font-weight:600;cursor:pointer;text-decoration:none;font-size:14px}
.btn-save{background:#4ade80;color:#0a0a0f}
.btn-save:hover{box-shadow:0 4px 20px #4ade8044}
.btn-cancel{background:#1a1a2a;color:#888}
.btn-cancel:hover{background:#2a2a3a}
.editor{flex:1;margin-top:12px}
.editor textarea{width:100%;height:100%;background:#0f0f18;border:1px solid #1a1a2a;border-radius:12px;color:#e0e0f0;font-family:monospace;font-size:14px;padding:16px;resize:none;outline:none;min-height:400px}
.editor textarea:focus{border-color:#7c5cfc}
</style>
</head>
<body>
<div class="header"><h3>✏️ {{ filename }}</h3><div class="actions"><a href="{{ url_for('files_page') }}" class="btn-cancel">Cancel</a><button class="btn-save" onclick="save()">💾 Save</button></div></div>
<div class="editor"><textarea id="content">{{ content }}</textarea></div>
<script>
function save() {
    const content = document.getElementById('content').value;
    const form = document.createElement('form');
    form.method = 'POST';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'content';
    input.value = content;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
}
document.addEventListener('keydown', e => { if ((e.ctrlKey||e.metaKey)&&e.key==='s') { e.preventDefault(); save(); } });
</script>
</body>
</html>
'''

SETTINGS_PAGE = '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Settings</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0f;color:#e0e0f0;font-family:sans-serif;padding:20px}
.container{max-width:800px;margin:auto}
.header{display:flex;justify-content:space-between;align-items:center;padding:16px 0 20px;border-bottom:1px solid #1a1a2a;flex-wrap:wrap;gap:12px}
.header h1{font-size:22px;background:linear-gradient(135deg,#7c5cfc,#a88cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .user{display:flex;gap:16px;align-items:center}
.header .user a{color:#ff6b6b;text-decoration:none;padding:6px 14px;border:1px solid #ff6b6b33;border-radius:8px}
.nav{display:flex;gap:4px;margin:20px 0 24px;background:#12121c;padding:6px;border-radius:14px;flex-wrap:nowrap;overflow-x:auto}
.nav a{color:#888;text-decoration:none;padding:10px 22px;border-radius:10px;font-size:14px;white-space:nowrap}
.nav a.active{background:#7c5cfc;color:#fff}
.nav a:hover:not(.active){background:#1a1a2a;color:#fff}
.card{background:#12121c;border:1px solid #1a1a2a;border-radius:16px;padding:24px;margin-top:20px}
.card h3{font-size:18px;margin-bottom:6px}
.card .desc{color:#555;font-size:13px;margin-bottom:18px}
.form-group{margin-bottom:18px}
.form-group label{display:block;color:#c8c8e0;font-size:13px;font-weight:500;margin-bottom:5px}
.form-group input{width:100%;padding:11px 16px;background:#0f0f18;border:1px solid #2a2a3a;border-radius:10px;color:#fff;font-size:15px;outline:none}
.form-group input:focus{border-color:#7c5cfc}
.btn-save{padding:12px 32px;background:linear-gradient(135deg,#7c5cfc,#5c3cfc);border:none;border-radius:10px;color:#fff;font-size:15px;font-weight:600;cursor:pointer;width:100%}
.btn-save:hover{box-shadow:0 4px 24px #7c5cfc55}
@media(max-width:480px){.nav a{padding:8px 14px;font-size:12px}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>⚙️ Settings</h1><div class="user"><span>{{ session.username }}</span><a href="{{ url_for('logout') }}">Logout</a></div></div>
<div class="nav"><a href="{{ url_for('dashboard') }}">📊 Dashboard</a><a href="{{ url_for('files_page') }}">📁 Files</a><a href="#" class="active">⚙️ Settings</a></div>

<div class="card">
<h3>Bot Configuration</h3>
<p class="desc">Set the main file name (e.g., main.py, bot.py). This file must exist in the 'files/' folder.</p>
<form method="POST">
<div class="form-group">
<label>Main File</label>
<input type="text" name="main_file" value="{{ settings.main_file }}" placeholder="bot.py">
</div>
<button type="submit" class="btn-save">💾 Save Settings</button>
</form>
</div>
</div>
</body>
</html>
'''

if __name__ == "__main__":
    # Cleanup old PID
    pid_path = os.path.join(FILES_DIR, PID_FILE)
    if os.path.exists(pid_path):
        try:
            with open(pid_path, "r") as f:
                pid = int(f.read())
            os.kill(pid, 0)
            os.remove(pid_path)
        except:
            os.remove(pid_path)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
