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
USER_LIMITS_FILE = "user_limits.json"
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

def load_limits():
    return load_json(USER_LIMITS_FILE)

def save_limits(limits):
    save_json(USER_LIMITS_FILE, limits)

def load_startup_configs():
    return load_json(STARTUP_CONFIG_FILE)

def save_startup_configs(configs):
    save_json(STARTUP_CONFIG_FILE, configs)

def get_user_limits(username):
    limits = load_limits()
    return limits.get(username, {
        "ram": "512 MB",
        "storage": "1 GB",
        "max_bots": 1
    })

def get_startup_file(user, app_name):
    configs = load_startup_configs()
    key = f"{user}/{app_name}"
    config = configs.get(key, {})
    return config.get("file", "main.py")

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

# Main Index route maps directly to Login
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if 'username' in session and not session.get('is_admin'):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("access_key", "").strip()
        users = load_users()
        
        if u in users and users[u] == p:
            session['username'] = u
            session['is_admin'] = False
            return redirect(url_for("dashboard"))
        else:
            error = "❌ Galat ID/Password! Kripya sahi details bharein ya Admin se sampark karein."
    
    return render_template_string(LOGIN_TEMPLATE, error=error)

@app.route("/dashboard")
@login_required
def dashboard():
    user = session['username']
    user_dir = os.path.join(UPLOAD_FOLDER, user)
    os.makedirs(user_dir, exist_ok=True)
    
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
                         limits=limits,
                         app_count=app_count,
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
        flash(f"❌ Bot limit exceed! Max {limits['max_bots']} bot(s) allowed. Admin se contact karein.", "error")
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
    filepath = filepath.replace('..', '').replace('//', '/').strip('/')
    
    app_dir = os.path.join(UPLOAD_FOLDER, user, name, "extracted")
    full_path = os.path.join(app_dir, filepath)
    
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
            flash(f"✅ Startup configuration set to: {selected_file}", "success")
        return redirect(url_for('dashboard'))
    
    current_startup = get_startup_file(user, name)
    return render_template_string(STARTUP_TEMPLATE, 
                                bot_name=name, 
                                files=py_files,
                                current=current_startup)

# ---------- Admin Section ----------
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get('is_admin'):
        return redirect(url_for("admin_dashboard"))
    
    error = None
    if request.method == "POST":
        u = request.form.get("u", "").strip()
        p = request.form.get("p", "").strip()
        
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session.clear()
            session['username'] = ADMIN_USERNAME
            session['is_admin'] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid admin credentials"
    
    return render_template_string(ADMIN_LOGIN_TEMPLATE, error=error)

@app.route("/admin/dashboard", methods=["GET", "POST"])
@admin_required
def admin_dashboard():
    users = load_users()
    limits = load_limits()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        # Admin creates or updates a user and their limits
        if action == "save_user":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            max_bots = int(request.form.get("max_bots", 1))
            ram = request.form.get("ram", "512 MB").strip()
            storage = request.form.get("storage", "1 GB").strip()
            
            if username and password:
                users[username] = password
                limits[username] = {
                    "max_bots": max_bots,
                    "ram": ram,
                    "storage": storage
                }
                save_users(users)
                save_limits(limits)
                flash(f"✅ User '{username}' configuration updated successfully!", "success")
        
        elif action == "delete_user":
            target_user = request.form.get("username")
            if target_user in users:
                del users[target_user]
                if target_user in limits:
                    del limits[target_user]
                save_users(users)
                save_limits(limits)
                flash(f"🗑️ User '{target_user}' removed from system.", "success")

    total_users = len(users)
    bots_list = []
    
    if os.path.exists(UPLOAD_FOLDER):
        for u_name in os.listdir(UPLOAD_FOLDER):
            u_path = os.path.join(UPLOAD_FOLDER, u_name)
            if os.path.isdir(u_path):
                for a_name in os.listdir(u_path):
                    if os.path.isdir(os.path.join(u_path, a_name)):
                        is_running = (u_name, a_name) in processes and processes[(u_name, a_name)].poll() is None
                        bots_list.append({
                            'user': u_name,
                            'name': a_name,
                            'running': is_running
                        })
    
    messages = get_flashed_messages(with_categories=True)
    
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE,
                         users=users,
                         limits=limits,
                         bots_list=bots_list,
                         total_users=total_users,
                         messages=messages)

