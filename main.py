from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify, render_template_string, get_flashed_messages, Response
import os, zipfile, subprocess, signal, shutil, json, sys, uuid, datetime, threading, time, re
from functools import wraps

app = Flask(__name__)
app.secret_key = "SEMYPAPAJI"

# --- Master Admin Credentials ---
ADMIN_USERNAME = "SEMY"
ADMIN_PASSWORD = "SEMY777"

UPLOAD_FOLDER = "uploads"
USER_DATA_FILE = "users.json"
PLANS_FILE = "plans.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
PAYMENTS_FILE = "payments.json"
PAYMENT_METHODS_FILE = "payment_methods.json"
STARTUP_CONFIG_FILE = "startup_configs.json"
MAX_RUNNING = 3

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
processes = {}
process_output = {}
process_locks = {}

# ---------- Data Management ----------
def load_json(filename, default=None):
    if default is None:
        default = {}
    if os.path.exists(filename):
        with open(filename, "r") as f:
            try:
                return json.load(f)
            except:
                return default
    return default

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

def load_users():
    return load_json(USER_DATA_FILE)

def save_users(users):
    save_json(USER_DATA_FILE, users)

def load_plans():
    return load_json(PLANS_FILE, {
        "starter": {
            "id": "starter",
            "name": "Starter",
            "price": 0,
            "ram": "512 MB",
            "storage": "1 GB",
            "bots": 1,
            "features": ["Community Support", "Basic Analytics"],
            "popular": False,
            "active": True
        },
        "pro": {
            "id": "pro",
            "name": "Pro",
            "price": 5,
            "ram": "2 GB",
            "storage": "10 GB",
            "bots": 5,
            "features": ["Priority Support", "Custom Domain", "Daily Backups"],
            "popular": True,
            "active": True
        },
        "enterprise": {
            "id": "enterprise",
            "name": "Enterprise",
            "price": 15,
            "ram": "8 GB",
            "storage": "50 GB",
            "bots": 999,
            "features": ["24/7 Dedicated Support", "Custom Domain + SSL", "Real-time Monitoring"],
            "popular": False,
            "active": True
        }
    })

def save_plans(plans):
    save_json(PLANS_FILE, plans)

def load_subscriptions():
    return load_json(SUBSCRIPTIONS_FILE)

def save_subscriptions(subs):
    save_json(SUBSCRIPTIONS_FILE, subs)

def load_payments():
    return load_json(PAYMENTS_FILE)

def save_payments(payments):
    save_json(PAYMENTS_FILE, payments)

def load_payment_methods():
    return load_json(PAYMENT_METHODS_FILE, {
        "bkash": {"name": "bKash", "type": "mobile", "number": "01XXXXXXXXX", "active": True, "icon": "📱", "instructions": "Send money to 01XXXXXXXXX and enter Transaction ID"},
        "nagad": {"name": "Nagad", "type": "mobile", "number": "01XXXXXXXXX", "active": True, "icon": "💰", "instructions": "Send money to 01XXXXXXXXX and enter Transaction ID"},
        "rocket": {"name": "Rocket", "type": "mobile", "number": "01XXXXXXXXX", "active": True, "icon": "🚀", "instructions": "Send money to 01XXXXXXXXX and enter Transaction ID"},
        "credit_card": {"name": "Credit Card", "type": "card", "details": "Visa/Mastercard", "active": False, "icon": "💳", "instructions": "Card payment coming soon"},
        "debit_card": {"name": "Debit Card", "type": "card", "details": "All Banks", "active": False, "icon": "🏦", "instructions": "Card payment coming soon"}
    })

def save_payment_methods(methods):
    save_json(PAYMENT_METHODS_FILE, methods)

def load_startup_configs():
    return load_json(STARTUP_CONFIG_FILE)

def save_startup_configs(configs):
    save_json(STARTUP_CONFIG_FILE, configs)

def get_user_subscription(username):
    subs = load_subscriptions()
    return subs.get(username, {
        "plan": "starter",
        "expires": None,
        "active": True,
        "purchased_at": None,
        "payment_status": "none"
    })

def get_user_limits(username):
    plan_id = get_user_subscription(username)["plan"]
    plans = load_plans()
    plan = plans.get(plan_id, plans["starter"])
    return {
        "ram": plan["ram"],
        "storage": plan["storage"],
        "max_bots": plan["bots"]
    }

def get_startup_file(user, app_name):
    configs = load_startup_configs()
    key = f"{user}/{app_name}"
    config = configs.get(key, {})
    startup_file = config.get("file", "main.py")
    return startup_file

def set_startup_file(user, app_name, filename):
    configs = load_startup_configs()
    key = f"{user}/{app_name}"
    configs[key] = {"file": filename}
    save_startup_configs(configs)

# ---------- Security ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------- Bot Logic ----------
def start_app(user, app_name):
    user_dir = os.path.join(UPLOAD_FOLDER, user)
    app_dir = os.path.join(user_dir, app_name)
    zip_path = os.path.join(app_dir, "app.zip")
    extract_dir = os.path.join(app_dir, "extracted")
    log_path = os.path.join(app_dir, "logs.txt")

    if not os.path.exists(zip_path):
        return False, "ZIP file not found"
    
    if (user, app_name) in processes and processes[(user, app_name)].poll() is None:
        return False, "Already running"

    if not os.path.exists(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_dir)
        except Exception as e:
            return False, f"ZIP extraction failed: {str(e)}"

    req_file = os.path.join(extract_dir, "requirements.txt")
    if os.path.exists(req_file) and not os.path.exists(os.path.join(extract_dir, "requirements_installed.txt")):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet", "--no-deps"], 
                          check=True, capture_output=True, timeout=60)
            with open(os.path.join(extract_dir, "requirements_installed.txt"), "w") as f:
                f.write("installed")
        except Exception as e:
            print(f"pip warning: {e}")

    startup_file = get_startup_file(user, app_name)
    found_main = None
    target_dir = extract_dir

    for root, dirs, files in os.walk(extract_dir):
        if startup_file in files:
            found_main = os.path.join(root, startup_file)
            target_dir = root
            break
    
    if not found_main:
        for root, dirs, files in os.walk(extract_dir):
            for f in files:
                if f in ["main.py", "app.py", "bot.py", "index.py", "run.py", "start.py"]:
                    found_main = os.path.join(root, f)
                    target_dir = root
                    break
            if found_main:
                break

    if not found_main:
        return False, f"No startup file found"

    try:
        log = open(log_path, "a")
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.basename(found_main)], 
            cwd=target_dir, 
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        processes[(user, app_name)] = p
        process_locks[(user, app_name)] = threading.Lock()
        process_output[(user, app_name)] = []
        
        def read_output():
            try:
                while True:
                    line = p.stdout.readline()
                    if not line:
                        break
                    with process_locks[(user, app_name)]:
                        process_output[(user, app_name)].append(line)
                        if len(process_output[(user, app_name)]) > 2000:
                            process_output[(user, app_name)] = process_output[(user, app_name)][-1000:]
                    try:
                        log.write(line)
                        log.flush()
                    except:
                        pass
            except:
                pass
            finally:
                try:
                    log.close()
                except:
                    pass
        
        threading.Thread(target=read_output, daemon=True).start()
        
        time.sleep(0.5)
        if p.poll() is not None and p.returncode != 0:
            return False, f"Process exited with code {p.returncode}"
        
        return True, f"Started {os.path.basename(found_main)}"
    except Exception as e:
        return False, str(e)

def stop_app(user, app_name):
    key = (user, app_name)
    p = processes.get(key)
    if p:
        try:
            p.terminate()
            try:
                p.wait(timeout=3)
            except:
                p.kill()
                p.wait()
        except:
            pass
        finally:
            processes.pop(key, None)
            process_locks.pop(key, None)
            return True
    return False

def restart_app(user, app_name):
    stop_app(user, app_name)
    time.sleep(0.5)
    return start_app(user, app_name)

def get_directory_structure(user, app_name, path=""):
    app_dir = os.path.join(UPLOAD_FOLDER, user, app_name, "extracted")
    full_path = os.path.join(app_dir, path)
    
    if not os.path.exists(full_path):
        return []
    
    items = []
    try:
        for item in sorted(os.listdir(full_path), key=lambda x: (not os.path.isdir(os.path.join(full_path, x)), x.lower())):
            item_path = os.path.join(path, item) if path else item
            full_item_path = os.path.join(full_path, item)
            is_dir = os.path.isdir(full_item_path)
            
            items.append({
                "name": item,
                "path": item_path,
                "is_dir": is_dir,
                "size": os.path.getsize(full_item_path) if not is_dir else 0,
                "modified": datetime.datetime.fromtimestamp(os.path.getmtime(full_item_path)).strftime("%Y-%m-%d %H:%M")
            })
    except Exception as e:
        print(f"Directory error: {e}")
    
    return items

# ---------- Routes ----------
@app.route("/")
def landing():
    plans = load_plans()
    return render_template_string(LANDING_TEMPLATE, plans=plans)

@app.route("/login", methods=["GET", "POST"])
def login():
    if 'username' in session and not session.get('is_admin'):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("access_key", "").strip()
        users = load_users()
        
        if u in users and users[u] == p:
            session['username'] = u
            session['is_admin'] = False
            return redirect(url_for("dashboard"))
        elif u not in users:
            users[u] = p
            save_users(users)
            
            subs = load_subscriptions()
            subs[u] = {
                "plan": "starter",
                "expires": None,
                "active": True,
                "purchased_at": datetime.datetime.now().isoformat(),
                "payment_status": "none"
            }
            save_subscriptions(subs)
            
            session['username'] = u
            session['is_admin'] = False
            return redirect(url_for("dashboard"))
        else:
            return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials")
    
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route("/dashboard")
@login_required
def dashboard():
    user = session['username']
    user_dir = os.path.join(UPLOAD_FOLDER, user)
    os.makedirs(user_dir, exist_ok=True)
    
    sub = get_user_subscription(user)
    plans = load_plans()
    current_plan = plans.get(sub["plan"], plans["starter"])
    limits = get_user_limits(user)
    
    apps = []
    app_count = 0
    if os.path.exists(user_dir):
        for name in os.listdir(user_dir):
            app_path = os.path.join(user_dir, name)
            if os.path.isdir(app_path):
                app_count += 1
                log_file = os.path.join(app_path, "logs.txt")
                log_data = ""
                if os.path.exists(log_file):
                    try:
                        with open(log_file, "r", encoding='utf-8', errors='ignore') as f:
                            log_data = f.read()[-2000:]
                    except Exception as e:
                        log_data = f"Error: {str(e)}"
                
                key = (user, name)
                if key in process_output:
                    try:
                        with process_locks.get(key, threading.Lock()):
                            live_output = ''.join(process_output[key][-100:])
                            if live_output:
                                log_data = live_output
                    except:
                        pass
                
                startup_file = get_startup_file(user, name)
                
                apps.append({
                    "name": name,
                    "running": key in processes and processes[key].poll() is None,
                    "log": log_data,
                    "startup_file": startup_file
                })
    
    messages = get_flashed_messages(with_categories=True)
    
    return render_template_string(DASHBOARD_TEMPLATE, 
                         apps=apps, 
                         current_plan=current_plan,
                         limits=limits,
                         app_count=app_count,
                         sub=sub,
                         session=session,
                         messages=messages)

@app.route("/upload", methods=["POST"])
@login_required
def upload_app():
    user = session['username']
    limits = get_user_limits(user)
    user_dir = os.path.join(UPLOAD_FOLDER, user)
    
    current_apps = len([d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))]) if os.path.exists(user_dir) else 0
    
    if current_apps >= limits["max_bots"]:
        flash(f"Upgrade required! Max {limits['max_bots']} bot(s) allowed.", "error")
        return redirect(url_for("dashboard"))
    
    file = request.files.get("file")
    if file and file.filename.endswith(".zip"):
        app_name = file.filename.replace(".zip", "").replace(" ", "_")
        app_dir = os.path.join(user_dir, app_name)
        
        stop_app(user, app_name)
        
        shutil.rmtree(app_dir, ignore_errors=True)
        os.makedirs(app_dir, exist_ok=True)
        file.save(os.path.join(app_dir, "app.zip"))
        
        extract_dir = os.path.join(app_dir, "extracted")
        try:
            with zipfile.ZipFile(os.path.join(app_dir, "app.zip"), 'r') as z:
                z.extractall(extract_dir)
            
            for root, dirs, files in os.walk(extract_dir):
                for f in files:
                    if f in ["main.py", "app.py", "bot.py", "index.py", "run.py", "start.py"]:
                        set_startup_file(user, app_name, f)
                        break
        except Exception as e:
            flash(f"Upload warning: {str(e)}", "warning")
            return redirect(url_for("dashboard"))
        
        flash("✅ Bot uploaded successfully!", "success")
    
    return redirect(url_for("dashboard"))

