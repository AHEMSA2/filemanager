import json
import io
import os
import signal
import shutil
import subprocess
import sys
import threading
import time

import psutil
import telebot
from flask import Flask, redirect, render_template_string, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from services import APService, PowerService, USBService

# ================= CONFIG =================

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def _load_config():
    if not os.path.exists(_CONFIG_PATH):
        sys.exit(
            f"[!] config.json bulunamadı: {_CONFIG_PATH}\n"
            "    Lütfen config.example.json dosyasını config.json olarak kopyalayıp doldurun.\n"
            "    cp config.example.json config.json"
        )
    with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
        try:
            cfg = json.load(fh)
        except json.JSONDecodeError as exc:
            sys.exit(f"[!] config.json geçersiz JSON: {exc}")

    errors = []
    def _require(key, expected_type):
        if key not in cfg:
            errors.append(f"  - '{key}' alanı eksik")
        elif not isinstance(cfg[key], expected_type):
            errors.append(f"  - '{key}' alanı {expected_type.__name__} olmalı, şu an: {type(cfg[key]).__name__}")

    _require("bot_token", str)
    _require("allowed_chat_id", int)
    _require("web_password", str)
    _require("web_port", int)
    _require("base_dir", str)

    def _optional(key, expected_type, default):
        if key not in cfg:
            cfg[key] = default
        elif not isinstance(cfg[key], expected_type):
            errors.append(f"  - '{key}' alanı {expected_type.__name__} olmalı, şu an: {type(cfg[key]).__name__}")

    default_usb_backup = "/srv/usb_backups" if os.name != "nt" else os.path.join(cfg.get("base_dir", "."), "usb_backups")
    _optional("usb_backup_dir", str, default_usb_backup)
    _optional("usb_auto_enabled", bool, True)
    _optional("power_min_seconds", int, 0)
    _optional("power_max_seconds", int, 86400)
    _optional("ap_enabled", bool, True)
    _optional("ap_interface", str, "auto")
    _optional("ap_ssid", str, "FileManager-AP")
    _optional("ap_password", str, "ChangeMe123")

    if isinstance(cfg.get("power_min_seconds"), int) and isinstance(cfg.get("power_max_seconds"), int):
        if cfg["power_min_seconds"] < 0 or cfg["power_max_seconds"] < cfg["power_min_seconds"]:
            errors.append("  - 'power_min_seconds' ve 'power_max_seconds' değerleri geçersiz")

    if cfg.get("ap_enabled") and isinstance(cfg.get("ap_password"), str) and len(cfg["ap_password"]) < 8:
        errors.append("  - 'ap_password' en az 8 karakter olmalı")

    if errors:
        sys.exit("[!] config.json hataları:\n" + "\n".join(errors))

    return cfg

_cfg = _load_config()

BOT_TOKEN       = _cfg["bot_token"]
ALLOWED_CHAT_ID = _cfg["allowed_chat_id"]
WEB_PASSWORD    = _cfg["web_password"]
WEB_PORT        = _cfg["web_port"]
BASE_DIR        = _cfg["base_dir"]
USB_BACKUP_DIR  = _cfg["usb_backup_dir"]
USB_AUTO_ENABLED = _cfg["usb_auto_enabled"]
POWER_MIN_SECONDS = _cfg["power_min_seconds"]
POWER_MAX_SECONDS = _cfg["power_max_seconds"]
AP_ENABLED = _cfg["ap_enabled"]
AP_INTERFACE = _cfg["ap_interface"]
AP_SSID = _cfg["ap_ssid"]
AP_PASSWORD = _cfg["ap_password"]

# ================= SABİTLER =================
MAX_CMDLINE_WEB  = 120   # web süreç listesinde gösterilecek komut karakter limiti
MAX_CMDLINE_TG   = 40    # Telegram mesajında gösterilecek komut karakter limiti
MAX_PROCESSES    = 40    # gösterilecek maksimum süreç sayısı

try:
    usb_service = USBService(USB_BACKUP_DIR, auto_enabled=USB_AUTO_ENABLED)
except OSError:
    fallback_usb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usb_backups")
    usb_service = USBService(fallback_usb_dir, auto_enabled=USB_AUTO_ENABLED)

power_service = PowerService(min_seconds=POWER_MIN_SECONDS, max_seconds=POWER_MAX_SECONDS)
ap_service = APService(enabled=AP_ENABLED, interface=AP_INTERFACE, ssid=AP_SSID, password=AP_PASSWORD)

