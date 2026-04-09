import os
import threading
from flask import Flask, request, send_file, redirect, url_for, session, render_template_string
from werkzeug.utils import secure_filename
import telebot

# ================= AYARLAR =================
WEB_PASSWORD = "admin" # Web arayüzü giriş şifresi
WEB_PORT = 5000
BASE_DIR = "/" # Başlangıç dizini

# Telegram Ayarları
BOT_TOKEN = "BURAYA_BOT_TOKEN_YAZ"
ALLOWED_CHAT_ID = 123456789 # Kendi Telegram ID'ni GİR! (Güvenlik için kritik)

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
    </style>
</head>
<body>
    <div class="container">
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
                    <span style="float:right;">[<a href="/download?file={{ path.rstrip('/') }}/{{ file }}">İndir</a>]</span>
                </div>
                {% endfor %}
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