@app.route("/run/<name>")
@login_required
def run_user(name):
    user = session['username']
    key = (user, name)
    
    if key in processes and processes[key].poll() is None:
        flash("Bot already running!", "warning")
        return redirect(url_for("dashboard"))
    
    user_running = [k for k in list(processes.keys()) if k[0] == user and processes[k].poll() is None]
    
    if len(user_running) >= MAX_RUNNING:
        stop_app(user_running[0][0], user_running[0][1])
        flash(f"Stopped {user_running[0][1]} (max {MAX_RUNNING} concurrent)", "info")
    
    success, msg = start_app(user, name)
    if success:
        flash(f"✅ {msg}", "success")
    else:
        flash(f"❌ {msg}", "error")
    
    return redirect(url_for("dashboard"))

@app.route("/stop/<name>")
@login_required
def stop_user(name):
    user = session['username']
    if stop_app(user, name):
        flash("⏹️ Stopped successfully!", "success")
    else:
        flash("Not running", "info")
    return redirect(url_for("dashboard"))

@app.route("/restart/<name>")
@login_required
def restart_user(name):
    user = session['username']
    success, msg = restart_app(user, name)
    if success:
        flash(f"🔄 {msg}", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for("dashboard"))

@app.route("/delete/<name>")
@login_required
def delete_user(name):
    user = session['username']
    stop_app(user, name)
    app_dir = os.path.join(UPLOAD_FOLDER, user, name)
    if os.path.exists(app_dir):
        shutil.rmtree(app_dir, ignore_errors=True)
        configs = load_startup_configs()
        key = f"{user}/{name}"
        if key in configs:
            del configs[key]
            save_startup_configs(configs)
        flash("🗑️ Deleted successfully!", "success")
    return redirect(url_for("dashboard"))

@app.route("/console/<name>")
@login_required
def console(name):
    user = session['username']
    key = (user, name)
    
    output = ""
    if key in process_output:
        try:
            with process_locks.get(key, threading.Lock()):
                output = ''.join(process_output[key][-500:])
        except:
            output = "Error reading output"
    
    is_running = key in processes and processes[key].poll() is None
    
    return render_template_string(CONSOLE_TEMPLATE, 
                                bot_name=name, 
                                output=output,
                                running=is_running)

@app.route("/console/<name>/stream")
@login_required
def console_stream(name):
    user = session['username']
    key = (user, name)
    
    def generate():
        last_len = 0
        while True:
            try:
                if key in process_output and key in process_locks:
                    with process_locks[key]:
                        current_output = process_output[key]
                        if len(current_output) > last_len:
                            new_lines = current_output[last_len:]
                            yield f"data: {json.dumps({'lines': new_lines})}\n\n"
                            last_len = len(current_output)
            except Exception as e:
                print(f"Stream error: {e}")
            time.sleep(0.1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route("/console/<name>/input", methods=["POST"])
@login_required
def console_input(name):
    user = session['username']
    key = (user, name)
    data = request.json
    command = data.get('command', '')
    
    if key in processes:
        p = processes[key]
        try:
            if p.poll() is None:
                p.stdin.write(command + '\n')
                p.stdin.flush()
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "error": "Process stopped"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    
    return jsonify({"success": False, "error": "Process not found"})

@app.route("/files/<name>")
@login_required
def file_manager(name):
    user = session['username']
    path = request.args.get('path', '')
    
    # Security check - prevent directory traversal
    path = path.replace('..', '').replace('//', '/').strip('/')
    
    items = get_directory_structure(user, name, path)
    startup_file = get_startup_file(user, name)
    
    return render_template_string(FILE_MANAGER_TEMPLATE, 
                                bot_name=name, 
                                items=items,
                                current_path=path,
                                startup_file=startup_file)

@app.route("/files/<name>/upload", methods=["POST"])
@login_required
def upload_file(name):
    user = session['username']
    path = request.form.get('path', '')
    file = request.files.get('file')
    
    # Security check
    path = path.replace('..', '').replace('//', '/').strip('/')
    
    if file:
        app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
        full_path = os.path.join(app_dir, path, file.filename)
        
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)
            return jsonify({"success": True, "message": "Uploaded"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    
    return jsonify({"success": False, "error": "No file"})

@app.route("/files/<name>/delete", methods=["POST"])
@login_required
def delete_file(name):
    user = session['username']
    data = request.json
    filepath = data.get('path', '')
    
    # Security check
    filepath = filepath.replace('..', '').replace('//', '/').strip('/')
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    full_path = os.path.join(app_dir, filepath)
    
    # Prevent deleting outside extracted folder
    if not full_path.startswith(app_dir):
        return jsonify({"success": False, "error": "Invalid path"})
    
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/files/<name>/rename", methods=["POST"])
@login_required
def rename_file(name):
    user = session['username']
    data = request.json
    old_path = data.get('old_path', '')
    new_name = data.get('new_name', '')
    
    # Security checks
    old_path = old_path.replace('..', '').replace('//', '/').strip('/')
    new_name = new_name.replace('..', '').replace('/', '').strip()
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    old_full = os.path.join(app_dir, old_path)
    new_full = os.path.join(os.path.dirname(old_full), new_name)
    
    if not old_full.startswith(app_dir) or not new_full.startswith(app_dir):
        return jsonify({"success": False, "error": "Invalid path"})
    
    try:
        os.rename(old_full, new_full)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/files/<name>/mkdir", methods=["POST"])
@login_required
def create_folder(name):
    user = session['username']
    data = request.json
    path = data.get('path', '')
    folder_name = data.get('name', '')
    
    # Security checks
    path = path.replace('..', '').replace('//', '/').strip('/')
    folder_name = folder_name.replace('..', '').replace('/', '').strip()
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    full_path = os.path.join(app_dir, path, folder_name)
    
    if not full_path.startswith(app_dir):
        return jsonify({"success": False, "error": "Invalid path"})
    
    try:
        os.makedirs(full_path, exist_ok=True)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/edit/<name>")
@login_required
def edit_files_redirect(name):
    return redirect(url_for('file_manager', name=name))

@app.route("/files/<name>/edit")
@login_required
def edit_file_page(name):
    user = session['username']
    filepath = request.args.get('path', '')
    
    # Security check
    filepath = filepath.replace('..', '').replace('//', '/').strip('/')
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    full_path = os.path.join(app_dir, filepath)
    
    if not full_path.startswith(app_dir):
        return "Invalid path", 403
    
    content = ""
    if os.path.exists(full_path) and os.path.isfile(full_path):
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            content = f"Error: {str(e)}"
    
    return render_template_string(EDIT_FILE_TEMPLATE, 
                                bot_name=name, 
                                filepath=filepath,
                                content=content)

@app.route("/files/<name>/save", methods=["POST"])
@login_required
def save_file_route(name):
    user = session['username']
    data = request.json
    filepath = data.get('path', '')
    content = data.get('content', '')
    
    # Security check
    filepath = filepath.replace('..', '').replace('//', '/').strip('/')
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    full_path = os.path.join(app_dir, filepath)
    
    if not full_path.startswith(app_dir):
        return jsonify({"success": False, "error": "Invalid path"})
    
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": "Saved"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/startup/<name>", methods=["GET", "POST"])
@login_required
def startup_config(name):
    user = session['username']
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    
    py_files = []
    if os.path.exists(app_dir):
        for root, dirs, files in os.walk(app_dir):
            for f in files:
                if f.endswith('.py'):
                    rel_path = os.path.relpath(os.path.join(root, f), app_dir)
                    py_files.append(rel_path)
    
    if request.method == "POST":
        selected_file = request.form.get('startup_file')
        if selected_file:
            set_startup_file(user, name, selected_file)
            flash(f"✅ Startup: {selected_file}", "success")
        return redirect(url_for('dashboard'))
    
    current_startup = get_startup_file(user, name)
    return render_template_string(STARTUP_TEMPLATE, 
                                bot_name=name, 
                                files=py_files,
                                current=current_startup)

@app.route("/pricing")
@login_required
def pricing():
    plans = load_plans()
    user_sub = get_user_subscription(session['username'])
    payment_methods = {k: v for k, v in load_payment_methods().items() if v.get('active')}
    
    # Get pending payments for this user
    payments = load_payments()
    user_pending = [p for p in payments.values() if p.get('user') == session['username'] and p.get('status') == 'pending']
    
    return render_template_string(PRICING_TEMPLATE, 
                                plans=plans, 
                                current_plan=user_sub["plan"],
                                payment_methods=payment_methods,
                                pending_payments=user_pending)

@app.route("/purchase/<plan_id>", methods=["POST"])
@login_required
def purchase_plan(plan_id):
    user = session['username']
    plans = load_plans()
    
    if plan_id not in plans or not plans[plan_id]["active"]:
        flash("Invalid plan", "error")
        return redirect(url_for("pricing"))
    
    plan = plans[plan_id]
    
    # Free plan - immediate activation
    if plan["price"] == 0:
        subs = load_subscriptions()
        subs[user] = {
            "plan": plan_id,
            "expires": None,
            "active": True,
            "purchased_at": datetime.datetime.now().isoformat(),
            "payment_status": "completed"
        }
        save_subscriptions(subs)
        flash(f"✅ Subscribed to {plan['name']}!", "success")
        return redirect(url_for("dashboard"))
    
    # Paid plan - require payment proof
    payment_method = request.form.get('payment_method', '')
    transaction_id = request.form.get('transaction_id', '').strip()
    
    if not payment_method:
        flash("Please select payment method", "error")
        return redirect(url_for("pricing"))
    
    if not transaction_id:
        flash("Please enter Transaction ID", "error")
        return redirect(url_for("pricing"))
    
    # Check if transaction ID already used
    payments = load_payments()
    for p in payments.values():
        if p.get('transaction_id') == transaction_id and p.get('status') != 'rejected':
            flash("Transaction ID already used!", "error")
            return redirect(url_for("pricing"))
    
    payment_id = str(uuid.uuid4())
    
    payments[payment_id] = {
        "id": payment_id,
        "user": user,
        "plan": plan_id,
        "amount": plan["price"],
        "status": "pending",
        "payment_method": payment_method,
        "transaction_id": transaction_id,
        "created_at": datetime.datetime.now().isoformat(),
        "notes": ""
    }
    save_payments(payments)
    
    # Update user subscription status to pending
    subs = load_subscriptions()
    subs[user] = {
        "plan": plan_id,
        "expires": None,
        "active": False,  # Not active until approved
        "purchased_at": datetime.datetime.now().isoformat(),
        "payment_status": "pending",
        "payment_id": payment_id
    }
    save_subscriptions(subs)
    
    flash(f"⏳ Payment submitted! ID: {payment_id[:8]}. Wait for admin approval.", "info")
    return redirect(url_for("dashboard"))

@app.route("/my-payments")
@login_required
def my_payments():
    user = session['username']
    payments = load_payments()
    user_payments = {k: v for k, v in payments.items() if v.get('user') == user}
    return render_template_string(MY_PAYMENTS_TEMPLATE, payments=user_payments)

# ---------- Admin Routes ----------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get('is_admin'):
        return redirect(url_for("admin_dashboard"))
    
    if request.method == "POST":
        u = request.form.get("u", "").strip()
        p = request.form.get("p", "").strip()
        
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session.clear()
            session['username'] = ADMIN_USERNAME
            session['is_admin'] = True
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template_string(ADMIN_LOGIN_TEMPLATE, error="Invalid credentials")
    
    return render_template_string(ADMIN_LOGIN_TEMPLATE, error=None)

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    users = load_users()
    subs = load_subscriptions()
    payments = load_payments()
    plans = load_plans()
    
    total_users = len(users)
    total_revenue = sum(p["amount"] for p in payments.values() if p["status"] == "completed")
    active_subs = sum(1 for s in subs.values() if s.get("active"))
    pending_payments = sum(1 for p in payments.values() if p["status"] == "pending")
    
    bots_list = []
    for u_name in os.listdir(UPLOAD_FOLDER):
        u_path = os.path.join(UPLOAD_FOLDER, u_name)
        if os.path.isdir(u_path):
            for a_name in os.listdir(u_path):
                if os.path.isdir(os.path.join(u_path, a_name)):
                    is_running = (u_name, a_name) in processes and processes[(u_name, a_name)].poll() is None
                    user_plan = subs.get(u_name, {}).get('plan', 'starter')
                    plan_name = plans.get(user_plan, {}).get('name', 'Starter')
                    bots_list.append({
                        'user': u_name,
                        'name': a_name,
                        'running': is_running,
                        'plan': plan_name
                    })
    
    messages = get_flashed_messages(with_categories=True)
    
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE,
                         users=users,
                         subs=subs,
                         payments=payments,
                         plans=plans,
                         bots_list=bots_list,
                         stats={
                             "total_users": total_users,
                             "total_revenue": total_revenue,
                             "active_subs": active_subs,
                             "pending_payments": pending_payments
                         },
                         messages=messages)