@app.route("/admin/download/<user>/<name>")
@admin_required
def admin_download(user, name):
    path = os.path.join(UPLOAD_FOLDER, user, name, "app.zip")
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name=f"{user}_{name}.zip")
    return "File Not Found", 404

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
    return redirect(url_for("login"))

# ---------- CSS & UI SYSTEM ----------
COMMON_STYLE = '''
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    :root { 
        --bg: #090d16; --card: #111827; --primary: #00f0ff; 
        --primary-hover: #00c8ff; --text: #f3f4f6; 
        --success: #10b981; --danger: #ef4444; --border: #1f2937;
    }
    body { 
        font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); 
        color: var(--text); margin: 0; padding: 20px; display: flex; 
        flex-direction: column; align-items: center; min-height: 100vh; box-sizing: border-box; 
    }
    .card { 
        background: var(--card); border: 1px solid var(--border); border-radius: 12px; 
        padding: 25px; width: 100%; max-width: 500px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); 
        box-sizing: border-box; text-align: center; margin-bottom: 20px; 
    }
    input, select, textarea { 
        width: 100%; padding: 12px; margin: 10px 0; border-radius: 6px; 
        border: 1px solid var(--border); background: #1f2937; color: white; box-sizing: border-box; font-size: 15px; 
    }
    button, .btn { 
        width: 100%; padding: 12px; margin: 10px 0; border-radius: 6px; border: none;
        background: var(--primary); color: #000; font-weight: bold; cursor: pointer;
        font-size: 15px; transition: 0.2s; display: inline-block; text-decoration: none; box-sizing: border-box;
    }
    button:hover, .btn:hover { background: var(--primary-hover); transform: translateY(-1px); }
    .btn-danger { background: var(--danger); color: white; }
    .btn-success { background: var(--success); color: white; }
    .btn-secondary { background: #374151; color: white; }
    .flash { padding: 12px; background: #1f2937; border-left: 4px solid var(--primary); margin: 10px 0; text-align: left; border-radius: 4px; font-size: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; background: var(--card); border-radius: 8px; overflow: hidden; }
    th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }
    th { background: #1f2937; color: var(--primary); }
    a { color: var(--primary); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
    .badge-success { background: rgba(16,185,129,0.2); color: #10b981; }
    .badge-danger { background: rgba(239,68,68,0.2); color: #ef4444; }
</style>
'''

# ---------- HTML BLOCKS ----------

LOGIN_TEMPLATE = f'''
<!DOCTYPE html>
<html>
<head><title>Login - Panel</title>{COMMON_STYLE}</head>
<body>
    <div class="card" style="margin-top: 50px;">
        <h2 style="color: var(--primary); margin-bottom: 5px; font-size: 28px; tracking: -0.5px;">CLOUD PANEL</h2>
        <p style="color: #6b7280; margin-top: 0; font-size: 14px;">Sign in to manage your bot services</p>
        
        {{% if error %}}<div class="flash" style="border-left-color: var(--danger); color: #f87171;">{{{{ error }}}}</div>{{% endif %}}
        
        <form method="POST">
            <input type="text" name="username" placeholder="Username" required autocomplete="off">
            <input type="password" name="access_key" placeholder="Password" required>
            <button type="submit">LOGIN</button>
        </form>
    </div>
</body>
</html>
'''

