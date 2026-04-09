import json
import os
import signal
import subprocess
import sys
import threading

import psutil
import telebot
from flask import Flask, redirect, render_template_string, request, send_file, session, url_for
from markupsafe import escape
from werkzeug.utils import secure_filename

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
    _require("logs_dir", str)

    if errors:
        sys.exit("[!] config.json hataları:\n" + "\n".join(errors))

    return cfg

_cfg = _load_config()

BOT_TOKEN       = _cfg["bot_token"]
ALLOWED_CHAT_ID = _cfg["allowed_chat_id"]
WEB_PASSWORD    = _cfg["web_password"]
WEB_PORT        = _cfg["web_port"]
BASE_DIR        = _cfg["base_dir"]
LOGS_DIR        = _cfg["logs_dir"]

# Logs dizinini oluştur
os.makedirs(LOGS_DIR, exist_ok=True)

# ================= SABİTLER =================
MAX_CMDLINE_WEB  = 120   # web süreç listesinde gösterilecek komut karakter limiti
MAX_CMDLINE_TG   = 40    # Telegram mesajında gösterilecek komut karakter limiti
MAX_PROCESSES    = 40    # gösterilecek maksimum süreç sayısı

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
                    <div class="item">🔍 <a href="?path={{ res_path }}">{{ res }}</a></div>
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
    """Launch a file non-blocking; return (proc, log_path) or raise."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    ext = os.path.splitext(file_path)[1].lower()
    if os.access(file_path, os.X_OK):
        cmd = [file_path]
    elif ext == ".py":
        cmd = ["python3", file_path]
    elif ext == ".sh":
        cmd = ["bash", file_path]
    else:
        cmd = ["xdg-open", file_path]

    # Placeholder log path — updated after Popen so we know the PID
    tmp_log = os.path.join(LOGS_DIR, "pending.log")
    log_fh = open(tmp_log, "w")
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh, close_fds=True)
    log_fh.close()

    log_path = os.path.join(LOGS_DIR, f"{proc.pid}.log")
    os.rename(tmp_log, log_path)
    return proc, log_path


@app.route('/run_file')
@login_required
def run_file():
    file_path = request.args.get('file', '')
    if not file_path or not os.path.isfile(file_path):
        return "Dosya bulunamadı", 404
    try:
        proc, log_path = _launch_file(file_path)
        return f"Başlatıldı — PID: {proc.pid} | Log: {escape(log_path)}", 200
    except Exception:
        return "Dosya başlatılamadı.", 500


def _get_processes(filter_text=""):
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            info = p.info
            cmdline = " ".join(info.get('cmdline') or [])
            name = info.get('name') or ""
            if filter_text and filter_text.lower() not in name.lower() and filter_text.lower() not in cmdline.lower():
                continue
            procs.append({"pid": info['pid'], "name": name, "cmdline": cmdline[:MAX_CMDLINE_WEB]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs[:MAX_PROCESSES]


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
        "/get [dosya_yolu] - Dosya indir\n"
        "/cd [dizin] - Yükleme hedef dizinini ayarla\n"
        "/run <dosya_yolu> - Dosyayı arka planda çalıştır\n"
        "/ps [filtre] - Süreçleri listele\n"
        "/kill <pid> - SIGTERM gönder\n"
        "/kill9 <pid> - SIGKILL gönder\n"
        "Belge/fotoğraf gönder - Aktif dizine kaydet"
    ))

@bot.message_handler(commands=['ls'])
def list_dir(message):
    if not check_auth(message): return
    
    args = message.text.split(' ', 1)
    path = args[1] if len(args) > 1 else BASE_DIR
    
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
        
    file_path = args[1]
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

    target = args[1].strip()
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
    file_path = args[1].strip()
    if not os.path.isfile(file_path):
        bot.reply_to(message, f"Dosya bulunamadı: {file_path}")
        return
    try:
        proc, log_path = _launch_file(file_path)
        bot.reply_to(message, f"✅ Başlatıldı\nPID: {proc.pid}\nLog: {log_path}")
    except Exception as exc:
        bot.reply_to(message, f"❌ Hata: {exc}")


@bot.message_handler(commands=['ps'])
def tg_ps(message):
    if not check_auth(message): return
    args = message.text.split(' ', 1)
    filter_text = args[1].strip() if len(args) > 1 else ""
    procs = _get_processes(filter_text)
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


# ================= ÇALIŞTIRMA MANTIĞI =================
def run_flask():
    # log_output=False ile terminali kirletmesini önleyebilirsin, debug=False olmalı
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    print(f"[*] Web arayüzü başlatılıyor... (Port: {WEB_PORT})")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    print("[*] Telegram botu dinleniyor...")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("[!] Kapatılıyor...")