@app.route("/admin/plans", methods=["GET", "POST"])
@admin_required
def admin_plans():
    plans = load_plans()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "create":
            plan_id = request.form.get("plan_id", "").lower().replace(" ", "_")
            if plan_id and plan_id not in plans:
                plans[plan_id] = {
                    "id": plan_id,
                    "name": request.form.get("name"),
                    "price": float(request.form.get("price", 0)),
                    "ram": request.form.get("ram"),
                    "storage": request.form.get("storage"),
                    "bots": int(request.form.get("bots", 1)),
                    "features": [f.strip() for f in request.form.get("features", "").split(",") if f.strip()],
                    "popular": request.form.get("popular") == "on",
                    "active": True
                }
                save_plans(plans)
                flash("✅ Plan created!", "success")
        
        elif action == "toggle":
            plan_id = request.form.get("plan_id")
            if plan_id in plans:
                plans[plan_id]["active"] = not plans[plan_id].get("active", True)
                save_plans(plans)
                flash("✅ Plan updated!", "success")
        
        elif action == "edit":
            plan_id = request.form.get("plan_id")
            if plan_id in plans:
                plans[plan_id]["name"] = request.form.get("name")
                plans[plan_id]["price"] = float(request.form.get("price", 0))
                plans[plan_id]["ram"] = request.form.get("ram")
                plans[plan_id]["storage"] = request.form.get("storage")
                plans[plan_id]["bots"] = int(request.form.get("bots", 1))
                plans[plan_id]["features"] = [f.strip() for f in request.form.get("features", "").split(",") if f.strip()]
                plans[plan_id]["popular"] = request.form.get("popular") == "on"
                save_plans(plans)
                flash("✅ Plan updated!", "success")
    
    messages = get_flashed_messages(with_categories=True)
    return render_template_string(ADMIN_PLANS_TEMPLATE, plans=plans, messages=messages)

@app.route("/admin/payment-methods", methods=["GET", "POST"])
@admin_required
def admin_payment_methods():
    methods = load_payment_methods()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add":
            method_id = request.form.get("method_id", "").lower().replace(" ", "_")
            if method_id and method_id not in methods:
                methods[method_id] = {
                    "name": request.form.get("name"),
                    "type": request.form.get("type"),
                    "number": request.form.get("number", ""),
                    "details": request.form.get("details", ""),
                    "instructions": request.form.get("instructions", ""),
                    "active": True,
                    "icon": request.form.get("icon", "💳")
                }
                save_payment_methods(methods)
                flash("✅ Payment method added!", "success")
        
        elif action == "toggle":
            method_id = request.form.get("method_id")
            if method_id in methods:
                methods[method_id]["active"] = not methods[method_id].get("active", True)
                save_payment_methods(methods)
                flash("✅ Updated!", "success")
        
        elif action == "edit":
            method_id = request.form.get("method_id")
            if method_id in methods:
                methods[method_id]["name"] = request.form.get("name")
                methods[method_id]["number"] = request.form.get("number", "")
                methods[method_id]["details"] = request.form.get("details", "")
                methods[method_id]["instructions"] = request.form.get("instructions", "")
                methods[method_id]["icon"] = request.form.get("icon", "💳")
                save_payment_methods(methods)
                flash("✅ Updated!", "success")
    
    messages = get_flashed_messages(with_categories=True)
    return render_template_string(ADMIN_PAYMENT_METHODS_TEMPLATE, methods=methods, messages=messages)

@app.route("/admin/users")
@admin_required
def admin_users():
    users = load_users()
    subs = load_subscriptions()
    plans = load_plans()
    return render_template_string(ADMIN_USERS_TEMPLATE, users=users, subs=subs, plans=plans)

@app.route("/admin/user/<username>/setplan", methods=["POST"])
@admin_required
def admin_set_user_plan(username):
    plan_id = request.form.get("plan_id")
    plans = load_plans()
    
    if plan_id in plans:
        subs = load_subscriptions()
        subs[username] = {
            "plan": plan_id,
            "expires": None,
            "active": True,
            "purchased_at": datetime.datetime.now().isoformat(),
            "payment_status": "manual",
            "manual_override": True
        }
        save_subscriptions(subs)
        flash(f"✅ Updated {username} to {plans[plan_id]['name']}", "success")
    
    return redirect(url_for("admin_users"))

@app.route("/admin/payments")
@admin_required
def admin_payments():
    payments = load_payments()
    users = load_users()
    plans = load_plans()
    return render_template_string(ADMIN_PAYMENTS_TEMPLATE, payments=payments, users=users, plans=plans)

