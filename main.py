from flask import Flask, render_template_string, request, redirect, url_for, session, send_file, flash, jsonify, Response, get_flashed_messages
import os, zipfile, subprocess, shutil, json, sys, uuid, datetime, threading, time, re
from functools import wraps

app = Flask(__name__)
app.secret_key = "SEMYPAPAJI"

# --- Master Admin Credentials ---
ADMIN_USERNAME = "SEMY"
ADMIN_PASSWORD = "SEMY777"

UPLOAD_FOLDER = "uploads"
USER_DATA_FILE = "users.json"
USER_LIMITS_FILE = "user_limits.json"  # New file for user bot limits
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

def load_user_limits():
    return load_json(USER_LIMITS_FILE)

def save_user_limits(limits):
    save_json(USER_LIMITS_FILE, limits)

def get_user_bot_limit(username):
    """Get bot limit for a user, default 0 (can't upload without admin setting limit)"""
    limits = load_user_limits()
    return limits.get(username, 0)

def set_user_bot_limit(username, limit):
    limits = load_user_limits()
    limits[username] = limit
    save_user_limits(limits)

def get_user_ram_limit(username):
    """Get RAM limit - for future use"""
    limits = load_user_limits()
    return limits.get(f"{username}_ram", "512 MB")

def get_user_storage_limit(username):
    """Get storage limit - for future use"""
    limits = load_user_limits()
    return limits.get(f"{username}_storage", "1 GB")

def get_startup_file(user, app_name):
    """Get startup file for a bot"""
    configs = load_startup_configs()
    key = f"{user}/{app_name}"
    config = configs.get(key, {})
    return config.get("file", "main.py")

def set_startup_file(user, app_name, filename):
    configs = load_startup_configs()
    key = f"{user}/{app_name}"
    configs[key] = {"file": filename}
    save_startup_configs(configs)

def load_startup_configs():
    return load_json("startup_configs.json")

def save_startup_configs(configs):
    save_json("startup_configs.json", configs)

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
def index():
    # Direct login page - no landing page
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if 'username' in session and not session.get('is_admin'):
        return redirect(url_for("dashboard"))
    if session.get('is_admin'):
        return redirect(url_for("admin_dashboard"))
        
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        users = load_users()
        
        # Check if user exists and password matches
        if u in users and users[u] == p:
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
    
    bot_limit = get_user_bot_limit(user)
    ram_limit = get_user_ram_limit(user)
    storage_limit = get_user_storage_limit(user)
    
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
                         bot_limit=bot_limit,
                         ram_limit=ram_limit,
                         storage_limit=storage_limit,
                         app_count=app_count,
                         session=session,
                         messages=messages)

@app.route("/upload", methods=["POST"])
@login_required
def upload_app():
    user = session['username']
    bot_limit = get_user_bot_limit(user)
    user_dir = os.path.join(UPLOAD_FOLDER, user)
    
    current_apps = len([d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))]) if os.path.exists(user_dir) else 0
    
    if bot_limit == 0:
        flash("❌ Admin hasn't assigned any bot limit to you. Contact admin.", "error")
        return redirect(url_for("dashboard"))
    
    if current_apps >= bot_limit:
        flash(f"❌ Bot limit reached! Max {bot_limit} bot(s) allowed. Contact admin to increase limit.", "error")
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
            flash(f"✅ Startup: {selected_file}", "success")
        return redirect(url_for('dashboard'))
    
    current_startup = get_startup_file(user, name)
    return render_template_string(STARTUP_TEMPLATE, 
                                bot_name=name, 
                                files=py_files,
                                current=current_startup)

@app.route("/my-info")
@login_required
def my_info():
    user = session['username']
    bot_limit = get_user_bot_limit(user)
    ram_limit = get_user_ram_limit(user)
    storage_limit = get_user_storage_limit(user)
    return render_template_string(MY_INFO_TEMPLATE, 
                                user=user,
                                bot_limit=bot_limit,
                                ram_limit=ram_limit,
                                storage_limit=storage_limit)

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
    user_limits = load_user_limits()
    
    # Get all users with bot counts
    users_list = []
    for u_name in users:
        user_dir = os.path.join(UPLOAD_FOLDER, u_name)
        bot_count = 0
        if os.path.exists(user_dir):
            bot_count = len([d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))])
        
        users_list.append({
            'username': u_name,
            'bot_limit': user_limits.get(u_name, 0),
            'bot_count': bot_count,
            'ram': user_limits.get(f"{u_name}_ram", "512 MB"),
            'storage': user_limits.get(f"{u_name}_storage", "1 GB"),
            'can_upload': user_limits.get(u_name, 0) > 0
        })
    
    messages = get_flashed_messages(with_categories=True)
    
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE,
                         users=users_list,
                         stats={
                             "total_users": len(users),
                             "total_bots": sum(u['bot_count'] for u in users_list),
                             "active_users": sum(1 for u in users_list if u['can_upload'])
                         },
                         messages=messages)