DASHBOARD_TEMPLATE = f'''
<!DOCTYPE html>
<html>
<head><title>Dashboard</title>{COMMON_STYLE}</head>
<body>
    <div class="card" style="max-width: 800px; text-align: left;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2>Welcome, {{{{ session['username'] }}}} 👋</h2>
            <a href="/logout" class="btn btn-danger" style="width: auto; padding: 8px 15px; margin:0;">Logout</a>
        </div>
        
        <div style="background: #1f2937; padding: 15px; border-radius: 8px; margin: 15px 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center;">
            <div><span style="color:#6b7280; font-size:12px;">BOTS LIMIT</span><br><strong>{{{{ app_count }}}} / {{{{ limits['max_bots'] }}}}</strong></div>
            <div><span style="color:#6b7280; font-size:12px;">RAM ALLOCATED</span><br><strong>{{{{ limits['ram'] }}}}</strong></div>
            <div><span style="color:#6b7280; font-size:12px;">STORAGE</span><br><strong>{{{{ limits['storage'] }}}}</strong></div>
        </div>

        {{% with messages = get_flashed_messages(with_categories=true) %}}
            {{% if messages %}}
                {{% for cat, msg in messages %}}
                    <div class="flash" style="border-left-color: {{'var(--success)' if cat=='success' else 'var(--danger)'}}">{{{{ msg }}}}</div>
                {{% endfor %}}
            {{% endif %}}
        {{% endwith %}}

        <h3>📤 Upload New Bot Bundle</h3>
        <form action="/upload" method="POST" enctype="multipart/form-data" style="display: flex; gap: 10px; align-items: center;">
            <input type="file" name="file" accept=".zip" required style="margin:0;">
            <button type="submit" class="btn-success" style="width: auto; margin:0; white-space: nowrap;">Deploy ZIP</button>
        </form>

        <h3 style="margin-top: 30px;">🤖 Your Active Bots</h3>
        {{% if not apps %}}
            <p style="color: #6b7280;">No bots deployed yet. Upload a ZIP file to get started.</p>
        {{% else %}}
            {{% for app in apps %}}
            <div style="background: #111827; border: 1px solid var(--border); padding: 15px; border-radius: 8px; margin-bottom: 10px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="font-size: 16px; color: var(--primary);">{{{{ app.name }}}}</strong>
                        {{% if app.running %}}
                            <span class="badge badge-success">🟢 RUNNING</span>
                        {{% else %}}
                            <span class="badge badge-danger">🔴 STOPPED</span>
                        {{% endif %}}
                        <br><span style="font-size:12px; color:#6b7280;">Startup: {{{{ app.startup_file }}}}</span>
                    </div>
                    <div style="display: flex; gap: 5px;">
                        <a href="/run/{{{{ app.name }}}}" class="btn btn-success" style="padding: 6px 12px; margin:0; font-size:13px; width:auto;">Start</a>
                        <a href="/stop/{{{{ app.name }}}}" class="btn btn-danger" style="padding: 6px 12px; margin:0; font-size:13px; width:auto;">Stop</a>
                        <a href="/restart/{{{{ app.name }}}}" class="btn btn-secondary" style="padding: 6px 12px; margin:0; font-size:13px; width:auto;">Restart</a>
                    </div>
                </div>
                <div style="margin-top: 10px; display: flex; gap: 10px; border-top: 1px solid var(--border); padding-top: 10px; font-size: 13px;">
                    <a href="/console/{{{{ app.name }}}}" style="font-weight: bold;">🖥️ Live Console</a> | 
                    <a href="/files/{{{{ app.name }}}}" style="font-weight: bold;">📁 File Manager</a> | 
                    <a href="/startup/{{{{ app.name }}}}" style="font-weight: bold;">⚙️ Startup File</a> | 
                    <a href="/delete/{{{{ app.name }}}}" style="color: var(--danger);" onclick="return confirm('Delete this bot?')">🗑️ Delete</a>
                </div>
            </div>
            {{% endfor %}}
        {{% endif %}}
    </div>
</body>
</html>
'''

ADMIN_LOGIN_TEMPLATE = f'''
<!DOCTYPE html>
<html>
<head><title>Admin Gate</title>{COMMON_STYLE}</head>
<body>
    <div class="card" style="margin-top: 60px;">
        <h2>Admin Master Security</h2>
        {{% if error %}}<p style="color:var(--danger)">{{{{ error }}}}</p>{{% endif %}}
        <form method="POST">
            <input type="text" name="u" placeholder="Secure Username" required>
            <input type="password" name="p" placeholder="Secure Password" required>
            <button type="submit" class="btn-danger">Unlock Admin Console</button>
        </form>
    </div>
</body>
</html>
'''