@app.route("/admin/payment/<payment_id>/approve", methods=["POST"])
@admin_required
def approve_payment(payment_id):
    payments = load_payments()
    if payment_id in payments:
        payments[payment_id]["status"] = "completed"
        payments[payment_id]["approved_at"] = datetime.datetime.now().isoformat()
        payments[payment_id]["approved_by"] = session['username']
        save_payments(payments)
        
        # Activate user subscription
        user = payments[payment_id]["user"]
        plan_id = payments[payment_id]["plan"]
        subs = load_subscriptions()
        subs[user] = {
            "plan": plan_id,
            "expires": (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat(),
            "active": True,
            "purchased_at": datetime.datetime.now().isoformat(),
            "payment_status": "completed",
            "payment_id": payment_id
        }
        save_subscriptions(subs)
        flash("✅ Payment approved! User plan activated.", "success")
    
    return redirect(url_for("admin_payments"))

@app.route("/admin/payment/<payment_id>/reject", methods=["POST"])
@admin_required
def reject_payment(payment_id):
    payments = load_payments()
    if payment_id in payments:
        payments[payment_id]["status"] = "rejected"
        payments[payment_id]["rejected_at"] = datetime.datetime.now().isoformat()
        payments[payment_id]["rejected_by"] = session['username']
        payments[payment_id]["reject_reason"] = request.form.get('reason', '')
        save_payments(payments)
        
        # Revert user to starter
        user = payments[payment_id]["user"]
        subs = load_subscriptions()
        subs[user] = {
            "plan": "starter",
            "expires": None,
            "active": True,
            "purchased_at": datetime.datetime.now().isoformat(),
            "payment_status": "rejected"
        }
        save_subscriptions(subs)
        flash("❌ Payment rejected.", "info")
    
    return redirect(url_for("admin_payments"))

@app.route("/admin/download/<user>/<name>")
@admin_required
def admin_download(user, name):
    path = os.path.join(UPLOAD_FOLDER, user, name, "app.zip")
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "Not Found", 404

@app.route("/admin/run/<user>/<name>")
@admin_required
def admin_run(user, name):
    success, msg = start_app(user, name)
    if success:
        flash(f"✅ Started {user}/{name}", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/stop/<user>/<name>")
@admin_required
def admin_stop(user, name):
    if stop_app(user, name):
        flash(f"⏹️ Stopped {user}/{name}", "success")
    else:
        flash(f"Not running", "info")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/restart/<user>/<name>")
@admin_required
def admin_restart(user, name):
    success, msg = restart_app(user, name)
    if success:
        flash(f"🔄 Restarted {user}/{name}", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete/<user>/<name>")
@admin_required
def admin_delete(user, name):
    stop_app(user, name)
    shutil.rmtree(os.path.join(UPLOAD_FOLDER, user, name), ignore_errors=True)
    flash(f"🗑️ Deleted {user}/{name}", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))

# ---------- HTML TEMPLATES ----------
LANDING_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LAM CODEX OFCL HOSTING PANEL</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            background: #0a0a0a;
            color: #ffffff;
            overflow-x: hidden;
        }
        nav {
            position: fixed;
            top: 0;
            width: 100%;
            padding: 20px 50px;
            background: rgba(10, 10, 10, 0.9);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            z-index: 1000;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .logo {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: rgbText 3s infinite alternate;
        }
        @keyframes rgbText {
            0% { filter: hue-rotate(0deg); }
            100% { filter: hue-rotate(360deg); }
        }
        .nav-links {
            display: flex;
            gap: 30px;
            align-items: center;
        }
        .nav-links a {
            color: #a0a0a0;
            text-decoration: none;
            font-weight: 500;
            transition: color 0.3s;
        }
        .nav-links a:hover { color: #00ffcc; }
        .login-btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000 !important;
            padding: 12px 30px;
            border-radius: 25px;
            font-weight: 700;
            transition: all 0.3s;
        }
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0, 255, 204, 0.4);
        }
        .hero {
            margin-top: 80px;
            padding: 120px 50px;
            text-align: center;
            background: radial-gradient(ellipse at top, rgba(0, 255, 204, 0.15), transparent 50%),
                        radial-gradient(ellipse at bottom, rgba(0, 212, 255, 0.15), transparent 50%);
        }
        .hero h1 {
            font-size: 72px;
            font-weight: 800;
            margin-bottom: 20px;
            background: linear-gradient(135deg, #ffffff, #00ffcc, #00d4ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            line-height: 1.1;
        }
        .hero p {
            font-size: 20px;
            color: #a0a0a0;
            max-width: 600px;
            margin: 0 auto 40px;
            line-height: 1.6;
        }
        .cta-buttons {
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-bottom: 60px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            background-size: 200% 200%;
            animation: rgbShift 3s ease infinite;
            color: #000;
            padding: 18px 50px;
            border-radius: 30px;
            text-decoration: none;
            font-weight: 800;
            font-size: 18px;
            transition: all 0.3s;
            box-shadow: 0 10px 30px rgba(0, 255, 204, 0.3);
        }
        @keyframes rgbShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        .btn-primary:hover {
            transform: translateY(-3px);
            box-shadow: 0 20px 40px rgba(0, 255, 204, 0.5);
        }
        .stats {
            display: flex;
            justify-content: center;
            gap: 80px;
            flex-wrap: wrap;
            margin-top: 40px;
        }
        .stat-number {
            font-size: 56px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .stat-label {
            color: #666;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: 10px;
        }
        .pricing-section {
            padding: 100px 50px;
            background: radial-gradient(ellipse at center, rgba(0, 255, 204, 0.05), transparent 70%);
        }
        .section-title {
            text-align: center;
            font-size: 48px;
            font-weight: 800;
            margin-bottom: 60px;
        }
        .pricing-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
            max-width: 1200px;
            margin: 0 auto;
        }
        .pricing-card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 25px;
            padding: 50px;
            position: relative;
            transition: all 0.3s;
        }
        .pricing-card:hover { 
            transform: scale(1.03); 
            box-shadow: 0 0 40px rgba(0, 255, 204, 0.1);
        }
        .pricing-card.popular {
            border-color: #00ffcc;
            background: rgba(0, 255, 204, 0.05);
        }
        .popular-badge {
            position: absolute;
            top: -15px;
            right: 30px;
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 800;
        }
        .price {
            font-size: 56px;
            font-weight: 800;
            margin: 30px 0;
        }
        .features-list {
            list-style: none;
            margin-bottom: 30px;
        }
        .features-list li {
            padding: 12px 0;
            color: #aaa;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        .features-list li:before {
            content: "✓";
            color: #00ffcc;
            margin-right: 10px;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <nav>
        <div class="logo">⚡ LAM CODEX OFCL</div>
        <div class="nav-links">
            <a href="#pricing">Pricing</a>
            <a href="/login" class="login-btn">Login</a>
        </div>
    </nav>

    <section class="hero">
        <h1>Host Your Bots<br>With Power</h1>
        <p>Deploy your Discord bots and applications with ultra-low latency, DDoS protection, and 24/7 uptime.</p>
        <div class="cta-buttons">
            <a href="/login" class="btn-primary">Get Started Free</a>
        </div>
        <div class="stats">
            <div class="stat-item">
                <div class="stat-number">100k+</div>
                <div class="stat-label">Active Users</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">99.9%</div>
                <div class="stat-label">Uptime</div>
            </div>
            <div class="stat-item">
                <div class="stat-number">24/7</div>
                <div class="stat-label">Support</div>
            </div>
        </div>
    </section>

    <section class="pricing-section" id="pricing">
        <h2 class="section-title">Choose Your Plan</h2>
        <div class="pricing-grid">
            {% for plan_id, plan in plans.items() if plan.active %}
            <div class="pricing-card {% if plan.popular %}popular{% endif %}">
                {% if plan.popular %}<div class="popular-badge">POPULAR</div>{% endif %}
                <h3>{{ plan.name }}</h3>
                <div class="price">${{ plan.price }}<span style="font-size:20px;color:#666">/mo</span></div>
                <ul class="features-list">
                    <li>{{ plan.ram }} RAM</li>
                    <li>{{ plan.storage }} Storage</li>
                    <li>{{ plan.bots }} Bot Slots</li>
                    {% for feature in plan.features %}
                    <li>{{ feature }}</li>
                    {% endfor %}
                </ul>
                <a href="/login" class="btn-primary" style="width: 100%; display: inline-block; text-align: center;">
                    {% if plan.price == 0 %}Get Started{% else %}Upgrade{% endif %}
                </a>
            </div>
            {% endfor %}
        </div>
    </section>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>LAM CODEX OFCL HOSTING - Login</title>
    <style>
        body {
            background: #050505;
            color: white;
            text-align: center;
            padding-top: 100px;
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
        }
        .container {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 30px;
            padding: 60px;
            display: inline-block;
            animation: rgbGlow 4s infinite alternate;
            max-width: 400px;
            width: 90%;
        }
        @keyframes rgbGlow { 
            0% { box-shadow: 0 0 30px rgba(0,255,204,0.3), 0 0 60px rgba(0,212,255,0.2); } 
            50% { box-shadow: 0 0 50px rgba(0,212,255,0.4), 0 0 80px rgba(255,0,222,0.2); } 
            100% { box-shadow: 0 0 30px rgba(255,0,222,0.3), 0 0 60px rgba(0,255,204,0.2); } 
        }
        h2 {
            font-size: 32px;
            margin-bottom: 30px;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        input {
            background: rgba(255,255,255,0.1);
            border: 2px solid rgba(255,255,255,0.1);
            padding: 18px;
            margin: 12px 0;
            color: white;
            border-radius: 12px;
            width: 100%;
            font-size: 16px;
            transition: all 0.3s;
        }
        input:focus {
            border-color: #00ffcc;
            box-shadow: 0 0 20px rgba(0,255,204,0.3);
            outline: none;
        }
        button {
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            background-size: 200% 200%;
            animation: rgbShift 3s ease infinite;
            color: black;
            font-weight: 800;
            padding: 18px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            width: 100%;
            margin-top: 20px;
            font-size: 18px;
            transition: transform 0.3s;
        }
        button:hover { 
            transform: scale(1.05); 
        }
        .error {
            color: #ff4444;
            margin-bottom: 20px;
            font-weight: 600;
        }
        .hint {
            margin-top: 25px;
            color: #666;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>⚡ LAM CODEX OFCL</h2>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="post">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="access_key" placeholder="Password" required>
            <button type="submit">LOGIN</button>
        </form>
        <p class="hint">New user? Auto-register with username + password</p>
    </div>
</body>
</html>
'''

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 20px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .plan-badge {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 10px 25px;
            border-radius: 25px;
            font-weight: 800;
            font-size: 14px;
        }
        .nav-links a {
            color: #ff4444;
            text-decoration: none;
            margin-left: 25px;
            font-weight: 600;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-box {
            background: rgba(255,255,255,0.05);
            padding: 25px;
            border-radius: 15px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .stat-label { color: #666; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
        .stat-value { font-size: 28px; font-weight: 800; margin-top: 8px; color: #00ffcc; }
        .upload-section {
            background: rgba(255,255,255,0.05);
            padding: 40px;
            border-radius: 20px;
            margin-bottom: 30px;
            text-align: center;
            border: 2px dashed rgba(0,255,204,0.3);
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 15px 40px;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            font-weight: 800;
            text-decoration: none;
            display: inline-block;
            margin: 5px;
            font-size: 16px;
            transition: all 0.3s;
        }
        .btn:hover { transform: translateY(-3px); box-shadow: 0 10px 25px rgba(0,255,204,0.4); }
        .btn-large { padding: 20px 50px; font-size: 18px; }
        .btn-danger { background: linear-gradient(135deg, #ff4444, #ff8844); color: white; }
        .btn-warning { background: linear-gradient(135deg, #ffaa00, #ffcc00); color: #000; }
        .btn-success { background: linear-gradient(135deg, #00ff88, #00cc66); color: #000; }
        .btn-info { background: linear-gradient(135deg, #00d4ff, #0088ff); color: white; }
        
        .apps-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
            gap: 25px;
        }
        .app-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 20px;
            padding: 30px;
            position: relative;
        }
        .app-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .app-title { display: flex; align-items: center; gap: 15px; }
        .status {
            width: 15px;
            height: 15px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 20px currentColor; }
            50% { opacity: 0.6; box-shadow: 0 0 10px currentColor; }
        }
        .status.running { background: #00ffcc; color: #00ffcc; }
        .status.stopped { background: #ff4444; color: #ff4444; }
        
        .menu-btn {
            background: rgba(255,255,255,0.1);
            border: none;
            color: white;
            width: 45px;
            height: 45px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 24px;
            transition: all 0.3s;
        }
        .menu-btn:hover { background: rgba(0,255,204,0.2); transform: rotate(90deg); }
        
        .dropdown-menu {
            display: none;
            position: absolute;
            right: 30px;
            top: 80px;
            background: rgba(20,20,20,0.98);
            border: 1px solid rgba(0,255,204,0.3);
            border-radius: 15px;
            padding: 15px;
            min-width: 220px;
            z-index: 100;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
        }
        .dropdown-menu.show { display: block; }
        .dropdown-menu a {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 15px;
            color: white;
            text-decoration: none;
            border-radius: 10px;
            transition: all 0.3s;
            margin-bottom: 5px;
            font-weight: 500;
        }
        .dropdown-menu a:hover { background: rgba(0,255,204,0.15); color: #00ffcc; }
        
        .logs {
            background: #000;
            padding: 20px;
            border-radius: 15px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            height: 180px;
            overflow-y: auto;
            color: #00ffcc;
            border: 1px solid rgba(0,255,204,0.2);
            margin-bottom: 20px;
            line-height: 1.6;
        }
        .actions {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 12px;
        }
        .actions .btn {
            text-align: center;
            padding: 15px;
            font-size: 14px;
        }
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 25px;
            font-weight: 600;
            font-size: 16px;
        }
        .flash.error { background: rgba(255,68,68,0.2); border: 1px solid #ff4444; color: #ff4444; }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
        .flash.info { background: rgba(0,212,255,0.2); border: 1px solid #00d4ff; color: #00d4ff; }
        .flash.warning { background: rgba(255,170,0,0.2); border: 1px solid #ffaa00; color: #ffaa00; }
        .startup-info { font-size: 13px; color: #666; margin-top: 5px; }
        .pending-badge {
            background: rgba(255,170,0,0.2);
            color: #ffaa00;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 700;
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">⚡ LAM CODEX OFCL</div>
        <div>
            <span class="plan-badge">{{ current_plan.name }}</span>
            {% if sub.get('payment_status') == 'pending' %}
            <span class="pending-badge">PAYMENT PENDING</span>
            {% endif %}
            <span style="margin-left: 20px; color: #666;">{{ session.username }}</span>
            <a href="/logout" class="nav-links" style="margin-left: 20px;">Logout</a>
        </div>
    </div>

    {% if messages %}
        {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    <div class="stats">
        <div class="stat-box">
            <div class="stat-label">Plan</div>
            <div class="stat-value">{{ current_plan.name }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Bots</div>
            <div class="stat-value">{{ app_count }} / {{ limits.max_bots }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">RAM</div>
            <div class="stat-value">{{ limits.ram }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Storage</div>
            <div class="stat-value">{{ limits.storage }}</div>
        </div>
    </div>

    <div class="upload-section">
        <h3 style="margin-bottom: 20px; font-size: 24px;">📁 Upload New Bot</h3>
        <form method="post" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" accept=".zip" required style="margin-bottom: 20px; color: white; padding: 15px; width: 100%; max-width: 400px;">
            <br>
            <button type="submit" class="btn btn-large">UPLOAD ZIP FILE</button>
        </form>
    </div>

    <h3 style="margin-bottom: 25px; font-size: 28px;">🤖 Your Bots</h3>
    <div class="apps-grid">
        {% for app in apps %}
        <div class="app-card">
            <div class="app-header">
                <div class="app-title">
                    <span class="status {% if app.running %}running{% else %}stopped{% endif %}"></span>
                    <div>
                        <h4 style="font-size: 22px;">{{ app.name }}</h4>
                        <div class="startup-info">Startup: {{ app.startup_file }}</div>
                    </div>
                </div>
                <button class="menu-btn" onclick="toggleMenu('menu-{{ loop.index }}')">⋮</button>
                <div id="menu-{{ loop.index }}" class="dropdown-menu">
                    <a href="/startup/{{ app.name }}">⚙️ Startup Config</a>
                    <a href="/files/{{ app.name }}">📁 File Manager</a>
                    <a href="/files/{{ app.name }}/edit?path=">✏️ Edit Files</a>
                    <a href="/delete/{{ app.name }}" style="color: #ff4444;" onclick="return confirm('Delete {{ app.name }}?')">🗑 Delete Bot</a>
                </div>
            </div>
            <div class="logs" id="logs-{{ app.name }}">{{ app.log[-800:] }}</div>
            <div class="actions">
                {% if app.running %}
                    <a href="/stop/{{ app.name }}" class="btn btn-warning">⏹ STOP</a>
                    <a href="/restart/{{ app.name }}" class="btn btn-info">🔄 RESTART</a>
                {% else %}
                    <a href="/run/{{ app.name }}" class="btn btn-success">▶ RUN</a>
                {% endif %}
                <a href="/console/{{ app.name }}" class="btn btn-info">💻 CONSOLE</a>
            </div>
        </div>
        {% else %}
        <div style="grid-column: 1/-1; text-align: center; padding: 60px; color: #666; background: rgba(255,255,255,0.03); border-radius: 20px; border: 2px dashed rgba(255,255,255,0.1);">
            <h3 style="color: #00ffcc; margin-bottom: 15px;">No bots yet</h3>
            <p>Upload your first bot above!</p>
        </div>
        {% endfor %}
    </div>

    <div style="text-align: center; margin-top: 40px;">
        <a href="/pricing" class="btn btn-large">⭐ UPGRADE PLAN</a>
        <a href="/my-payments" class="btn btn-large" style="margin-left: 15px;">💳 MY PAYMENTS</a>
    </div>

    <script>
        function toggleMenu(id) {
            document.querySelectorAll('.dropdown-menu').forEach(m => {
                if (m.id !== id) m.classList.remove('show');
            });
            document.getElementById(id).classList.toggle('show');
        }
        document.addEventListener('click', function(e) {
            if (!e.target.matches('.menu-btn')) {
                document.querySelectorAll('.dropdown-menu').forEach(m => m.classList.remove('show'));
            }
        });
    </script>
</body>
</html>
'''

CONSOLE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Console - {{ bot_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Courier New', monospace;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            background: rgba(255,255,255,0.05);
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 22px;
            font-weight: 800;
            color: #00ffcc;
            text-shadow: 0 0 10px rgba(0,255,204,0.5);
        }
        .status {
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 700;
            margin-left: 15px;
        }
        .status.running { 
            background: rgba(0,255,204,0.2); 
            color: #00ffcc; 
            border: 1px solid #00ffcc;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { box-shadow: 0 0 10px rgba(0,255,204,0.3); }
            50% { box-shadow: 0 0 20px rgba(0,255,204,0.5); }
        }
        .status.stopped { background: rgba(255,68,68,0.2); color: #ff4444; border: 1px solid #ff4444; }
        
        .terminal-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 20px;
            gap: 15px;
        }
        #console {
            flex: 1;
            background: #000;
            border: 2px solid rgba(0,255,204,0.3);
            border-radius: 15px;
            padding: 25px;
            font-size: 14px;
            line-height: 1.7;
            overflow-y: auto;
            color: #00ffcc;
            text-shadow: 0 0 5px rgba(0,255,204,0.3);
            box-shadow: inset 0 0 50px rgba(0,255,204,0.05);
        }
        .input-line {
            display: flex;
            gap: 15px;
        }
        #commandInput {
            flex: 1;
            background: rgba(255,255,255,0.05);
            border: 2px solid rgba(0,255,204,0.3);
            color: #00ffcc;
            padding: 18px 25px;
            border-radius: 12px;
            font-family: inherit;
            font-size: 15px;
            outline: none;
        }
        #commandInput:focus {
            border-color: #00ffcc;
            box-shadow: 0 0 20px rgba(0,255,204,0.2);
        }
        #commandInput:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            border: none;
            padding: 18px 40px;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 800;
            font-size: 16px;
            transition: all 0.3s;
        }
        .btn:hover:not(:disabled) {
            transform: scale(1.05);
            box-shadow: 0 0 30px rgba(0,255,204,0.4);
        }
        .btn:disabled {
            background: #333;
            color: #666;
        }
        .back {
            color: #666;
            text-decoration: none;
            font-size: 15px;
            transition: color 0.3s;
        }
        .back:hover { color: #00ffcc; }
        .timestamp { color: #666; margin-right: 12px; font-size: 12px; }
        .command-line { color: #00d4ff; }
        .error-line { color: #ff4444; }
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center;">
            <span class="logo">💻 {{ bot_name }}</span>
            <span class="status {% if running %}running{% else %}stopped{% endif %}">
                {% if running %}● RUNNING{% else %}○ STOPPED{% endif %}
            </span>
        </div>
        <a href="/dashboard" class="back">← Back to Dashboard</a>
    </div>

    <div class="terminal-container">
        <div id="console">{{ output }}</div>
        
        <div class="input-line">
            <input type="text" id="commandInput" placeholder="Type command and press Enter..." {% if not running %}disabled{% endif %}>
            <button onclick="sendCommand()" {% if not running %}disabled{% endif %}>SEND</button>
        </div>
    </div>

    <script>
        const consoleDiv = document.getElementById('console');
        const input = document.getElementById('commandInput');
        
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
        
        {% if running %}
        const evtSource = new EventSource('/console/{{ bot_name }}/stream');
        evtSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            data.lines.forEach(line => {
                const div = document.createElement('div');
                const timestamp = new Date().toLocaleTimeString();
                
                let lineClass = '';
                if (line.includes('ERROR') || line.includes('Error')) lineClass = 'error-line';
                else if (line.startsWith('>') || line.startsWith('$')) lineClass = 'command-line';
                
                div.innerHTML = '<span class="timestamp">[' + timestamp + ']</span><span class="' + lineClass + '">' + escapeHtml(line) + '</span>';
                consoleDiv.appendChild(div);
            });
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        };
        {% endif %}
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function sendCommand() {
            const cmd = input.value.trim();
            if (!cmd) return;
            
            const div = document.createElement('div');
            div.innerHTML = '<span class="timestamp">[' + new Date().toLocaleTimeString() + ']</span><span class="command-line">> ' + escapeHtml(cmd) + '</span>';
            consoleDiv.appendChild(div);
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
            
            fetch('/console/{{ bot_name }}/input', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command: cmd})
            }).then(r => r.json()).then(data => {
                if (!data.success) {
                    const errDiv = document.createElement('div');
                    errDiv.innerHTML = '<span class="timestamp">[' + new Date().toLocaleTimeString() + ']</span><span class="error-line">Error: ' + escapeHtml(data.error || 'Unknown') + '</span>';
                    consoleDiv.appendChild(errDiv);
                    consoleDiv.scrollTop = consoleDiv.scrollHeight;
                }
            });
            
            input.value = '';
        }
        
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendCommand();
        });
        
        {% if running %}
        input.focus();
        {% endif %}
    </script>