@app.route("/admin/users")
@admin_required
def admin_users():
    users = load_users()
    user_limits = load_user_limits()
    
    users_list = []
    for u_name in users:
        user_dir = os.path.join(UPLOAD_FOLDER, u_name)
        bot_count = 0
        if os.path.exists(user_dir):
            bot_count = len([d for d in os.listdir(user_dir) if os.path.isdir(os.path.join(user_dir, d))])
        
        users_list.append({
            'username': u_name,
            'bot_limit': user_limits.get(u_name, 0),
            'bot_count': bot_count,
            'ram': user_limits.get(f"{u_name}_ram", "512 MB"),
            'storage': user_limits.get(f"{u_name}_storage", "1 GB")
        })
    
    return render_template_string(ADMIN_USERS_TEMPLATE, users=users_list)

@app.route("/admin/user/<username>/setlimit", methods=["POST"])
@admin_required
def admin_set_user_limit(username):
    bot_limit = int(request.form.get("bot_limit", 0))
    ram_limit = request.form.get("ram_limit", "512 MB")
    storage_limit = request.form.get("storage_limit", "1 GB")
    
    set_user_bot_limit(username, bot_limit)
    
    # Set RAM and storage limits
    limits = load_user_limits()
    limits[f"{username}_ram"] = ram_limit
    limits[f"{username}_storage"] = storage_limit
    save_user_limits(limits)
    
    flash(f"✅ Updated {username} - Bot Limit: {bot_limit}, RAM: {ram_limit}, Storage: {storage_limit}", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/user/<username>/delete", methods=["POST"])
@admin_required
def admin_delete_user(username):
    if username == ADMIN_USERNAME:
        flash("❌ Cannot delete master admin!", "error")
        return redirect(url_for("admin_users"))
    
    # Stop all bots of this user
    user_dir = os.path.join(UPLOAD_FOLDER, username)
    if os.path.exists(user_dir):
        for bot_name in os.listdir(user_dir):
            if os.path.isdir(os.path.join(user_dir, bot_name)):
                stop_app(username, bot_name)
        shutil.rmtree(user_dir, ignore_errors=True)
    
    # Remove user from users.json
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
    
    # Remove user limits
    limits = load_user_limits()
    keys_to_remove = [k for k in limits.keys() if k.startswith(username)]
    for k in keys_to_remove:
        del limits[k]
    save_user_limits(limits)
    
    # Remove startup configs
    configs = load_startup_configs()
    keys_to_remove = [k for k in configs.keys() if k.startswith(f"{username}/")]
    for k in keys_to_remove:
        del configs[k]
    save_startup_configs(configs)
    
    flash(f"🗑️ Deleted user {username} and all their data", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/createuser", methods=["POST"])
@admin_required
def admin_create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    bot_limit = int(request.form.get("bot_limit", 0))
    ram_limit = request.form.get("ram_limit", "512 MB")
    storage_limit = request.form.get("storage_limit", "1 GB")
    
    if not username or not password:
        flash("❌ Username and password required!", "error")
        return redirect(url_for("admin_users"))
    
    users = load_users()
    if username in users:
        flash("❌ Username already exists!", "error")
        return redirect(url_for("admin_users"))
    
    # Create user
    users[username] = password
    save_users(users)
    
    # Set limits
    set_user_bot_limit(username, bot_limit)
    limits = load_user_limits()
    limits[f"{username}_ram"] = ram_limit
    limits[f"{username}_storage"] = storage_limit
    save_user_limits(limits)
    
    # Create user directory
    os.makedirs(os.path.join(UPLOAD_FOLDER, username), exist_ok=True)
    
    flash(f"✅ Created user {username} with bot limit: {bot_limit}", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/bots")
@admin_required
def admin_bots():
    users = load_users()
    bots_list = []
    
    for u_name in users:
        user_dir = os.path.join(UPLOAD_FOLDER, u_name)
        if os.path.exists(user_dir):
            for bot_name in os.listdir(user_dir):
                bot_path = os.path.join(user_dir, bot_name)
                if os.path.isdir(bot_path):
                    is_running = (u_name, bot_name) in processes and processes[(u_name, bot_name)].poll() is None
                    bots_list.append({
                        'user': u_name,
                        'name': bot_name,
                        'running': is_running
                    })
    
    return render_template_string(ADMIN_BOTS_TEMPLATE, bots=bots_list)

@app.route("/admin/run/<user>/<name>")
@admin_required
def admin_run(user, name):
    success, msg = start_app(user, name)
    if success:
        flash(f"✅ Started {user}/{name}", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for("admin_bots"))

@app.route("/admin/stop/<user>/<name>")
@admin_required
def admin_stop(user, name):
    if stop_app(user, name):
        flash(f"⏹️ Stopped {user}/{name}", "success")
    else:
        flash(f"Not running", "info")
    return redirect(url_for("admin_bots"))

@app.route("/admin/restart/<user>/<name>")
@admin_required
def admin_restart(user, name):
    success, msg = restart_app(user, name)
    if success:
        flash(f"🔄 Restarted {user}/{name}", "success")
    else:
        flash(f"❌ {msg}", "error")
    return redirect(url_for("admin_bots"))

@app.route("/admin/delete/<user>/<name>")
@admin_required
def admin_delete(user, name):
    stop_app(user, name)
    shutil.rmtree(os.path.join(UPLOAD_FOLDER, user, name), ignore_errors=True)
    flash(f"🗑️ Deleted {user}/{name}", "success")
    return redirect(url_for("admin_bots"))

@app.route("/admin/download/<user>/<name>")
@admin_required
def admin_download(user, name):
    path = os.path.join(UPLOAD_FOLDER, user, name, "app.zip")
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name=f"{user}_{name}.zip")
    return "Not Found", 404

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- HTML TEMPLATES ----------
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
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">LOGIN</button>
        </form>
        <p class="hint">Contact admin for account creation</p>
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
        .limit-badge {
            background: rgba(255,255,255,0.1);
            padding: 10px 25px;
            border-radius: 25px;
            font-weight: 700;
            font-size: 14px;
        }
        .limit-badge.warning {
            background: rgba(255,170,0,0.2);
            color: #ffaa00;
            border: 1px solid #ffaa00;
        }
        .limit-badge.danger {
            background: rgba(255,68,68,0.2);
            color: #ff4444;
            border: 1px solid #ff4444;
        }
        .nav-links a {
            color: #ff4444;
            text-decoration: none;
            margin-left: 25px;
            font-weight: 600;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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
        .limit-notice {
            background: rgba(255,170,0,0.1);
            border: 1px solid #ffaa00;
            color: #ffaa00;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">⚡ LAM CODEX OFCL</div>
        <div>
            <span class="limit-badge {% if bot_limit == 0 %}danger{% elif app_count >= bot_limit %}warning{% endif %}">
                🤖 {{ app_count }} / {{ bot_limit }} Bots
            </span>
            <span style="margin-left: 20px; color: #666;">{{ session.username }}</span>
            <a href="/my-info" style="margin-left: 20px; color: #00d4ff;">ℹ️ My Info</a>
            <a href="/logout" style="margin-left: 15px; color: #ff4444;">Logout</a>
        </div>
    </div>

    {% if messages %}
        {% for category, message in messages %}
            <div class="flash {{ category }}">{{ message }}</div>
        {% endfor %}
    {% endif %}

    {% if bot_limit == 0 %}
    <div class="limit-notice">
        ⚠️ You don't have any bot limit assigned. Contact admin to get access.
    </div>
    {% endif %}

    <div class="stats">
        <div class="stat-box">
            <div class="stat-label">Your Limit</div>
            <div class="stat-value">{{ bot_limit }} Bot(s)</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Used Bots</div>
            <div class="stat-value">{{ app_count }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">RAM Limit</div>
            <div class="stat-value">{{ ram_limit }}</div>
        </div>
        <div class="stat-box">
            <div class="stat-label">Storage Limit</div>
            <div class="stat-value">{{ storage_limit }}</div>
        </div>
    </div>

    {% if bot_limit > 0 %}
    <div class="upload-section">
        <h3 style="margin-bottom: 20px; font-size: 24px;">📁 Upload New Bot</h3>
        <form method="post" action="/upload" enctype="multipart/form-data">
            <input type="file" name="file" accept=".zip" required style="margin-bottom: 20px; color: white; padding: 15px; width: 100%; max-width: 400px;">
            <br>
            <button type="submit" class="btn btn-large">UPLOAD ZIP FILE</button>
        </form>
    </div>
    {% else %}
    <div class="upload-section" style="opacity: 0.5;">
        <h3 style="margin-bottom: 20px; font-size: 24px;">📁 Upload New Bot (Disabled)</h3>
        <p style="color: #ffaa00;">You need bot limit to upload. Contact admin.</p>
    </div>
    {% endif %}

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

# [CONSOLE_TEMPLATE remains same as original]
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

# [FILE_MANAGER_TEMPLATE remains same as original]
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

# [EDIT_FILE_TEMPLATE remains same]
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

MY_INFO_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>My Info - LAM CODEX OFCL</title>
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
            max-width: 600px;
            margin: 0 auto;
            background: rgba(255,255,255,0.05);
            border-radius: 25px;
            border: 1px solid rgba(255,255,255,0.1);
            overflow: hidden;
        }
        .info-row {
            display: flex;
            padding: 25px 30px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .info-label {
            width: 120px;
            font-weight: 700;
            color: #00ffcc;
        }
        .info-value {
            flex: 1;
            color: white;
        }
        .info-value.limit {
            font-size: 24px;
            font-weight: 800;
            color: #00ffcc;
        }
        .back {
            display: inline-block;
            margin-top: 30px;
            color: #666;
            text-decoration: none;
            text-align: center;
            font-size: 16px;
        }
        .back:hover { color: #00ffcc; }
        .text-center { text-align: center; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">ℹ️ MY INFORMATION</div>
        <a href="/dashboard" class="back">← Back to Dashboard</a>
    </div>

    <div class="container">
        <div class="info-row">
            <div class="info-label">Username</div>
            <div class="info-value">{{ user }}</div>
        </div>
        <div class="info-row">
            <div class="info-label">Bot Limit</div>
            <div class="info-value limit">{{ bot_limit }}</div>
        </div>
        <div class="info-row">
            <div class="info-label">RAM Limit</div>
            <div class="info-value">{{ ram_limit }}</div>
        </div>
        <div class="info-row">
            <div class="info-label">Storage Limit</div>
            <div class="info-value">{{ storage_limit }}</div>
        </div>
    </div>
    
    <div class="text-center">
        <a href="/dashboard" class="back">← Back to Dashboard</a>
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
            flex-wrap: wrap;
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
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 700;
            font-size: 16px;
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
        .flash.error { background: rgba(255,68,68,0.2); border: 1px solid #ff4444; color: #ff4444; }
        .limit-badge {
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 700;
        }
        .limit-high { background: rgba(0,255,204,0.2); color: #00ffcc; }
        .limit-low { background: rgba(255,170,0,0.2); color: #ffaa00; }
        .limit-none { background: rgba(255,68,68,0.2); color: #ff4444; }
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
        <a href="/admin/users">👥 Users</a>
        <a href="/admin/bots">🤖 Bots</a>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{{ stats.total_users }}</div>
            <div class="stat-label">Total Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ stats.total_bots }}</div>
            <div class="stat-label">Total Bots</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ stats.active_users }}</div>
            <div class="stat-label">Active Users</div>
        </div>
    </div>

    <h3 style="margin-bottom: 25px; font-size: 24px; color: #00ffcc;">Users & Limits</h3>
    <table>
        <tr>
            <th>Username</th>
            <th>Bot Limit</th>
            <th>Current Bots</th>
            <th>RAM</th>
            <th>Storage</th>
            <th>Status</th>
        </tr>
        {% for user in users %}
        <tr>
            <td><strong>{{ user.username }}</strong></td>
            <td>
                <span class="limit-badge {% if user.bot_limit > 5 %}limit-high{% elif user.bot_limit > 0 %}limit-low{% else %}limit-none{% endif %}">
                    {{ user.bot_limit }}
                </span>
            </td>
            <td>{{ user.bot_count }} / {{ user.bot_limit }}</td>
            <td>{{ user.ram }}</td>
            <td>{{ user.storage }}</td>
            <td>
                {% if user.can_upload %}
                    <span style="color: #00ff88;">✓ Active</span>
                {% else %}
                    <span style="color: #ff4444;">✗ Inactive</span>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

ADMIN_USERS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Manage Users - LAM CODEX OFCL</title>
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
        .create-form, .edit-form {
            background: rgba(255,255,255,0.05);
            padding: 35px;
            border-radius: 20px;
            margin-bottom: 40px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        label {
            color: #00ffcc;
            font-weight: 700;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        input, select {
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 10px;
            color: white;
            font-size: 15px;
        }
        input:focus {
            border-color: #00ffcc;
            outline: none;
        }
        .btn {
            background: linear-gradient(135deg, #00ffcc, #00d4ff);
            color: #000;
            padding: 15px 35px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: 800;
            font-size: 16px;
            transition: all 0.3s;
            margin-top: 20px;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0,255,204,0.3);
        }
        .btn-danger {
            background: linear-gradient(135deg, #ff4444, #ff8844);
            color: white;
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
            padding: 20px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 13px;
        }
        tr:hover { background: rgba(255,255,255,0.03); }
        .flash {
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 700;
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
        .flash.error { background: rgba(255,68,68,0.2); border: 1px solid #ff4444; color: #ff4444; }
        .delete-form {
            display: inline-block;
        }
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        .small-btn {
            padding: 8px 15px;
            font-size: 13px;
            border-radius: 8px;
            background: rgba(255,255,255,0.1);
            color: white;
            border: none;
            cursor: pointer;
            transition: all 0.3s;
        }
        .small-btn.danger:hover { background: #ff4444; color: white; }
        .small-btn:hover { transform: scale(1.05); }
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

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div class="create-form">
        <h3 style="margin-bottom: 25px; color: #00ffcc;">➕ Create New User</h3>
        <form method="post" action="/admin/createuser">
            <div class="form-row">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" name="username" required placeholder="Enter username">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" name="password" required placeholder="Enter password">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Bot Limit</label>
                    <input type="number" name="bot_limit" value="0" min="0" required>
                </div>
                <div class="form-group">
                    <label>RAM Limit</label>
                    <select name="ram_limit">
                        <option value="256 MB">256 MB</option>
                        <option value="512 MB" selected>512 MB</option>
                        <option value="1 GB">1 GB</option>
                        <option value="2 GB">2 GB</option>
                        <option value="4 GB">4 GB</option>
                        <option value="8 GB">8 GB</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Storage Limit</label>
                    <select name="storage_limit">
                        <option value="512 MB">512 MB</option>
                        <option value="1 GB" selected>1 GB</option>
                        <option value="2 GB">2 GB</option>
                        <option value="5 GB">5 GB</option>
                        <option value="10 GB">10 GB</option>
                        <option value="20 GB">20 GB</option>
                    </select>
                </div>
            </div>
            <button type="submit" class="btn">➕ CREATE USER</button>
        </form>
    </div>

    <h3 style="margin-bottom: 25px; font-size: 24px; color: #00ffcc;">📋 Existing Users</h3>
    <table>
        <tr>
            <th>Username</th>
            <th>Bot Limit</th>
            <th>Current Bots</th>
            <th>RAM</th>
            <th>Storage</th>
            <th>Actions</th>
        </tr>
        {% for user in users %}
        <tr>
            <td><strong>{{ user.username }}</strong> ({% if user.username == 'SEMY' %}Admin{% endif %})</strong></td>
            <td>
                <form method="post" action="/admin/user/{{ user.username }}/setlimit" style="display: flex; gap: 10px; align-items: center;">
                    <input type="number" name="bot_limit" value="{{ user.bot_limit }}" style="width: 80px; padding: 8px;" min="0">
                    <button type="submit" class="small-btn">Set</button>
                </form>
            </td>
            <td>{{ user.bot_count }} / {{ user.bot_limit }}</td>
            <td>
                <form method="post" action="/admin/user/{{ user.username }}/setlimit" style="display: flex; gap: 10px; align-items: center;">
                    <input type="text" name="ram_limit" value="{{ user.ram }}" style="width: 90px; padding: 8px;">
                    <button type="submit" class="small-btn">Set</button>
                </form>
            </td>
            <td>
                <form method="post" action="/admin/user/{{ user.username }}/setlimit" style="display: flex; gap: 10px; align-items: center;">
                    <input type="text" name="storage_limit" value="{{ user.storage }}" style="width: 90px; padding: 8px;">
                    <button type="submit" class="small-btn">Set</button>
                </form>
            </td>
            <td class="action-buttons">
                {% if user.username != 'SEMY' %}
                <form method="post" action="/admin/user/{{ user.username }}/delete" class="delete-form" onsubmit="return confirm('Delete user {{ user.username }} and all their bots? This cannot be undone!')">
                    <button type="submit" class="small-btn danger">🗑 Delete</button>
                </form>
                {% else %}
                <span style="color: #666;">Protected</span>
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

ADMIN_BOTS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>All Bots - LAM CODEX OFCL</title>
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
        .menu {
            display: flex;
            gap: 20px;
            margin-bottom: 40px;
            flex-wrap: wrap;
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
            padding: 20px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th {
            background: rgba(255,255,255,0.05);
            color: #00ffcc;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 13px;
        }
        .status {
            padding: 8px 20px;
            border-radius: 25px;
            font-size: 12px;
            font-weight: 800;
        }
        .status.running { 
            background: rgba(0,255,204,0.2); 
            color: #00ffcc; 
            border: 1px solid #00ffcc;
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
            padding: 10px 20px;
            border-radius: 8px;
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
        }
        .flash.success { background: rgba(0,255,204,0.2); border: 1px solid #00ffcc; color: #00ffcc; }
        .flash.error { background: rgba(255,68,68,0.2); border: 1px solid #ff4444; color: #ff4444; }
        .flash.info { background: rgba(0,212,255,0.2); border: 1px solid #00d4ff; color: #00d4ff; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">🤖 ALL BOTS</div>
        <div class="nav">
            <a href="/admin/dashboard">Dashboard</a>
            <a href="/admin/users">Users</a>
            <a href="/logout">Logout</a>
        </div>
    </div>

    <div class="menu">
        <a href="/admin/dashboard">📊 Dashboard</a>
        <a href="/admin/users">👥 Users</a>
        <a href="/admin/bots">🤖 Bots</a>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash {{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <table>
        <tr>
            <th>User</th>
            <th>Bot Name</th>
            <th>Status</th>
            <th>Actions</th>
        </tr>
        {% for bot in bots %}
        <tr>
            <td><strong>{{ bot.user }}</strong></td>
            <td>{{ bot.name }}</td>
            <td>
                <span class="status {% if bot.running %}running{% else %}stopped{% endif %}">
                    {% if bot.running %}● RUNNING{% else %}○ STOPPED{% endif %}
                </span>
            </td>
            <td class="actions">
                <a href="/admin/run/{{ bot.user }}/{{ bot.name }}" style="background: rgba(0,255,136,0.2); color: #00ff88;">▶ RUN</a>
                <a href="/admin/stop/{{ bot.user }}/{{ bot.name }}" style="background: rgba(255,170,0,0.2); color: #ffaa00;">⏹ STOP</a>
                <a href="/admin/restart/{{ bot.user }}/{{ bot.name }}" style="background: rgba(0,212,255,0.2); color: #00d4ff;">🔄 RESTART</a>
                <a href="/admin/delete/{{ bot.user }}/{{ bot.name }}" style="background: rgba(255,68,68,0.2); color: #ff4444;">🗑 DELETE</a>
                <a href="/admin/download/{{ bot.user }}/{{ bot.name }}" style="background: rgba(170,136,255,0.2); color: #aa88ff;">⬇ DOWNLOAD</a>
            </td>
        </tr>
        {% else %}
        <tr>
            <td colspan="4" style="text-align: center; padding: 60px; color: #666;">No bots found</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

if __name__ == "__main__":
    # Ensure admin user exists in users.json
    users = load_users()
    if ADMIN_USERNAME not in users:
        users[ADMIN_USERNAME] = ADMIN_PASSWORD
        save_users(users)
    
    # Set admin's own limit to unlimited (999)
    set_user_bot_limit(ADMIN_USERNAME, 999)
    
    app.run(host="0.0.0.0", port=8030, debug=True, threaded=True)