ADMIN_DASHBOARD_TEMPLATE = f'''
<!DOCTYPE html>
<html>
<head><title>Master Admin Control</title>{COMMON_STYLE}</head>
<body>
    <div class="card" style="max-width: 900px; text-align: left;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2>🛠️ Master Administration Panel</h2>
            <a href="/logout" class="btn btn-danger" style="width: auto; padding: 8px 15px; margin:0;">Logout</a>
        </div>
        
        {{% with messages = get_flashed_messages(with_categories=true) %}}
            {{% if messages %}}
                {{% for cat, msg in messages %}}
                    <div class="flash" style="border-left-color: var(--primary)">{{{{ msg }}}}</div>
                {{% endfor %}}
            {{% endif %}}
        {{% endwith %}}

        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-top: 20px;">
            <div style="background: #111827; border: 1px solid var(--border); padding: 15px; border-radius: 8px; height: fit-content;">
                <h3 style="color: var(--primary); margin-top:0;">👤 Configure Account</h3>
                <form method="POST">
                    <input type="hidden" name="action" value="save_user">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="text" name="password" placeholder="Password/Access Key" required>
                    <input type="number" name="max_bots" placeholder="Bot Limits (Count)" min="1" value="1" required>
                    <input type="text" name="ram" placeholder="RAM Allocation" value="512 MB">
                    <input type="text" name="storage" placeholder="Storage Allocation" value="1 GB">
                    <button type="submit" class="btn-success">Save Account</button>
                </form>
                
                <h4 style="margin-top: 20px; color: var(--danger);">⚠️ Remove Account</h4>
                <form method="POST" onsubmit="return confirm('Are you sure you want to completely delete this user?')">
                    <input type="hidden" name="action" value="delete_user">
                    <select name="username" required>
                        <option value="">-- Select User --</option>
                        {{% for u in users %}} <option value="{{{{u}}}}">{{{{u}}}}</option> {{% endfor %}}
                    </select>
                    <button type="submit" class="btn-danger">Delete User Account</button>
                </form>
            </div>

            <div>
                <h3 style="margin-top:0;">👥 System Registered Users Details</h3>
                <table>
                    <tr><th>User</th><th>Password</th><th>Max Bots</th><th>RAM/Storage</th></tr>
                    {{% for u, p in users.items() %}}
                    <tr>
                        <td><strong>{{{{ u }}}}</strong></td>
                        <td><code>{{{{ p }}}}</code></td>
                        <td>{{{{ limits[u]['max_bots'] if u in limits else 1 }}}}</td>
                        <td>{{{{ limits[u]['ram'] if u in limits else '512 MB' }}}} / {{{{ limits[u]['storage'] if u in limits else '1 GB' }}}}</td>
                    </tr>
                    {{% endfor %}}
                </table>

                <h3 style="margin-top: 30px;">📊 Active Running User Instances</h3>
                <table>
                    <tr><th>User</th><th>Bot Name</th><th>Status</th><th>Actions</th></tr>
                    {{% for b in bots_list %}}
                    <tr>
                        <td>{{{{ b.user }}}}</td>
                        <td>{{{{ b.name }}}}</td>
                        <td>
                            {{% if b.running %}} <span class="badge badge-success">🟢 Active</span> 
                            {{% else %}} <span class="badge badge-danger">🔴 Idle</span> {{% endif %}}
                        </td>
                        <td>
                            <a href="/admin/download/{{{{b.user}}}}/{{{{b.name}}}}" style="color: var(--primary); font-weight: bold; font-size:12px;">📥 ZIP</a> |
                            <a href="/admin/run/{{{{b.user}}}}/{{{{b.name}}}}" style="color: var(--success); font-weight: bold; font-size:12px;">Boot</a> |
                            <a href="/admin/stop/{{{{b.user}}}}/{{{{b.name}}}}" style="color: var(--danger); font-weight: bold; font-size:12px;">Kill</a> |
                            <a href="/admin/delete/{{{{b.user}}}}/{{{{b.name}}}}" style="color: #6b7280; font-size:12px;" onclick="return confirm('Wipe instance?')">Wipe</a>
                        </td>
                    </tr>
                    {{% endfor %}}
                </table>
            </div>
        </div>
    </div>
</body>
</html>
'''