</body>
</html>
'''

FILE_MANAGER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>File Manager - {{ bot_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 20px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            padding: 20px 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 24px;
            font-weight: 800;
            color: #aa88ff;
            text-shadow: 0 0 10px rgba(170,136,255,0.3);
        }
        .breadcrumb {
            color: #666;
            margin-bottom: 25px;
            font-size: 15px;
            padding: 15px 20px;
            background: rgba(255,255,255,0.03);
            border-radius: 10px;
        }
        .breadcrumb a {
            color: #00ffcc;
            text-decoration: none;
            font-weight: 600;
        }
        .toolbar {
            display: flex;
            gap: 15px;
            margin-bottom: 25px;
            flex-wrap: wrap;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 14px 28px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 700;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            transition: all 0.3s;
            font-size: 15px;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0,255,204,0.3); }
        .btn-secondary { background: rgba(255,255,255,0.1); color: white; }
        .btn-danger { background: linear-gradient(135deg, #ff4444, #ff8844); color: white; }
        
        .file-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }
        .file-item {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 25px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
        }
        .file-item:hover {
            border-color: #00ffcc;
            transform: translateY(-5px);
            box-shadow: 0 15px 30px rgba(0,0,0,0.3);
        }
        .file-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        .file-name {
            font-weight: 700;
            margin-bottom: 8px;
            word-break: break-all;
            font-size: 16px;
        }
        .file-info {
            font-size: 13px;
            color: #666;
        }
        .file-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        .file-actions button {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            transition: all 0.3s;
        }
        .edit-btn { background: #00d4ff; color: #000; }
        .rename-btn { background: #ffaa00; color: #000; }
        .delete-btn { background: #ff4444; color: white; }
        .file-actions button:hover { transform: scale(1.05); }
        
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0,0,0,0.9);
            justify-content: center;
            align-items: center;
            z-index: 1000;
            backdrop-filter: blur(10px);
        }
        .modal-content {
            background: #1a1a1a;
            padding: 40px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            min-width: 450px;
            max-width: 90%;
        }
        .modal h3 { margin-bottom: 25px; color: #00ffcc; font-size: 24px; }
        .modal input {
            width: 100%;
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            color: white;
            border-radius: 10px;
            margin-bottom: 25px;
            font-size: 16px;
        }
        .modal-buttons {
            display: flex;
            gap: 15px;
            justify-content: flex-end;
        }
        .back {
            color: #666;
            text-decoration: none;
            font-size: 15px;
            transition: color 0.3s;
        }
        .back:hover { color: #00ffcc; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">📁 {{ bot_name }}</div>
        <a href="/dashboard" class="back">← Back to Dashboard</a>
    </div>

    <div class="breadcrumb">
        <a href="/files/{{ bot_name }}">📂 Root</a>
        {% if current_path %} / {{ current_path }}{% endif %}
    </div>

    <div class="toolbar">
        <button class="btn" onclick="showUpload()">📤 Upload</button>
        <button class="btn btn-secondary" onclick="showNewFolder()">📁 New Folder</button>
        <button class="btn" onclick="location.href='/startup/{{ bot_name }}'">⚙️ Startup: {{ startup_file }}</button>
    </div>

    <div class="file-grid">
        {% for item in items %}
        <div class="file-item" {% if item.is_dir %}ondblclick="location.href='/files/{{ bot_name }}?path={{ (current_path + '/' + item.name) if current_path else item.name }}'"{% endif %}>
            <div class="file-icon">{% if item.is_dir %}📁{% elif item.name.endswith('.py') %}🐍{% elif item.name.endswith('.txt') %}📝{% elif item.name.endswith('.json') %}⚙️{% else %}📄{% endif %}</div>
            <div class="file-name">{{ item.name }}</div>
            <div class="file-info">{% if not item.is_dir %}{{ (item.size / 1024)|round(2) }} KB • {% endif %}{{ item.modified }}</div>
            <div class="file-actions">
                {% if not item.is_dir %}
                <button class="edit-btn" onclick="event.stopPropagation(); location.href='/files/{{ bot_name }}/edit?path={{ (current_path + '/' + item.name) if current_path else item.name }}'">✏️ Edit</button>
                {% endif %}
                <button class="rename-btn" onclick="event.stopPropagation(); showRename('{{ item.name }}', '{{ item.path }}')">✏️ Rename</button>
                <button class="delete-btn" onclick="event.stopPropagation(); deleteItem('{{ item.path }}')">🗑️ Delete</button>
            </div>
        </div>
        {% else %}
        <div style="grid-column: 1/-1; text-align: center; padding: 60px; color: #666; background: rgba(255,255,255,0.03); border-radius: 20px;">
            <h3 style="color: #00ffcc; margin-bottom: 15px;">Empty folder</h3>
            <p>Upload files or create new folder</p>
        </div>
        {% endfor %}
    </div>

    <!-- Upload Modal -->
    <div id="uploadModal" class="modal">
        <div class="modal-content">
            <h3>📤 Upload File</h3>
            <form id="uploadForm" enctype="multipart/form-data">
                <input type="file" name="file" id="fileInput" required>
                <div class="modal-buttons">
                    <button type="button" class="btn btn-secondary" onclick="closeModal('uploadModal')">Cancel</button>
                    <button type="submit" class="btn">Upload</button>
                </div>
            </form>
        </div>
    </div>

    <!-- New Folder Modal -->
    <div id="folderModal" class="modal">
        <div class="modal-content">
            <h3>📁 Create Folder</h3>
            <input type="text" id="folderName" placeholder="Folder name" required>
            <div class="modal-buttons">
                <button type="button" class="btn btn-secondary" onclick="closeModal('folderModal')">Cancel</button>
                <button type="button" class="btn" onclick="createFolder()">Create</button>
            </div>
        </div>
    </div>

    <!-- Rename Modal -->
    <div id="renameModal" class="modal">
        <div class="modal-content">
            <h3>✏️ Rename</h3>
            <input type="text" id="newName" placeholder="New name" required>
            <input type="hidden" id="oldPath">
            <div class="modal-buttons">
                <button type="button" class="btn btn-secondary" onclick="closeModal('renameModal')">Cancel</button>
                <button type="button" class="btn" onclick="renameItem()">Rename</button>
            </div>
        </div>
    </div>

    <script>
        const currentPath = '{{ current_path }}';
        const botName = '{{ bot_name }}';

        function showUpload() { document.getElementById('uploadModal').style.display = 'flex'; }
        function showNewFolder() { document.getElementById('folderModal').style.display = 'flex'; }
        function showRename(oldName, path) {
            document.getElementById('newName').value = oldName;
            document.getElementById('oldPath').value = path;
            document.getElementById('renameModal').style.display = 'flex';
        }
        function closeModal(id) { document.getElementById(id).style.display = 'none'; }

        document.getElementById('uploadForm').onsubmit = function(e) {
            e.preventDefault();
            const formData = new FormData();
            formData.append('file', document.getElementById('fileInput').files[0]);
            formData.append('path', currentPath);

            fetch(`/files/${botName}/upload`, {
                method: 'POST',
                body: formData
            }).then(r => r.json()).then(data => {
                if (data.success) location.reload();
                else alert(data.error || 'Upload failed');
            });
        };

        function createFolder() {
            const name = document.getElementById('folderName').value;
            fetch(`/files/${botName}/mkdir`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: currentPath, name: name})
            }).then(r => r.json()).then(data => {
                if (data.success) location.reload();
                else alert(data.error || 'Failed');
            });
        }

        function renameItem() {
            const oldPath = document.getElementById('oldPath').value;
            const newName = document.getElementById('newName').value;
            fetch(`/files/${botName}/rename`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({old_path: oldPath, new_name: newName})
            }).then(r => r.json()).then(data => {
                if (data.success) location.reload();
                else alert(data.error || 'Failed');
            });
        }

        function deleteItem(path) {
            if (!confirm('Delete permanently?')) return;
            fetch(`/files/${botName}/delete`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: path})
            }).then(r => r.json()).then(data => {
                if (data.success) location.reload();
                else alert(data.error || 'Failed');
            });
        }
    </script>
</body>
</html>
'''

EDIT_FILE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Edit {{ filepath }} - {{ bot_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            background: rgba(255,255,255,0.05);
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 20px;
            font-weight: 800;
            color: #aa88ff;
        }
        .filename {
            color: #00ffcc;
            font-family: monospace;
            font-size: 16px;
            margin-left: 15px;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 14px 35px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 800;
            font-size: 15px;
            transition: all 0.3s;
        }
        .btn:hover {
            transform: scale(1.05);
            box-shadow: 0 0 30px rgba(0,255,204,0.4);
        }
        #editor {
            flex: 1;
            background: #050505;
            border: none;
            padding: 25px;
            font-family: 'Courier New', monospace;
            font-size: 15px;
            color: #00ffcc;
            resize: none;
            outline: none;
            line-height: 1.8;
            tab-size: 4;
        }
        .back {
            color: #666;
            text-decoration: none;
            margin-right: 20px;
            font-size: 15px;
            transition: color 0.3s;
        }
        .back:hover { color: #00ffcc; }
        .status {
            position: fixed;
            bottom: 30px;
            right: 30px;
            padding: 18px 35px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 15px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        @keyframes slideIn {
            from { transform: translateX(100px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        .status.success {
            background: rgba(0,255,204,0.2);
            border: 1px solid #00ffcc;
            color: #00ffcc;
            display: block;
        }
        .status.error {
            background: rgba(255,68,68,0.2);
            border: 1px solid #ff4444;
            color: #ff4444;
            display: block;
        }
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center;">
            <span class="logo">✏️ Editing:</span>
            <span class="filename">{{ filepath }}</span>
        </div>
        <div>
            <a href="/files/{{ bot_name }}?path={{ filepath.rsplit('/', 1)[0] if '/' in filepath else '' }}" class="back">← Back</a>
            <button class="btn" onclick="saveFile()">💾 SAVE (Ctrl+S)</button>
        </div>
    </div>

    <textarea id="editor" spellcheck="false">{{ content }}</textarea>

    <div id="status" class="status"></div>

    <script>
        const filepath = '{{ filepath }}';
        const botName = '{{ bot_name }}';
        const editor = document.getElementById('editor');
        const statusDiv = document.getElementById('status');

        let isDirty = false;
        editor.addEventListener('input', () => { isDirty = true; });

        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                saveFile();
            }
        });

        function saveFile() {
            fetch(`/files/${botName}/save`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: filepath, content: editor.value})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    isDirty = false;
                    showStatus('✅ Saved!', 'success');
                } else {
                    showStatus('❌ ' + (data.error || 'Failed'), 'error');
                }
            })
            .catch(() => showStatus('❌ Network error', 'error'));
        }

        function showStatus(text, type) {
            statusDiv.textContent = text;
            statusDiv.className = 'status ' + type;
            setTimeout(() => statusDiv.className = 'status', 3000);
        }

        window.addEventListener('beforeunload', (e) => {
            if (isDirty) {
                e.preventDefault();
                e.returnValue = '';
            }
        });

        editor.focus();
    </script>