# ================= HTML ŞABLONU =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Server Manager</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .container { max-width: 1000px; margin: 0 auto; }
        .panel { background: #161b22; padding: 15px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 20px; }
        .item { padding: 5px 0; border-bottom: 1px solid #21262d; }
        input[type="text"], input[type="password"] { background: #0d1117; color: white; border: 1px solid #30363d; padding: 5px; }
        input[type="submit"], button { background: #238636; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .btn-run { background: #9e6a03; color: white; border: none; padding: 3px 8px; cursor: pointer; font-size: 0.85em; }
        .nav-links { margin-bottom: 10px; }
        .nav-links a { margin-right: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/">📁 Dosya Yöneticisi</a>
            <a href="/processes">⚙️ Süreçler</a>
            <a href="/usb">💾 USB</a>
            <a href="/power">🔌 Güç</a>
            <a href="/ap">📡 Access Point</a>
        </div>
        <h2>Dizin: {{ path }}</h2>
        
        <div class="panel">
            <form action="/upload" method="post" enctype="multipart/form-data" style="display:inline-block; margin-right: 20px;">
                <input type="hidden" name="path" value="{{ path }}">
                <input type="file" name="file">
                <input type="submit" value="Dosya Yükle">
            </form>
            <form action="/" method="get" style="display:inline-block;">
                <input type="hidden" name="path" value="{{ path }}">
                <input type="text" name="search" placeholder="Bu dizinde ara...">
                <input type="submit" value="Ara">
            </form>
        </div>

        <div class="panel">
            <div class="item">
                <a href="?path={{ '/'.join(path.strip('/').split('/')[:-1]) or '/' }}"> [ .. Üst Dizine Dön ] </a>
            </div>
            
            {% if search_results %}
                <h3>Arama Sonuçları</h3>
                {% for res in search_results %}
                    <div class="item">🔍 <a href="?path={{ res }}">{{ res }}</a></div>
                {% endfor %}
            {% else %}
                <h3>Klasörler</h3>
                {% for folder in folders %}
                <div class="item">📁 <a href="?path={{ path.rstrip('/') }}/{{ folder }}">{{ folder }}</a></div>
                {% endfor %}

                <h3>Dosyalar</h3>
                {% for file in files %}
                <div class="item">📄 {{ file }} 
                    <span style="float:right;">
                        [<a href="/download?file={{ path.rstrip('/') }}/{{ file }}">İndir</a>]
                        &nbsp;
                        [<a href="/run_file?file={{ path.rstrip('/') }}/{{ file }}" class="btn-run" onclick="return confirm('{{ file }} çalıştırılsın mı?')">▶ Çalıştır</a>]
                    </span>
                </div>
                {% endfor %}
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

PROCESSES_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Süreçler - Server Manager</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
        a { color: #58a6ff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .container { max-width: 1200px; margin: 0 auto; }
        .panel { background: #161b22; padding: 15px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #21262d; }
        th { color: #8b949e; font-size: 0.85em; }
        .btn-kill { background: #da3633; color: white; border: none; padding: 3px 8px; cursor: pointer; font-size: 0.85em; }
        .nav-links { margin-bottom: 10px; }
        .nav-links a { margin-right: 15px; }
        input[type="text"] { background: #0d1117; color: white; border: 1px solid #30363d; padding: 5px; }
        input[type="submit"] { background: #238636; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .flash { padding: 10px; background: #1f2d1f; border: 1px solid #238636; border-radius: 4px; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/">📁 Dosya Yöneticisi</a>
            <a href="/processes">⚙️ Süreçler</a>
            <a href="/usb">💾 USB</a>
            <a href="/power">🔌 Güç</a>
            <a href="/ap">📡 Access Point</a>
        </div>
        <h2>⚙️ Çalışan Süreçler</h2>

        {% if message %}
        <div class="flash">{{ message }}</div>
        {% endif %}

        <div class="panel">
            <form method="get" action="/processes" style="margin-bottom:10px;">
                <input type="text" name="filter" value="{{ filter_text }}" placeholder="Süreç adı filtrele...">
                <input type="submit" value="Filtrele">
            </form>
            <table>
                <thead>
                    <tr><th>PID</th><th>İsim</th><th>Komut</th><th>İşlem</th></tr>
                </thead>
                <tbody>
                {% for proc in processes %}
                <tr>
                    <td>{{ proc.pid }}</td>
                    <td>{{ proc.name }}</td>
                    <td style="max-width:500px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{{ proc.cmdline }}</td>
                    <td>
                        <form method="post" action="/kill_process" style="display:inline;">
                            <input type="hidden" name="pid" value="{{ proc.pid }}">
                            <input type="hidden" name="sig" value="SIGTERM">
                            <button type="submit" class="btn-kill" onclick="return confirm('PID {{ proc.pid }} durdurulsun mu?')">Durdur</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

USB_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>USB Yönetimi - Server Manager</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
        a { color: #58a6ff; text-decoration: none; }
        .container { max-width: 1200px; margin: 0 auto; }
        .panel { background: #161b22; padding: 15px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 20px; }
        .nav-links { margin-bottom: 10px; }
        .nav-links a { margin-right: 15px; }
        .flash { padding: 10px; background: #1f2d1f; border: 1px solid #238636; border-radius: 4px; margin-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #21262d; }
        button, input[type="submit"] { background: #238636; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .btn-copy { background: #9e6a03; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/">📁 Dosya Yöneticisi</a>
            <a href="/processes">⚙️ Süreçler</a>
            <a href="/usb">💾 USB</a>
            <a href="/power">🔌 Güç</a>
            <a href="/ap">📡 Access Point</a>
        </div>
        <h2>💾 USB Yönetimi</h2>

        {% if message %}
        <div class="flash">{{ message }}</div>
        {% endif %}

        <div class="panel">
            <p>Yedek hedefi: {{ status.backup_root }}</p>
            <p>Otomatik kopyalama: <strong>{{ 'Açık' if status.auto_enabled else 'Kapalı' }}</strong></p>
            <p>İzleyici durumu: <strong>{{ 'Çalışıyor' if status.monitor_running else 'Durdu' }}</strong></p>
            <form method="post" action="/usb/toggle">
                <input type="hidden" name="enable" value="{{ 0 if status.auto_enabled else 1 }}">
                <button type="submit">{{ 'Otomatik Kopyalamayı Kapat' if status.auto_enabled else 'Otomatik Kopyalamayı Aç' }}</button>
            </form>
        </div>

        <div class="panel">
            <h3>Takılı USB Cihazları</h3>
            <table>
                <thead>
                    <tr><th>Cihaz</th><th>Mount</th><th>FS</th><th>İşlem</th></tr>
                </thead>
                <tbody>
                {% for dev in devices %}
                <tr>
                    <td>{{ dev.device }}</td>
                    <td>{{ dev.mountpoint }}</td>
                    <td>{{ dev.fstype }}</td>
                    <td>
                        <form method="post" action="/usb/copy" style="display:inline;">
                            <input type="hidden" name="mountpoint" value="{{ dev.mountpoint }}">
                            <button type="submit" class="btn-copy">Şimdi Kopyala</button>
                        </form>
                    </td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

POWER_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Güç Yönetimi - Server Manager</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
        a { color: #58a6ff; text-decoration: none; }
        .container { max-width: 1000px; margin: 0 auto; }
        .panel { background: #161b22; padding: 15px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 20px; }
        .nav-links { margin-bottom: 10px; }
        .nav-links a { margin-right: 15px; }
        .flash { padding: 10px; background: #1f2d1f; border: 1px solid #238636; border-radius: 4px; margin-bottom: 10px; }
        input[type="number"] { background: #0d1117; color: white; border: 1px solid #30363d; padding: 5px; }
        button, input[type="submit"] { background: #238636; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .btn-danger { background: #da3633; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/">📁 Dosya Yöneticisi</a>
            <a href="/processes">⚙️ Süreçler</a>
            <a href="/usb">💾 USB</a>
            <a href="/power">🔌 Güç</a>
            <a href="/ap">📡 Access Point</a>
        </div>
        <h2>🔌 Güç Yönetimi</h2>

        {% if message %}
        <div class="flash">{{ message }}</div>
        {% endif %}

        <div class="panel">
            <form method="post" action="/power/schedule" style="margin-bottom:10px;">
                <input type="hidden" name="action" value="shutdown">
                <label>Kapatma (saniye):</label>
                <input type="number" name="seconds" min="{{ status.min_seconds }}" max="{{ status.max_seconds }}" value="30">
                <input type="submit" value="Planla">
            </form>

            <form method="post" action="/power/schedule" style="margin-bottom:10px;">
                <input type="hidden" name="action" value="reboot">
                <label>Yeniden Başlatma (saniye):</label>
                <input type="number" name="seconds" min="{{ status.min_seconds }}" max="{{ status.max_seconds }}" value="30">
                <input type="submit" value="Planla">
            </form>

            <form method="post" action="/power/cancel">
                <button type="submit" class="btn-danger">Tüm Planlı Güç İşlemlerini İptal Et</button>
            </form>
        </div>

        <div class="panel">
            <h3>Planlı İşlemler</h3>
            {% if status.scheduled %}
                {% for item in status.scheduled %}
                <div>{{ item.unit }} - {{ 'Aktif' if item.active else 'Pasif' }}</div>
                {% endfor %}
            {% else %}
                <div>Aktif planlı işlem yok.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

AP_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Access Point - Server Manager</title>
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; }
        a { color: #58a6ff; text-decoration: none; }
        .container { max-width: 1000px; margin: 0 auto; }
        .panel { background: #161b22; padding: 15px; border: 1px solid #30363d; border-radius: 6px; margin-bottom: 20px; }
        .nav-links { margin-bottom: 10px; }
        .nav-links a { margin-right: 15px; }
        .flash { padding: 10px; background: #1f2d1f; border: 1px solid #238636; border-radius: 4px; margin-bottom: 10px; }
        input[type="text"], input[type="password"] { background: #0d1117; color: white; border: 1px solid #30363d; padding: 5px; }
        button, input[type="submit"] { background: #238636; color: white; border: none; padding: 5px 10px; cursor: pointer; }
        .btn-danger { background: #da3633; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/">📁 Dosya Yöneticisi</a>
            <a href="/processes">⚙️ Süreçler</a>
            <a href="/usb">💾 USB</a>
            <a href="/power">🔌 Güç</a>
            <a href="/ap">📡 Access Point</a>
        </div>
        <h2>📡 Access Point Yönetimi</h2>

        {% if message %}
        <div class="flash">{{ message }}</div>
        {% endif %}

        <div class="panel">
            <form method="post" action="/ap/start" style="margin-bottom:10px;">
                <label>SSID:</label>
                <input type="text" name="ssid" placeholder="{{ default_ssid }}">
                <label>Parola:</label>
                <input type="password" name="password" placeholder="********">
                <input type="submit" value="AP Başlat">
            </form>

            <form method="post" action="/ap/stop">
                <button type="submit" class="btn-danger">AP Durdur</button>
            </form>
        </div>

        <div class="panel">
            <h3>Durum</h3>
            <div>AP Özelliği: {{ 'Açık' if status.enabled else 'Kapalı' }}</div>
            <div>nmcli: {{ 'Var' if status.nmcli_exists else 'Yok' }}</div>
            <div>Arayüz Ayarı: {{ status.interface }}</div>
            <h4>Aktif Wi-Fi Bağlantıları</h4>
            {% if status.active_wifi %}
                {% for conn in status.active_wifi %}
                <div>{{ conn.name }} ({{ conn.device }})</div>
                {% endfor %}
            {% else %}
                <div>Aktif AP bağlantısı yok.</div>
            {% endif %}
        </div>

        <div class="panel">
            <h3>Bağlı İstemciler</h3>
            {% if clients %}
                {% for client in clients %}
                <div>{{ client }}</div>
                {% endfor %}
            {% else %}
                <div>Bağlı istemci listesi boş.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

# ================= FLASK WEB SUNUCUSU =================
app = Flask(__name__)
app.secret_key = os.urandom(24)

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == WEB_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
    return '<body style="background:#0d1117; color:white; text-align:center; padding-top:100px; font-family:monospace;"><form method="post">Şifre: <input type="password" name="password"> <input type="submit" value="Giriş"></form></body>'

@app.route('/')
@login_required
def index():
    path = request.args.get('path', BASE_DIR)
    search_query = request.args.get('search', '')
    
    files, folders, search_results = [], [], []
    
    try:
        if search_query:
            # Sadece bulunulan dizin ve bir alt seviyesinde basit arama (Kilitlenmeyi önlemek için)
            for root, dirs, filenames in os.walk(path):
                for f in filenames:
                    if search_query.lower() in f.lower():
                        search_results.append(os.path.join(root, f))
        else:
            items = os.listdir(path)
            for item in items:
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    folders.append(item)
                else:
                    files.append(item)
    except PermissionError:
        return "Erişim Engellendi", 403
    except Exception as e:
        return str(e), 500

    return render_template_string(HTML_TEMPLATE, path=path, folders=sorted(folders), files=sorted(files), search_results=search_results)

@app.route('/download')
@login_required
def download():
    file_path = request.args.get('file')
    return send_file(file_path, as_attachment=True)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    current_path = request.form['path']
    file = request.files.get('file')
    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(current_path, filename))
    return redirect(url_for('index', path=current_path))


def _launch_file(file_path):
    """Launch a file non-blocking and return process handle."""
    ext = os.path.splitext(file_path)[1].lower()
    if os.access(file_path, os.X_OK):
        cmd = [file_path]
    elif ext == ".py":
        cmd = [shutil.which("python3") or sys.executable, file_path]
    elif ext == ".sh":
        cmd = [shutil.which("bash") or "/bin/sh", file_path]
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("xdg-open bulunamadı")
        cmd = [opener, file_path]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return proc


def _resolve_user_path(chat_id, raw_path, default_to_current=False):
    current = get_upload_dir(chat_id)
    if not raw_path:
        return current if default_to_current else ""

    raw = raw_path.strip()
    if raw.startswith("~"):
        resolved = os.path.expanduser(raw)
    elif os.path.isabs(raw):
        resolved = raw
    else:
        resolved = os.path.join(current, raw)

    return os.path.abspath(os.path.normpath(resolved))


@app.route('/run_file')
@login_required
def run_file():
    file_path = request.args.get('file', '')
    if not file_path or not os.path.isfile(file_path):
        return "Dosya bulunamadı", 404
    try:
        proc = _launch_file(file_path)
        return f"Başlatıldı — PID: {proc.pid}", 200
    except Exception as exc:
        return f"Dosya başlatılamadı: {exc}", 500


def _get_processes(filter_text="", limit=MAX_PROCESSES, cmdline_limit=MAX_CMDLINE_WEB):
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            info = p.info
            cmdline = " ".join(info.get('cmdline') or [])
            name = info.get('name') or ""
            if filter_text and filter_text.lower() not in name.lower() and filter_text.lower() not in cmdline.lower():
                continue
            short_cmd = cmdline[:cmdline_limit] if cmdline_limit else cmdline
            procs.append({"pid": info['pid'], "name": name, "cmdline": short_cmd})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if limit is None:
        return procs
    return procs[:limit]


@app.route('/processes')
@login_required
def processes_page():
    filter_text = request.args.get('filter', '')
    message = request.args.get('message', '')
    procs = _get_processes(filter_text)
    return render_template_string(PROCESSES_TEMPLATE, processes=procs,
                                  filter_text=filter_text, message=message)


@app.route('/kill_process', methods=['POST'])
@login_required
def kill_process():
    pid_str = request.form.get('pid', '')
    sig_name = request.form.get('sig', 'SIGTERM')
    sig = signal.SIGKILL if sig_name == 'SIGKILL' else signal.SIGTERM
    try:
        pid = int(pid_str)
        os.kill(pid, sig)
        msg = f"PID {pid} → {sig_name} gönderildi."
    except (ValueError, ProcessLookupError, PermissionError) as exc:
        msg = f"Hata: {exc}"
    return redirect(url_for('processes_page', message=msg))


@app.route('/usb')
@login_required
def usb_page():
    message = request.args.get('message', '')
    devices = usb_service.list_mounts()
    status = usb_service.get_status()
    return render_template_string(USB_TEMPLATE, message=message, devices=devices, status=status)


@app.route('/usb/toggle', methods=['POST'])
@login_required
def usb_toggle():
    enabled = request.form.get('enable', '1') == '1'
    ok, msg = usb_service.set_auto_enabled(enabled)
    if ok and enabled:
        usb_service.start_auto_monitor()
    return redirect(url_for('usb_page', message=msg))


@app.route('/usb/copy', methods=['POST'])
@login_required
def usb_copy():
    mountpoint = request.form.get('mountpoint', '').strip()
    ok, msg = usb_service.trigger_copy(mountpoint)
    return redirect(url_for('usb_page', message=msg))


@app.route('/power')
@login_required
def power_page():
    message = request.args.get('message', '')
    status = power_service.status()
    return render_template_string(POWER_TEMPLATE, message=message, status=status)


@app.route('/power/schedule', methods=['POST'])
@login_required
def power_schedule():
    action = request.form.get('action', '').strip()
    seconds_raw = request.form.get('seconds', '0').strip()
    try:
        seconds = int(seconds_raw)
    except ValueError:
        return redirect(url_for('power_page', message='Süre sayısal olmalı.'))

    if action == 'shutdown':
        _, msg = power_service.schedule_shutdown(seconds)
    elif action == 'reboot':
        _, msg = power_service.schedule_reboot(seconds)
    else:
        msg = 'Geçersiz işlem türü.'
    return redirect(url_for('power_page', message=msg))


@app.route('/power/cancel', methods=['POST'])
@login_required
def power_cancel():
    _, msg = power_service.cancel_scheduled()
    return redirect(url_for('power_page', message=msg))


@app.route('/ap')
@login_required
def ap_page():
    message = request.args.get('message', '')
    status = ap_service.status()
    ok, clients, err = ap_service.clients()
    if not ok:
        message = (message + ' | ' if message else '') + err
    return render_template_string(
        AP_TEMPLATE,
        message=message,
        status=status,
        clients=clients,
        default_ssid=AP_SSID,
    )


@app.route('/ap/start', methods=['POST'])
@login_required
def ap_start():
    ssid = request.form.get('ssid', '').strip()
    password = request.form.get('password', '').strip()
    _, msg = ap_service.start(ssid=ssid, password=password)
    return redirect(url_for('ap_page', message=msg))


@app.route('/ap/stop', methods=['POST'])
@login_required
def ap_stop():
    _, msg = ap_service.stop()
    return redirect(url_for('ap_page', message=msg))


# ================= TELEGRAM BOT =================
bot = telebot.TeleBot(BOT_TOKEN)

# Per-chat upload directory (defaults to BASE_DIR)
upload_dirs = {}

def check_auth(message):
    return message.chat.id == ALLOWED_CHAT_ID

def get_upload_dir(chat_id):
    return upload_dirs.get(chat_id, BASE_DIR)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_auth(message): return
    bot.reply_to(message, (
        "Yönetici Paneli Aktif.\nKomutlar:\n"
        "/ls [dizin] - Klasör içeriği\n"
        "/get [dosya_yolu] - Dosya indir (relative destekli)\n"
        "/cd [dizin] - Çalışma/yükleme dizinini ayarla (örn: /cd ..)\n"
        "/run <dosya_yolu> - Dosyayı arka planda çalıştır\n"
        "/ps [filtre] - Süreçleri kısa listele\n"
        "/ps full [filtre] - Tüm süreçleri TXT olarak gönder\n"
        "/kill <pid> - Nazik sonlandırma (SIGTERM)\n"
        "/kill9 <pid> - Zorla sonlandırma (SIGKILL)\n"
        "/usb_list - Takılı USB'leri listele\n"
        "/usb_copy <mountpoint> - USB'yi anlık kopyala\n"
        "/usb_auto <on|off> - Otomatik USB kopyalama\n"
        "/usb_status - USB izleyici durumunu göster\n"
        "/shutdown <saniye> - Gecikmeli kapatma\n"
        "/reboot <saniye> - Gecikmeli yeniden başlatma\n"
        "/power_cancel - Planlı güç işlemlerini iptal et\n"
        "/power_status - Planlı güç durumu\n"
        "/ap_start [ssid] [parola] - AP başlat\n"
        "/ap_stop - AP durdur\n"
        "/ap_status - AP durumunu göster\n"
        "/ap_clients - AP istemcilerini göster\n"
        "Belge/fotoğraf gönder - Aktif dizine kaydet"
    ))

@bot.message_handler(commands=['ls'])
def list_dir(message):
    if not check_auth(message): return
    
    args = message.text.split(' ', 1)
    path = _resolve_user_path(message.chat.id, args[1] if len(args) > 1 else "", default_to_current=True)
    
    try:
        items = os.listdir(path)
        response = f"Dizin: {path}\n\n" + "\n".join(items[:50]) # İlk 50 öğeyi göster
        if len(items) > 50: response += f"\n...ve {len(items)-50} öğe daha."
        bot.reply_to(message, response)
    except Exception as e:
        bot.reply_to(message, f"Hata: {str(e)}")

@bot.message_handler(commands=['get'])
def get_file(message):
    if not check_auth(message): return
    
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /get /tam/dosya/yolu.txt")
        return
        
    file_path = _resolve_user_path(message.chat.id, args[1])
    try:
        with open(file_path, 'rb') as f:
            bot.send_document(message.chat.id, f)
    except Exception as e:
        bot.reply_to(message, f"Dosya çekilemedi: {str(e)}")

@bot.message_handler(commands=['cd'])
def change_upload_dir(message):
    if not check_auth(message): return

    args = message.text.split(' ', 1)
    if len(args) < 2:
        current = get_upload_dir(message.chat.id)
        bot.reply_to(message, f"Mevcut yükleme dizini: {current}\nKullanım: /cd /yeni/dizin")
        return

    target = _resolve_user_path(message.chat.id, args[1])
    if not os.path.isdir(target):
        bot.reply_to(message, f"Dizin bulunamadı: {target}")
        return

    upload_dirs[message.chat.id] = target
    bot.reply_to(message, f"Yükleme dizini ayarlandı: {target}")

def unique_save_path(directory, filename):
    """Return a path that does not already exist, appending a counter if needed."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1
    return candidate

@bot.message_handler(content_types=['document'])
def receive_document(message):
    if not check_auth(message): return

    target_dir = get_upload_dir(message.chat.id)
    raw_name = message.document.file_name or f"document_{message.document.file_id}"
    file_name = secure_filename(raw_name)
    save_path = unique_save_path(target_dir, file_name)
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(save_path, 'wb') as f:
            f.write(downloaded)
        bot.reply_to(message, f"Dosya kaydedildi: {save_path}")
    except Exception as e:
        bot.reply_to(message, f"Yükleme başarısız: {str(e)}")

@bot.message_handler(content_types=['photo'])
def receive_photo(message):
    if not check_auth(message): return

    target_dir = get_upload_dir(message.chat.id)
    # Use the highest-resolution photo
    photo = message.photo[-1]
    try:
        file_info = bot.get_file(photo.file_id)
        # Derive extension from the actual file path returned by Telegram
        ext = os.path.splitext(file_info.file_path)[1] or ".jpg"
        file_name = secure_filename(f"{photo.file_id}{ext}")
        save_path = unique_save_path(target_dir, file_name)
        downloaded = bot.download_file(file_info.file_path)
        with open(save_path, 'wb') as f:
            f.write(downloaded)
        bot.reply_to(message, f"Fotoğraf kaydedildi: {save_path}")
    except Exception as e:
        bot.reply_to(message, f"Yükleme başarısız: {str(e)}")


# ================= YENİ TELEGRAM KOMUTLARI =================

@bot.message_handler(commands=['run'])
def tg_run(message):
    if not check_auth(message): return
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /run /tam/dosya/yolu")
        return
    file_path = _resolve_user_path(message.chat.id, args[1])
    if not os.path.isfile(file_path):
        bot.reply_to(message, f"Dosya bulunamadı: {file_path}")
        return
    try:
        proc = _launch_file(file_path)
        bot.reply_to(message, f"✅ Başlatıldı\nPID: {proc.pid}")
    except Exception as exc:
        bot.reply_to(message, f"❌ Hata: {exc}")


@bot.message_handler(commands=['ps'])
def tg_ps(message):
    if not check_auth(message): return
    args = message.text.split(' ', 1)
    mode = "short"
    filter_text = ""
    if len(args) > 1:
        tail = args[1].strip()
        parts = tail.split(' ', 1)
        if parts[0].lower() in ("full", "txt"):
            mode = "full"
            filter_text = parts[1].strip() if len(parts) > 1 else ""
        else:
            filter_text = tail

    if mode == "full":
        procs = _get_processes(filter_text=filter_text, limit=None, cmdline_limit=None)
        if not procs:
            bot.reply_to(message, "Süreç bulunamadı.")
            return
        rows = ["PID\tNAME\tCMDLINE"]
        for p in procs:
            rows.append(f"{p['pid']}\t{p['name']}\t{p['cmdline']}")
        text = "\n".join(rows)
        bio = io.BytesIO(text.encode("utf-8", errors="replace"))
        bio.name = f"processes_{int(time.time())}.txt"
        bot.send_document(message.chat.id, bio)
        return

    procs = _get_processes(filter_text=filter_text)
    if not procs:
        bot.reply_to(message, "Süreç bulunamadı.")
        return
    lines = [f"{'PID':<7} {'İsim':<20} Komut"]
    for p in procs:
        cmd_short = p['cmdline'][:MAX_CMDLINE_TG] if p['cmdline'] else "-"
        lines.append(f"{p['pid']:<7} {p['name'][:20]:<20} {cmd_short}")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=['kill'])
def tg_kill(message):
    if not check_auth(message): return
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /kill <pid>")
        return
    try:
        pid = int(args[1].strip())
        os.kill(pid, signal.SIGTERM)
        bot.reply_to(message, f"✅ PID {pid} → SIGTERM gönderildi.")
    except Exception as exc:
        bot.reply_to(message, f"❌ Hata: {exc}")


@bot.message_handler(commands=['kill9'])
def tg_kill9(message):
    if not check_auth(message): return
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /kill9 <pid>")
        return
    try:
        pid = int(args[1].strip())
        os.kill(pid, signal.SIGKILL)
        bot.reply_to(message, f"✅ PID {pid} → SIGKILL gönderildi.")
    except Exception as exc:
        bot.reply_to(message, f"❌ Hata: {exc}")


@bot.message_handler(commands=['usb_list'])
def tg_usb_list(message):
    if not check_auth(message):
        return
    devices = usb_service.list_mounts()
    if not devices:
        bot.reply_to(message, "Takılı USB bulunamadı.")
        return
    lines = ["Takılı USB'ler:"]
    for dev in devices[:20]:
        lines.append(f"- {dev['mountpoint']} ({dev['device']})")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=['usb_copy'])
def tg_usb_copy(message):
    if not check_auth(message):
        return
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /usb_copy <mountpoint>")
        return
    mountpoint = args[1].strip()
    _, msg = usb_service.trigger_copy(mountpoint)
    bot.reply_to(message, msg)


@bot.message_handler(commands=['usb_auto'])
def tg_usb_auto(message):
    if not check_auth(message):
        return
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, "Kullanım: /usb_auto <on|off>")
        return
    mode = args[1].strip().lower()
    if mode not in ('on', 'off'):
        bot.reply_to(message, "Geçersiz değer. on/off kullan.")
        return
    enabled = mode == 'on'
    _, msg = usb_service.set_auto_enabled(enabled)
    if enabled:
        usb_service.start_auto_monitor()
    bot.reply_to(message, msg)


@bot.message_handler(commands=['usb_status'])
def tg_usb_status(message):
    if not check_auth(message):
        return
    status = usb_service.get_status()
    bot.reply_to(
        message,
        (
            f"USB auto: {'Açık' if status['auto_enabled'] else 'Kapalı'}\n"
            f"İzleyici: {'Çalışıyor' if status['monitor_running'] else 'Durdu'}\n"
            f"Aktif iş sayısı: {len(status['active_jobs'])}\n"
            f"Yedek hedefi: {status['backup_root']}"
        ),
    )


def _tg_parse_seconds(message, command_name):
    args = message.text.split(' ', 1)
    if len(args) < 2:
        bot.reply_to(message, f"Kullanım: /{command_name} <saniye>")
        return None
    try:
        return int(args[1].strip())
    except ValueError:
        bot.reply_to(message, "Süre sayısal olmalı.")
        return None


@bot.message_handler(commands=['shutdown'])
def tg_shutdown(message):
    if not check_auth(message):
        return
    seconds = _tg_parse_seconds(message, 'shutdown')
    if seconds is None:
        return
    _, msg = power_service.schedule_shutdown(seconds)
    bot.reply_to(message, msg)


@bot.message_handler(commands=['reboot'])
def tg_reboot(message):
    if not check_auth(message):
        return
    seconds = _tg_parse_seconds(message, 'reboot')
    if seconds is None:
        return
    _, msg = power_service.schedule_reboot(seconds)
    bot.reply_to(message, msg)


@bot.message_handler(commands=['power_cancel'])
def tg_power_cancel(message):
    if not check_auth(message):
        return
    _, msg = power_service.cancel_scheduled()
    bot.reply_to(message, msg)


@bot.message_handler(commands=['power_status'])
def tg_power_status(message):
    if not check_auth(message):
        return
    status = power_service.status()
    if not status['scheduled']:
        bot.reply_to(message, "Planlı güç işlemi yok.")
        return
    lines = ["Planlı güç işlemleri:"]
    for item in status['scheduled']:
        lines.append(f"- {item['unit']} ({'aktif' if item['active'] else 'pasif'})")
    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=['ap_start'])
def tg_ap_start(message):
    if not check_auth(message):
        return
    parts = message.text.split(' ')
    ssid = parts[1].strip() if len(parts) > 1 else ""
    password = parts[2].strip() if len(parts) > 2 else ""
    _, msg = ap_service.start(ssid=ssid, password=password)
    bot.reply_to(message, msg)


@bot.message_handler(commands=['ap_stop'])
def tg_ap_stop(message):
    if not check_auth(message):
        return
    _, msg = ap_service.stop()
    bot.reply_to(message, msg)


@bot.message_handler(commands=['ap_status'])
def tg_ap_status(message):
    if not check_auth(message):
        return
    status = ap_service.status()
    active_count = len(status['active_wifi'])
    bot.reply_to(
        message,
        (
            f"AP enabled: {'Evet' if status['enabled'] else 'Hayır'}\n"
            f"nmcli: {'Var' if status['nmcli_exists'] else 'Yok'}\n"
            f"Ayar arayüzü: {status['interface']}\n"
            f"Aktif Wi-Fi bağlantısı: {active_count}"
        ),
    )


@bot.message_handler(commands=['ap_clients'])
def tg_ap_clients(message):
    if not check_auth(message):
        return
    ok, clients, err = ap_service.clients()
    if not ok:
        bot.reply_to(message, f"Hata: {err}")
        return
    if not clients:
        bot.reply_to(message, "Bağlı istemci yok.")
        return
    bot.reply_to(message, "Bağlı istemciler:\n" + "\n".join(f"- {c}" for c in clients))


# ================= ÇALIŞTIRMA MANTIĞI =================
def run_flask():
    # log_output=False ile terminali kirletmesini önleyebilirsin, debug=False olmalı
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    if USB_AUTO_ENABLED:
        ok, msg = usb_service.start_auto_monitor()
        print(f"[*] {msg}")

    print(f"[*] Web arayüzü başlatılıyor... (Port: {WEB_PORT})")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    print("[*] Telegram botu dinleniyor...")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("[!] Kapatılıyor...")