CONSOLE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Live Terminal Console</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { background: #05070f; color: #00ff66; font-family: monospace; padding: 20px; margin: 0; }
        .header { background: #111; padding: 10px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; color: white; }
        #terminal { background: #000; border: 1px solid #222; padding: 15px; height: 60vh; overflow-y: auto; border-radius: 6px; white-space: pre-wrap; word-break: break-all; }
        .input-line { display: flex; margin-top: 10px; background: #000; border: 1px solid #222; padding: 5px; border-radius: 6px; }
        .input-line span { color: #00ff66; padding-right: 5px; font-weight: bold; }
        #cmd { background: transparent; border: none; color: white; flex-grow: 1; outline: none; font-family: monospace; font-size: 14px; }
    </style>
</head>
<body>
    <div class="header">
        <span>Instance Logs: <strong>{{ bot_name }}</strong></span>
        <a href="/dashboard" style="color:#00f0ff; text-decoration:none;">Back to Home</a>
    </div>
    
    <div id="terminal">{{ output }}</div>
    
    <div class="input-line">
        <span>$</span>
        <input type="text" id="cmd" placeholder="Send continuous standard input stream down to script thread..." autocomplete="off">
    </div>

    <script>
        const terminal = document.getElementById('terminal');
        terminal.scrollTop = terminal.scrollHeight;

        const source = new EventSource('/console/{{ bot_name }}/stream');
        source.onmessage = function(event) {
            const data = JSON.parse(event.data);
            if(data.lines && data.lines.length > 0) {
                data.lines.forEach(line => {
                    terminal.textContent += line;
                });
                terminal.scrollTop = terminal.scrollHeight;
            }
        };

        document.getElementById('cmd').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                const cmd = this.value;
                this.value = '';
                fetch('/console/{{ bot_name }}/input', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: cmd})
                });
            }
        });
    </script>
</body>
</html>
'''

FILE_MANAGER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Storage Matrix Explorer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { background: #090d16; color: #f3f4f6; font-family: sans-serif; padding: 20px; margin:0;}
        .container { max-width: 900px; margin: 0 auto; background: #111827; padding: 25px; border-radius: 12px; border: 1px solid #1f2937; }
        .header { display: flex; justify-content: space-between; margin-bottom: 20px; border-bottom: 1px solid #1f2937; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #1f2937; font-size:14px; }
        th { background: #1f2937; color: #00f0ff; }
        .actions-bar { margin-bottom: 15px; display: flex; gap: 10px; flex-wrap: wrap; }
        button, input[type="button"] { background: #00f0ff; color: black; font-weight: bold; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; }
        .danger { background: #ef4444; color: white; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h3>Files Explorer: <span style="color:#00f0ff;">{{ bot_name }}</span></h3>
        <a href="/dashboard" style="color:#00f0ff; text-decoration:none;">Back to Main Screen</a>
    </div>
    
    <p>Current Path: <code>/{{ current_path }}</code></p>
    
    <div class="actions-bar">
        <button onclick="mkdir()">New Folder</button>
        <input type="file" id="file_uploader" style="display: none;" onchange="uploadFile()">
        <button onclick="document.getElementById('file_uploader').click()">Upload File</button>
        {% if current_path %}
            <button onclick="window.location.href='?path={{ current_path.split('/')[:-1]|join('/') }}'" style="background:#374151; color:white;">⬅ Up</button>
        {% endif %}
    </div>

    <table>
        <tr><th>Name</th><th>Modified</th><th>Size</th><th>Controls</th></tr>
        {% for item in items %}
        <tr>
            <td>
                {% if item.is_dir %}
                    📁 <a href="?path={{ item.path }}" style="font-weight: bold; color: #00f0ff;">{{ item.name }}/</a>
                {% else %}
                    📄 <a href="/files/{{ bot_name }}/edit?path={{ item.path }}" style="color: white;">{{ item.name }}</a>
                {% endif %}
            </td>
            <td>{{ item.modified }}</td>
            <td>{{ (item.size / 1024)|round(1) }} KB</td>
            <td>
                <a href="#" onclick="rename('{{ item.path }}')" style="color:#10b981; margin-right: 10px; font-size:12px;">Rename</a>
                <a href="#" onclick="deleteItem('{{ item.path }}')" style="color:#ef4444; font-size:12px;">Delete</a>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

<script>
function mkdir() {
    const name = prompt("Enter folder name:");
    if (name) {
        fetch('/files/{{ bot_name }}/mkdir', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: '{{ current_path }}', name: name})
        }).then(() => location.reload());
    }
}
function uploadFile() {
    const fileInput = document.getElementById('file_uploader');
    if (fileInput.files.length === 0) return;
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('path', '{{ current_path }}');
    
    fetch('/files/{{ bot_name }}/upload', {
        method: 'POST',
        body: formData
    }).then(res => res.json()).then(data => {
        if(data.success) location.reload();
        else alert(data.error);
    });
}
function rename(oldPath) {
    const name = prompt("Enter new name:");
    if(name) {
        fetch('/files/{{ bot_name }}/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({old_path: oldPath, new_name: name})
        }).then(() => location.reload());
    }
}
function deleteItem(path) {
    if(confirm("Confirm deletion of item?")) {
        fetch('/files/{{ bot_name }}/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({path: path})
        }).then(() => location.reload());
    }
}
</script>
</body>
</html>
'''