</body>
</html>
'''

STARTUP_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Startup Config - {{ bot_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            background: rgba(255,255,255,0.05);
            padding: 50px;
            border-radius: 25px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        h2 {
            margin-bottom: 15px;
            color: #00ffcc;
            font-size: 32px;
        }
        p {
            color: #666;
            margin-bottom: 35px;
            font-size: 16px;
            line-height: 1.6;
        }
        .file-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .file-option {
            display: flex;
            align-items: center;
            padding: 20px 25px;
            background: rgba(255,255,255,0.05);
            border: 2px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .file-option:hover {
            border-color: #00ffcc;
            background: rgba(0,255,204,0.05);
            transform: translateX(10px);
        }
        .file-option input[type="radio"] {
            margin-right: 20px;
            width: 22px;
            height: 22px;
            accent-color: #00ffcc;
        }
        .file-option.selected {
            border-color: #00ffcc;
            background: rgba(0,255,204,0.1);
        }
        .file-option label {
            flex: 1;
            cursor: pointer;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 18px 50px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 800;
            font-size: 18px;
            width: 100%;
            margin-top: 35px;
            transition: all 0.3s;
        }
        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(0,255,204,0.3);
        }
        .back {
            color: #666;
            text-decoration: none;
            font-size: 16px;
            transition: color 0.3s;
        }
        .back:hover { color: #00ffcc; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">⚙️ Startup Configuration</div>
        <a href="/files/{{ bot_name }}" class="back">← Back to File Manager</a>
    </div>

    <div class="container">
        <h2>Select Startup File</h2>
        <p>Choose which Python file will run when you click RUN:</p>
        
        <form method="post">
            <div class="file-list">
                {% for file in files %}
                <label class="file-option {% if file == current %}selected{% endif %}">
                    <input type="radio" name="startup_file" value="{{ file }}" {% if file == current %}checked{% endif %}>
                    <span>🐍 {{ file }}</span>
                </label>
                {% else %}
                <p style="color: #ff4444; text-align: center; padding: 40px;">No Python files found! Upload your bot first.</p>
                {% endfor %}
            </div>
            {% if files %}
            <button type="submit" class="btn">💾 SAVE CONFIGURATION</button>
            {% endif %}
        </form>
    </div>

    <script>
        document.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', function() {
                document.querySelectorAll('.file-option').forEach(opt => opt.classList.remove('selected'));
                this.closest('.file-option').classList.add('selected');
            });
        });
    </script>
</body>
</html>
'''