EDIT_FILE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Edit - Code Workspace</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { background: #090d16; color: white; font-family: sans-serif; padding: 20px; margin:0;}
        .box { max-width: 1000px; margin:0 auto; background: #111827; padding:20px; border-radius:12px;}
        textarea { width: 100%; height: 65vh; background: #000; color: #00ff66; font-family: monospace; padding:15px; border-radius:6px; border:1px solid #1f2937; font-size:14px; resize:vertical; outline:none;}
        .row { display: flex; justify-content: space-between; margin-bottom: 15px; align-items:center;}
        button { background: #10b981; color: white; font-weight: bold; padding: 10px 25px; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
<div class="box">
    <div class="row">
        <h3>Editing: <span style="color:#00f0ff;">{{ filepath }}</span></h3>
        <a href="/files/{{ bot_name }}" style="color:#00f0ff; text-decoration:none;">Discard Changes</a>
    </div>
    
    <textarea id="editor">{{ content }}</textarea>
    <br><br>
    <button onclick="saveFile()">💾 Save Script Modifications</button>
</div>

<script>
function saveFile() {
    const text = document.getElementById('editor').value;
    fetch('/files/{{ bot_name }}/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: '{{ filepath }}', content: text})
    }).then(res => res.json()).then(data => {
        if(data.success) alert("Script successfully compiled and saved down to disk!");
        else alert(data.error);
    });
}
</script>
</body>
</html>
'''

STARTUP_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Startup Configuration</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { background: #090d16; color: white; font-family: sans-serif; padding: 20px;}
        .box { max-width: 500px; margin: 40px auto; background: #111827; padding:25px; border-radius:12px; border:1px solid #1f2937;}
        select, button { width: 100%; padding:12px; margin-top:15px; border-radius:6px; font-size:15px;}
        button { background: #00f0ff; color: black; font-weight: bold; border:none; cursor: pointer;}
    </style>
</head>
<body>
<div class="box">
    <h3>Configure Startup Hook</h3>
    <p style="color:#6b7280; font-size:13px;">Select which file standard engine will execute on booting up the cluster runner.</p>
    
    <form method="POST">
        <label>Primary Entry File Pointer:</label>
        <select name="startup_file">
            {% for f in files %}
                <option value="{{ f }}" {% if f == current %}selected{% endif %}>{{ f }}</option>
            {% endfor %}
        </select>
        <button type="submit">Update Setup Vector</button>
    </form>
    <br>
    <center><a href="/dashboard" style="color: #6b7280; font-size: 13px;">Return to Dashboard</a></center>
</div>
</body>
</html>
'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8030, debug=True, threaded=True)