PRICING_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Pricing - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            text-align: center;
            margin-bottom: 60px;
        }
        .logo {
            font-size: 36px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .pricing-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
            max-width: 1400px;
            margin: 0 auto;
        }
        .pricing-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 30px;
            padding: 50px;
            text-align: center;
            position: relative;
            transition: all 0.3s;
        }
        .pricing-card:hover { transform: translateY(-10px); box-shadow: 0 30px 60px rgba(0,0,0,0.4); }
        .pricing-card.current {
            border-color: #00ffcc;
            box-shadow: 0 0 50px rgba(0,255,204,0.2);
        }
        .pricing-card.popular {
            border-color: #00d4ff;
            background: rgba(0,212,255,0.05);
            transform: scale(1.05);
        }
        .badge {
            position: absolute;
            top: -15px;
            left: 50%;
            transform: translateX(-50%);
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 10px 30px;
            border-radius: 25px;
            font-size: 14px;
            font-weight: 800;
        }
        h2 { margin-bottom: 15px; font-size: 32px; }
        .price {
            font-size: 64px;
            font-weight: 800;
            margin: 30px 0;
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .price span { font-size: 20px; color: #666; font-weight: 400; }
        .features {
            list-style: none;
            margin: 40px 0;
            text-align: left;
        }
        .features li {
            padding: 18px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 16px;
        }
        .features li:before {
            content: "✓";
            color: #00ffcc;
            font-size: 20px;
            font-weight: bold;
        }
        .payment-section {
            margin: 30px 0;
            padding: 30px;
            background: rgba(255,255,255,0.03);
            border-radius: 20px;
            text-align: left;
        }
        .payment-section h4 {
            margin-bottom: 20px;
            color: #00ffcc;
            font-size: 18px;
        }
        .payment-method {
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            margin-bottom: 15px;
            cursor: pointer;
            transition: all 0.3s;
            border: 2px solid transparent;
        }
        .payment-method:hover, .payment-method.selected {
            border-color: #00ffcc;
            background: rgba(0,255,204,0.1);
        }
        .payment-method input {
            width: 22px;
            height: 22px;
            accent-color: #00ffcc;
        }
        .payment-method-icon {
            font-size: 32px;
        }
        .payment-method-info {
            flex: 1;
        }
        .payment-method-name {
            font-weight: 700;
            font-size: 18px;
            margin-bottom: 5px;
        }
        .payment-method-details {
            color: #666;
            font-size: 14px;
        }
        .transaction-input {
            width: 100%;
            padding: 18px;
            background: rgba(255,255,255,0.1);
            border: 2px solid rgba(255,255,255,0.2);
            border-radius: 12px;
            color: white;
            font-size: 16px;
            margin-top: 20px;
        }
        .transaction-input:focus {
            border-color: #00ffcc;
            outline: none;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 20px 50px;
            border: none;
            border-radius: 30px;
            cursor: pointer;
            font-weight: 800;
            width: 100%;
            font-size: 18px;
            transition: all 0.3s;
            margin-top: 25px;
        }
        .btn:hover:not(:disabled) {
            transform: scale(1.05);
            box-shadow: 0 15px 40px rgba(0,255,204,0.4);
        }
        .btn:disabled {
            background: #333;
            color: #666;
            cursor: not-allowed;
        }
        .back {
            display: inline-block;
            margin-top: 50px;
            color: #666;
            text-decoration: none;
            font-size: 18px;
        }
        .back:hover { color: #00ffcc; }
        .pending-notice {
            background: rgba(255,170,0,0.1);
            border: 1px solid #ffaa00;
            color: #ffaa00;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">⚡ LAM CODEX OFCL</div>
        <h1 style="margin-top: 20px; font-size: 48px;">Upgrade Your Plan</h1>
        <p style="color: #666; margin-top: 15px; font-size: 18px;">Select plan and complete payment</p>
    </div>

    {% if pending_payments %}
    <div style="max-width: 800px; margin: 0 auto 40px;">
        {% for payment in pending_payments %}
        <div class="pending-notice">
            <strong>⏳ Pending Payment:</strong> {{ payment.plan|upper }} plan (${{ payment.amount }}) - ID: {{ payment.id[:8] }}<br>
            Transaction ID: {{ payment.transaction_id }} - Waiting for admin approval
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="pricing-grid">
        {% for plan_id, plan in plans.items() if plan.active %}
        <div class="pricing-card {% if plan_id == current_plan %}current{% endif %} {% if plan.popular %}popular{% endif %}">
            {% if plan_id == current_plan %}<div class="badge">CURRENT</div>{% endif %}
            {% if plan.popular and plan_id != current_plan %}<div class="badge">POPULAR</div>{% endif %}
            
            <h2>{{ plan.name }}</h2>
            <div class="price">${{ plan.price }}<span>/month</span></div>
            
            <ul class="features">
                <li>{{ plan.ram }} RAM</li>
                <li>{{ plan.storage }} Storage</li>
                <li>{{ plan.bots }} Bot Slot{% if plan.bots > 1 %}s{% endif %}</li>
                {% for feature in plan.features %}
                <li>{{ feature }}</li>
                {% endfor %}
            </ul>

            {% if plan.price > 0 and plan_id != current_plan %}
            <form method="post" action="/purchase/{{ plan_id }}" id="form-{{ plan_id }}">
                <div class="payment-section">
                    <h4>Select Payment Method</h4>
                    {% for method_id, method in payment_methods.items() %}
                    <label class="payment-method" onclick="selectMethod('{{ plan_id }}', '{{ method_id }}', this)">
                        <input type="radio" name="payment_method" value="{{ method_id }}" required>
                        <span class="payment-method-icon">{{ method.icon }}</span>
                        <div class="payment-method-info">
                            <div class="payment-method-name">{{ method.name }}</div>
                            <div class="payment-method-details">{{ method.number }} - {{ method.instructions }}</div>
                        </div>
                    </label>
                    {% endfor %}
                    
                    <input type="text" name="transaction_id" class="transaction-input" placeholder="Enter Transaction ID / Reference Number" required>
                </div>
                <button type="submit" class="btn">COMPLETE PAYMENT</button>
            </form>
            {% else %}
            <form method="post" action="/purchase/{{ plan_id }}">
                <button type="submit" class="btn" {% if plan_id == current_plan %}disabled{% endif %}>
                    {% if plan_id == current_plan %}Current Plan{% else %}Select Free Plan{% endif %}
                </button>
            </form>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <div style="text-align: center;">
        <a href="/dashboard" class="back">← Back to Dashboard</a>
    </div>

    <script>
        function selectMethod(planId, methodId, element) {
            document.querySelectorAll('#form-' + planId + ' .payment-method').forEach(el => el.classList.remove('selected'));
            element.classList.add('selected');
            element.querySelector('input').checked = true;
        }
    </script>
</body>
</html>
'''

MY_PAYMENTS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>My Payments - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #00ffcc, #00d4ff, #ff00de);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.02);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }
        th, td {
            padding: 25px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 14px;
        }
        .status {
            padding: 10px 25px;
            border-radius: 25px;
            font-size: 13px;
            font-weight: 800;
        }
        .status.completed { background: rgba(0,255,204,0.2); color: #00ffcc; border: 1px solid #00ffcc; }
        .status.pending { background: rgba(255,170,0,0.2); color: #ffaa00; border: 1px solid #ffaa00; }
        .status.rejected { background: rgba(255,68,68,0.2); color: #ff4444; border: 1px solid #ff4444; }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 15px 40px;
            border: none;
            border-radius: 25px;
            text-decoration: none;
            display: inline-block;
            font-weight: 800;
            margin-top: 30px;
        }
        .back {
            color: #666;
            text-decoration: none;
            font-size: 16px;
            transition: color 0.3s;
        }
        .back:hover { color: #00ffcc; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">💳 MY PAYMENTS</div>
        <a href="/dashboard" class="back">← Back to Dashboard</a>
    </div>

    <table>
        <tr>
            <th>Payment ID</th>
            <th>Plan</th>
            <th>Amount</th>
            <th>Method</th>
            <th>Transaction ID</th>
            <th>Status</th>
            <th>Date</th>
        </tr>
        {% for payment_id, payment in payments.items() %}
        <tr>
            <td><code>{{ payment_id[:12] }}...</code></td>
            <td>{{ payment.plan|upper }}</td>
            <td style="color: #00ffcc; font-weight: 800;">${{ payment.amount }}</td>
            <td>{{ payment.payment_method|upper }}</td>
            <td>{{ payment.transaction_id }}</td>
            <td><span class="status {{ payment.status }}">{{ payment.status|upper }}</span></td>
            <td>{{ payment.created_at[:10] }}</td>
        </tr>
        {% else %}
        <tr>
            <td colspan="7" style="text-align: center; color: #666; padding: 60px;">No payment history found</td>
        </tr>
        {% endfor %}
    </table>

    <div style="text-align: center;">
        <a href="/pricing" class="btn">Go to Pricing</a>
    </div>
</body>
</html>
'''

ADMIN_LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login - LAM CODEX OFCL</title>
    <style>
        body {
            background: #050505;
            color: white;
            text-align: center;
            padding-top: 100px;
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
        }
        .glow-box {
            background: rgba(0, 0, 0, 0.6);
            border: 2px solid rgba(255,255,255,0.2);
            padding: 70px;
            border-radius: 30px;
            display: inline-block;
            animation: adminGlow 3s infinite alternate;
        }
        @keyframes adminGlow { 
            0% { box-shadow: 0 0 30px rgba(255,0,222,0.4), 0 0 60px rgba(0,212,255,0.2); } 
            50% { box-shadow: 0 0 60px rgba(0,212,255,0.4), 0 0 90px rgba(255,0,222,0.3); } 
            100% { box-shadow: 0 0 90px rgba(255,0,222,0.5), 0 0 120px rgba(0,212,255,0.4); } 
        }
        h1 {
            font-size: 36px;
            margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(0,212,255,0.5);
        }
        p {
            color: #888;
            margin-bottom: 40px;
            font-size: 18px;
        }
        input { 
            padding: 18px; 
            margin: 12px; 
            width: 320px; 
            border-radius: 12px; 
            border: 2px solid rgba(255,255,255,0.2); 
            background: transparent; 
            color: #fff; 
            font-size: 18px;
            transition: all 0.3s;
        }
        input:focus {
            border-color: #00d4ff;
            box-shadow: 0 0 25px rgba(0,212,255,0.3);
            outline: none;
        }
        button { 
            padding: 20px 70px; 
            background: linear-gradient(45deg, #ff00de, #00d4ff, #ff00de); 
            background-size: 200% 200%;
            animation: rgbShift 3s ease infinite;
            border: none; 
            color: white; 
            border-radius: 12px; 
            cursor: pointer; 
            font-weight: 800; 
            margin-top: 30px;
            font-size: 20px;
            transition: transform 0.3s;
        }
        button:hover { transform: scale(1.05); }
        @keyframes rgbShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        .error {
            color: #ff4444;
            margin-top: 20px;
            font-weight: 600;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <div class="glow-box">
        <h1>🛡️ MASTER CONTROL</h1>
        <p>LAM CODEX OFCL HOSTING</p>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="post">
            <input type="text" name="u" placeholder="Username" required><br>
            <input type="password" name="p" placeholder="Password" required><br>
            <button type="submit">UNLOCK</button>
        </form>
    </div>
</body>
</html>
'''

ADMIN_DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Dashboard - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 32px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff00de, #00d4ff, #00ffcc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav a {
            color: #00d4ff;
            text-decoration: none;
            margin-left: 30px;
            font-weight: 700;
            font-size: 16px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 25px;
            margin-bottom: 50px;
        }
        .stat-card {
            background: rgba(255,255,255,0.05);
            padding: 40px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            transition: all 0.3s;
        }
        .stat-card:hover {
            border-color: #00ffcc;
            transform: translateY(-5px);
        }
        .stat-value {
            font-size: 48px;
            font-weight: 800;
            color: #00ffcc;
            text-shadow: 0 0 20px rgba(0,255,204,0.3);
        }
        .stat-label { color: #666; margin-top: 10px; font-size: 16px; text-transform: uppercase; letter-spacing: 2px; }
        .menu {
            display: flex;
            gap: 20px;
            margin-bottom: 40px;
        }
        .menu a {
            padding: 18px 35px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            font-weight: 700;
            text-decoration: none;
            color: white;
            transition: all 0.3s;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .menu a:hover {
            background: rgba(0,255,204,0.1);
            border-color: #00ffcc;
            color: #00ffcc;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.02);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }
        th, td {
            padding: 25px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 14px;
        }
        .status {
            padding: 10px 25px;
            border-radius: 25px;
            font-size: 13px;
            font-weight: 800;
        }
        .status.running { 
            background: rgba(0,255,204,0.2); 
            color: #00ffcc; 
            border: 1px solid #00ffcc;
            box-shadow: 0 0 15px rgba(0,255,204,0.2);
        }
        .status.stopped { 
            background: rgba(255,68,68,0.2); 
            color: #ff4444; 
            border: 1px solid #ff4444;
        }
        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .actions a {
            padding: 12px 25px;
            border-radius: 10px;
            font-weight: 700;
            font-size: 13px;
            text-decoration: none;
            transition: all 0.3s;
        }
        .actions a:hover { transform: scale(1.05); }
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 700;
            font-size: 16px;
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
        .flash.error { background: rgba(255,68,68,0.2); border: 1px solid #ff4444; color: #ff4444; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">🛡️ LAM CODEX OFCL PANEL</div>
        <div class="nav">
            <span style="color: #666; margin-right: 20px;">Master Admin</span>
            <a href="/logout">Logout</a>
        </div>
    </div>

    {% if messages %}
        {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    <div class="menu">
        <a href="/admin/dashboard">📊 Dashboard</a>
        <a href="/admin/plans">💎 Plans</a>
        <a href="/admin/payment-methods">💳 Payment Methods</a>
        <a href="/admin/users">👥 Users</a>
        <a href="/admin/payments">💰 Payments {% if stats.pending_payments > 0 %}({{ stats.pending_payments }} pending){% endif %}</a>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{{ stats.total_users }}</div>
            <div class="stat-label">Total Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${{ "%.2f"|format(stats.total_revenue) }}</div>
            <div class="stat-label">Revenue</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ stats.active_subs }}</div>
            <div class="stat-label">Active Subs</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" style="color: #ffaa00;">{{ stats.pending_payments }}</div>
            <div class="stat-label">Pending Payments</div>
        </div>
    </div>

    <h3 style="margin-bottom: 25px; font-size: 24px; color: #00ffcc;">All Bots</h3>
    <table>
        <tr>
            <th>User</th>
            <th>Bot</th>
            <th>Status</th>
            <th>Plan</th>
            <th>Actions</th>
        </tr>
        {% for bot in bots_list %}
        <tr>
            <td><strong>{{ bot.user }}</strong></td>
            <td>{{ bot.name }}</td>
            <td>
                {% if bot.running %}
                    <span class="status running">● RUNNING</span>
                {% else %}
                    <span class="status stopped">○ STOPPED</span>
                {% endif %}
            </td>
            <td>{{ bot.plan }}</td>
            <td class="actions">
                <a href="/admin/run/{{ bot.user }}/{{ bot.name }}" style="background: rgba(0,255,136,0.2); color: #00ff88;">▶ RUN</a>
                <a href="/admin/stop/{{ bot.user }}/{{ bot.name }}" style="background: rgba(255,170,0,0.2); color: #ffaa00;">⏹ STOP</a>
                <a href="/admin/restart/{{ bot.user }}/{{ bot.name }}" style="background: rgba(0,212,255,0.2); color: #00d4ff;">🔄 RESTART</a>
                <a href="/admin/delete/{{ bot.user }}/{{ bot.name }}" style="background: rgba(255,68,68,0.2); color: #ff4444;">🗑 DELETE</a>
                <a href="/admin/download/{{ bot.user }}/{{ bot.name }}" style="background: rgba(170,136,255,0.2); color: #aa88ff;">⬇ DOWNLOAD</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

ADMIN_PLANS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Plans - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 32px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff00de, #00d4ff, #00ffcc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav a {
            color: #00d4ff;
            text-decoration: none;
            margin-left: 30px;
            font-weight: 700;
        }
        .plans-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 50px;
        }
        .plan-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 20px;
            padding: 35px;
            position: relative;
            transition: all 0.3s;
        }
        .plan-card:hover {
            border-color: #00ffcc;
            transform: translateY(-5px);
        }
        .plan-card.inactive { opacity: 0.5; border-color: #ff4444; }
        .plan-card h3 {
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 24px;
        }
        .badge {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 6px 15px;
            border-radius: 15px;
            font-size: 12px;
            font-weight: 800;
        }
        .price {
            font-size: 42px;
            font-weight: 800;
            color: #00ffcc;
            margin-bottom: 25px;
        }
        .features {
            list-style: none;
            margin-bottom: 25px;
            font-size: 15px;
        }
        .features li {
            padding: 10px 0;
            color: #aaa;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .plan-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        .btn-small {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 700;
            font-size: 13px;
        }
        .btn-toggle { background: #00d4ff; color: #000; }
        .btn-edit { background: #ffaa00; color: #000; }
        .create-form {
            background: rgba(255,255,255,0.05);
            padding: 50px;
            border-radius: 25px;
            max-width: 800px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .form-group {
            margin-bottom: 25px;
        }
        label {
            display: block;
            margin-bottom: 10px;
            color: #00ffcc;
            font-weight: 700;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        input, select {
            width: 100%;
            padding: 18px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 12px;
            color: white;
            font-size: 16px;
        }
        input:focus {
            border-color: #00ffcc;
            outline: none;
            box-shadow: 0 0 20px rgba(0,255,204,0.2);
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 18px 50px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 800;
            font-size: 18px;
            margin-top: 20px;
            transition: all 0.3s;
        }
        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(0,255,204,0.3);
        }
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 700;
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">💎 MANAGE PLANS</div>
        <div class="nav">
            <a href="/admin/dashboard">Dashboard</a>
            <a href="/logout">Logout</a>
        </div>
    </div>

    {% if messages %}
        {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    <h3 style="margin-bottom: 30px; font-size: 24px; color: #00ffcc;">All Plans (Cannot Delete - Only Deactivate)</h3>
    <div class="plans-grid">
        {% for plan_id, plan in plans.items() %}
        <div class="plan-card {% if not plan.active %}inactive{% endif %}">
            <h3>
                {{ plan.name }}
                {% if plan.popular %}<span class="badge">POPULAR</span>{% endif %}
                {% if not plan.active %}<span class="badge" style="background: #ff4444; color: white;">INACTIVE</span>{% endif %}
            </h3>
            <div class="price">${{ plan.price }}/mo</div>
            <ul class="features">
                <li>🚀 {{ plan.ram }} RAM</li>
                <li>💾 {{ plan.storage }} Storage</li>
                <li>🤖 {{ plan.bots }} Bots</li>
                <li>✨ {{ plan.features|join(', ') }}</li>
            </ul>
            <div class="plan-actions">
                <form method="post" style="display: inline;">
                    <input type="hidden" name="action" value="toggle">
                    <input type="hidden" name="plan_id" value="{{ plan_id }}">
                    <button type="submit" class="btn-small btn-toggle">
                        {% if plan.active %}Deactivate{% else %}Activate{% endif %}
                    </button>
                </form>
                <button class="btn-small btn-edit" onclick="editPlan('{{ plan_id }}', '{{ plan.name }}', {{ plan.price }}, '{{ plan.ram }}', '{{ plan.storage }}', {{ plan.bots }}, '{{ plan.features|join(',') }}', {{ 'true' if plan.popular else 'false' }})">Edit</button>
            </div>
        </div>
        {% endfor %}
    </div>

    <h3 style="margin-bottom: 30px; font-size: 24px; color: #00ffcc;">Create New Plan</h3>
    <div class="create-form">
        <form method="post" id="planForm">
            <input type="hidden" name="action" value="create" id="formAction">
            <input type="hidden" name="plan_id" id="editPlanId">
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 25px;">
                <div class="form-group">
                    <label>Plan ID (unique)</label>
                    <input type="text" name="plan_id" id="newPlanId" placeholder="e.g., premium" required>
                </div>
                <div class="form-group">
                    <label>Plan Name</label>
                    <input type="text" name="name" id="planName" placeholder="e.g., Premium" required>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 25px;">
                <div class="form-group">
                    <label>Price ($/month)</label>
                    <input type="number" name="price" id="planPrice" step="0.01" value="0" required>
                </div>
                <div class="form-group">
                    <label>Max Bots</label>
                    <input type="number" name="bots" id="planBots" value="1" required>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 25px;">
                <div class="form-group">
                    <label>RAM</label>
                    <input type="text" name="ram" id="planRam" placeholder="e.g., 4 GB" required>
                </div>
                <div class="form-group">
                    <label>Storage</label>
                    <input type="text" name="storage" id="planStorage" placeholder="e.g., 20 GB" required>
                </div>
            </div>
            
            <div class="form-group">
                <label>Features (comma separated)</label>
                <input type="text" name="features" id="planFeatures" placeholder="Feature 1, Feature 2, Feature 3">
            </div>
            
            <label style="display: flex; align-items: center; gap: 15px; cursor: pointer; margin-bottom: 20px;">
                <input type="checkbox" name="popular" id="planPopular" style="width: auto; width: 22px; height: 22px;"> 
                <span style="font-size: 16px; text-transform: none; letter-spacing: normal;">Mark as Popular Plan</span>
            </label>
            
            <button type="submit" class="btn" id="submitBtn">✨ CREATE PLAN</button>
            <button type="button" class="btn" onclick="resetForm()" style="margin-left: 15px; background: #666; display: none;" id="cancelBtn">Cancel</button>
        </form>
    </div>

    <script>
        function editPlan(id, name, price, ram, storage, bots, features, popular) {
            document.getElementById('formAction').value = 'edit';
            document.getElementById('editPlanId').value = id;
            document.getElementById('newPlanId').value = id;
            document.getElementById('newPlanId').disabled = true;
            document.getElementById('planName').value = name;
            document.getElementById('planPrice').value = price;
            document.getElementById('planRam').value = ram;
            document.getElementById('planStorage').value = storage;
            document.getElementById('planBots').value = bots;
            document.getElementById('planFeatures').value = features;
            document.getElementById('planPopular').checked = popular;
            document.getElementById('submitBtn').textContent = '💾 UPDATE PLAN';
            document.getElementById('cancelBtn').style.display = 'inline-block';
            window.scrollTo(0, document.body.scrollHeight);
        }
        
        function resetForm() {
            document.getElementById('formAction').value = 'create';
            document.getElementById('editPlanId').value = '';
            document.getElementById('newPlanId').value = '';
            document.getElementById('newPlanId').disabled = false;
            document.getElementById('planName').value = '';
            document.getElementById('planPrice').value = '0';
            document.getElementById('planRam').value = '';
            document.getElementById('planStorage').value = '';
            document.getElementById('planBots').value = '1';
            document.getElementById('planFeatures').value = '';
            document.getElementById('planPopular').checked = false;
            document.getElementById('submitBtn').textContent = '✨ CREATE PLAN';
            document.getElementById('cancelBtn').style.display = 'none';
        }
    </script>
</body>
</html>
'''

ADMIN_PAYMENT_METHODS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Payment Methods - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 32px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff00de, #00d4ff, #00ffcc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav a {
            color: #00d4ff;
            text-decoration: none;
            margin-left: 30px;
            font-weight: 700;
        }
        .methods-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 25px;
            margin-bottom: 50px;
        }
        .method-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 25px;
            padding: 35px;
            position: relative;
            transition: all 0.3s;
        }
        .method-card:hover {
            transform: translateY(-5px);
            border-color: #00ffcc;
        }
        .method-card.inactive {
            opacity: 0.4;
            border-color: #ff4444;
        }
        .method-icon {
            font-size: 56px;
            margin-bottom: 20px;
        }
        .method-name {
            font-size: 28px;
            font-weight: 800;
            margin-bottom: 10px;
        }
        .method-type {
            color: #666;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-bottom: 20px;
        }
        .method-details {
            background: rgba(0,0,0,0.3);
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 25px;
            font-family: monospace;
            font-size: 15px;
            line-height: 1.6;
        }
        .method-actions {
            display: flex;
            gap: 15px;
        }
        .btn {
            flex: 1;
            padding: 15px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 700;
            font-size: 15px;
            transition: all 0.3s;
        }
        .btn:hover { transform: scale(1.05); }
        .btn-toggle {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
        }
        .btn-edit {
            background: #ffaa00;
            color: #000;
        }
        .create-form {
            background: rgba(255,255,255,0.05);
            padding: 50px;
            border-radius: 25px;
            max-width: 800px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .form-group {
            margin-bottom: 25px;
        }
        label {
            display: block;
            margin-bottom: 10px;
            color: #00ffcc;
            font-weight: 700;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        input, select, textarea {
            width: 100%;
            padding: 18px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 12px;
            color: white;
            font-size: 16px;
        }
        textarea {
            min-height: 100px;
            resize: vertical;
        }
        .btn-add {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 18px 50px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 800;
            font-size: 18px;
            width: 100%;
            margin-top: 20px;
        }
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 700;
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">💳 PAYMENT METHODS</div>
        <div class="nav">
            <a href="/admin/dashboard">Dashboard</a>
            <a href="/logout">Logout</a>
        </div>
    </div>

    {% if messages %}
        {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    <h3 style="margin-bottom: 30px; font-size: 24px; color: #00ffcc;">Active Methods</h3>
    <div class="methods-grid">
        {% for method_id, method in methods.items() %}
        <div class="method-card {% if not method.active %}inactive{% endif %}">
            <div class="method-icon">{{ method.icon }}</div>
            <div class="method-name">{{ method.name }}</div>
            <div class="method-type">{{ method.type }}</div>
            <div class="method-details">
                {% if method.number %}<div>📞 {{ method.number }}</div>{% endif %}
                {% if method.details %}<div>📝 {{ method.details }}</div>{% endif %}
                {% if method.instructions %}<div>💡 {{ method.instructions }}</div>{% endif %}
            </div>
            <div class="method-actions">
                <form method="post" style="flex: 1;">
                    <input type="hidden" name="action" value="toggle">
                    <input type="hidden" name="method_id" value="{{ method_id }}">
                    <button type="submit" class="btn btn-toggle">
                        {% if method.active %}Deactivate{% else %}Activate{% endif %}
                    </button>
                </form>
                <button class="btn btn-edit" onclick="editMethod('{{ method_id }}', '{{ method.name }}', '{{ method.type }}', '{{ method.number }}', '{{ method.details }}', '{{ method.instructions }}', '{{ method.icon }}')">Edit</button>
            </div>
        </div>
        {% endfor %}
    </div>

    <h3 style="margin-bottom: 30px; font-size: 24px; color: #00ffcc;">Add/Edit Method</h3>
    <div class="create-form">
        <form method="post" id="methodForm">
            <input type="hidden" name="action" value="add" id="formAction">
            <input type="hidden" name="method_id" id="editMethodId">
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 25px;">
                <div class="form-group">
                    <label>Method ID</label>
                    <input type="text" name="method_id" id="newMethodId" placeholder="e.g., bkash" required>
                </div>
                <div class="form-group">
                    <label>Display Name</label>
                    <input type="text" name="name" id="methodName" placeholder="e.g., bKash" required>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 25px;">
                <div class="form-group">
                    <label>Type</label>
                    <select name="type" id="methodType">
                        <option value="mobile">Mobile Banking</option>
                        <option value="card">Card</option>
                        <option value="bank">Bank Transfer</option>
                        <option value="crypto">Cryptocurrency</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Icon (emoji)</label>
                    <input type="text" name="icon" id="methodIcon" placeholder="e.g., 📱" value="💳">
                </div>
            </div>
            
            <div class="form-group">
                <label>Account Number / Card Details</label>
                <input type="text" name="number" id="methodNumber" placeholder="e.g., 01XXXXXXXXX">
            </div>
            
            <div class="form-group">
                <label>Additional Details</label>
                <input type="text" name="details" id="methodDetails" placeholder="Extra information">
            </div>
            
            <div class="form-group">
                <label>Instructions for Users</label>
                <textarea name="instructions" id="methodInstructions" placeholder="e.g., Send money to 01XXXXXXXXX and enter Transaction ID"></textarea>
            </div>
            
            <button type="submit" class="btn-add" id="submitBtn">➕ ADD PAYMENT METHOD</button>
            <button type="button" class="btn-add" onclick="resetForm()" style="margin-left: 15px; background: #666; display: none;" id="cancelBtn">Cancel</button>
        </form>
    </div>

    <script>
        function editMethod(id, name, type, number, details, instructions, icon) {
            document.getElementById('formAction').value = 'edit';
            document.getElementById('editMethodId').value = id;
            document.getElementById('newMethodId').value = id;
            document.getElementById('newMethodId').disabled = true;
            document.getElementById('methodName').value = name;
            document.getElementById('methodType').value = type;
            document.getElementById('methodNumber').value = number;
            document.getElementById('methodDetails').value = details;
            document.getElementById('methodInstructions').value = instructions;
            document.getElementById('methodIcon').value = icon;
            document.getElementById('submitBtn').textContent = '💾 UPDATE METHOD';
            document.getElementById('cancelBtn').style.display = 'inline-block';
            window.scrollTo(0, document.body.scrollHeight);
        }
        
        function resetForm() {
            document.getElementById('formAction').value = 'add';
            document.getElementById('editMethodId').value = '';
            document.getElementById('newMethodId').value = '';
            document.getElementById('newMethodId').disabled = false;
            document.getElementById('methodName').value = '';
            document.getElementById('methodNumber').value = '';
            document.getElementById('methodDetails').value = '';
            document.getElementById('methodInstructions').value = '';
            document.getElementById('methodIcon').value = '💳';
            document.getElementById('submitBtn').textContent = '➕ ADD PAYMENT METHOD';
            document.getElementById('cancelBtn').style.display = 'none';
        }
    </script>
</body>
</html>
'''

ADMIN_USERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Users - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 32px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff00de, #00d4ff, #00ffcc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav a {
            color: #00d4ff;
            text-decoration: none;
            margin-left: 30px;
            font-weight: 700;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.02);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }
        th, td {
            padding: 25px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 14px;
        }
        tr:hover { background: rgba(255,255,255,0.03); }
        select {
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            color: white;
            font-size: 15px;
            min-width: 180px;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 15px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 800;
            font-size: 15px;
            transition: all 0.3s;
        }
        .btn:hover { transform: scale(1.05); box-shadow: 0 10px 25px rgba(0,255,204,0.3); }
        .plan-badge {
            display: inline-block;
            padding: 10px 25px;
            border-radius: 25px;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
        }
        .plan-starter { background: rgba(255,255,255,0.1); color: #aaa; }
        .plan-pro { background: rgba(0,212,255,0.2); color: #00d4ff; border: 1px solid #00d4ff; }
        .plan-enterprise { background: rgba(255,0,222,0.2); color: #ff00de; border: 1px solid #ff00de; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">👥 USER MANAGEMENT</div>
        <div class="nav">
            <a href="/admin/dashboard">Dashboard</a>
            <a href="/logout">Logout</a>
        </div>
    </div>

    <table>
        <tr>
            <th>Username</th>
            <th>Current Plan</th>
            <th>Status</th>
            <th>Change Plan</th>
        </tr>
        {% for username in users %}
        {% set user_sub = subs.get(username, {}) %}
        <tr>
            <td><strong style="font-size: 18px;">{{ username }}</strong></td>
            <td><span class="plan-badge plan-{{ user_sub.get('plan', 'starter') }}">{{ user_sub.get('plan', 'starter')|upper }}</span></td>
            <td>{% if user_sub.get('active') %}<span style="color: #00ff88; font-weight: 700;">● ACTIVE</span>{% else %}<span style="color: #ff4444;">○ INACTIVE</span>{% endif %}</td>
            <td>
                <form method="post" action="/admin/user/{{ username }}/setplan" style="display: flex; gap: 15px;">
                    <select name="plan_id">
                        {% for plan_id, plan in plans.items() %}
                        <option value="{{ plan_id }}" {% if plan_id == user_sub.get('plan') %}selected{% endif %}>{{ plan.name }}</option>
                        {% endfor %}
                    </select>
                    <button type="submit" class="btn">UPDATE</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

ADMIN_PAYMENTS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Payments - LAM CODEX OFCL</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0a0a0a;
            color: white;
            font-family: 'Inter', sans-serif;
            padding: 40px;
            min-height: 100vh;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            padding: 25px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            font-size: 32px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff00de, #00d4ff, #00ffcc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav a {
            color: #00d4ff;
            text-decoration: none;
            margin-left: 30px;
            font-weight: 700;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.02);
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }
        th, td {
            padding: 25px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 14px;
        }
        tr:hover { background: rgba(255,255,255,0.03); }
        .status {
            padding: 10px 25px;
            border-radius: 25px;
            font-size: 13px;
            font-weight: 800;
        }
        .status.completed { 
            background: rgba(0,255,204,0.2); 
            color: #00ffcc; 
            border: 1px solid #00ffcc;
            box-shadow: 0 0 15px rgba(0,255,204,0.2);
        }
        .status.pending { 
            background: rgba(255,170,0,0.2); 
            color: #ffaa00; 
            border: 1px solid #ffaa00;
        }
        .status.rejected { 
            background: rgba(255,68,68,0.2); 
            color: #ff4444; 
            border: 1px solid #ff4444;
        }
        .btn {
            padding: 12px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 800;
            font-size: 14px;
            transition: all 0.3s;
            margin-right: 10px;
        }
        .btn-approve {
            background: linear-gradient(135deg, #00ff88, #00cc66);
            color: #000;
        }
        .btn-reject {
            background: linear-gradient(135deg, #ff4444, #ff8844);
            color: white;
        }
        .btn:hover { transform: scale(1.05); }
        code {
            background: rgba(255,255,255,0.1);
            padding: 8px 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 14px;
        }
        .transaction-box {
            background: rgba(0,255,204,0.1);
            border: 1px solid #00ffcc;
            padding: 15px;
            border-radius: 10px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 16px;
            color: #00ffcc;
        }
        .reject-form {
            display: none;
            margin-top: 15px;
            padding: 20px;
            background: rgba(255,68,68,0.1);
            border-radius: 10px;
        }
        .reject-form input {
            width: 100%;
            padding: 12px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            color: white;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">💰 PAYMENT APPROVALS</div>
        <div class="nav">
            <a href="/admin/dashboard">Dashboard</a>
            <a href="/logout">Logout</a>
        </div>
    </div>

    <table>
        <tr>
            <th>Payment ID</th>
            <th>User</th>
            <th>Plan</th>
            <th>Amount</th>
            <th>Method</th>
            <th>Transaction ID</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
        {% for payment_id, payment in payments.items() %}
        <tr>
            <td><code>{{ payment_id[:12] }}...</code></td>
            <td><strong>{{ payment.user }}</strong></td>
            <td>{{ payment.plan|upper }}</td>
            <td style="color: #00ffcc; font-weight: 800; font-size: 18px;">${{ payment.amount }}</td>
            <td>{{ payment.payment_method|upper }}</td>
            <td>
                <div class="transaction-box">
                    {{ payment.transaction_id }}
                </div>
            </td>
            <td><span class="status {{ payment.status }}">{{ payment.status|upper }}</span></td>
            <td>
                {% if payment.status == 'pending' %}
                <form method="post" action="/admin/payment/{{ payment_id }}/approve" style="display: inline;">
                    <button type="submit" class="btn btn-approve">✓ APPROVE</button>
                </form>
                <button class="btn btn-reject" onclick="showRejectForm('{{ payment_id }}')">✗ REJECT</button>
                <form method="post" action="/admin/payment/{{ payment_id }}/reject" id="reject-{{ payment_id }}" class="reject-form">
                    <input type="text" name="reason" placeholder="Reason for rejection" required>
                    <button type="submit" class="btn btn-reject">Confirm Rejection</button>
                </form>
                {% else %}
                <span style="color: #666;">{{ payment.status|upper }}</span>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>

    <script>
        function showRejectForm(id) {
            const form = document.getElementById('reject-' + id);
            form.style.display = form.style.display === 'block' ? 'none' : 'block';
        }
    </script>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8030, debug=True, threaded=True)