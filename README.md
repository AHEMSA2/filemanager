# filemanager

Flask web file manager + Telegram bot — ahemsa's masterpiece.

## Kurulum

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.example.json config.json
# config.json dosyasını düzenle (aşağıya bakın)

python main.py
```

## config.json Alanları

| Alan | Tür | Açıklama |
|---|---|---|
| `bot_token` | string | Telegram Bot API token (@BotFather'dan alınır) |
| `allowed_chat_id` | integer | İzin verilen tek Telegram kullanıcı/chat ID |
| `web_password` | string | Web arayüzü giriş şifresi |
| `web_port` | integer | Web sunucusu portu (varsayılan: 5000) |
| `base_dir` | string | Başlangıç dizini (varsayılan: "/") |
| `logs_dir` | string | Süreç log dosyalarının yazılacağı dizin (varsayılan: "logs") |

> **Önemli:** `config.json` ve `logs/` dizini `.gitignore` ile takip dışındadır — asla repo'ya commit etme.

## Telegram Komutları

| Komut | Açıklama |
|---|---|
| `/start` / `/help` | Yardım menüsünü göster |
| `/ls [dizin]` | Dizin içeriğini listele |
| `/get <dosya_yolu>` | Dosyayı Telegram'a gönder |
| `/cd <dizin>` | Telegram upload hedefini değiştir |
| `/run <dosya_yolu>` | Dosyayı arka planda başlat (PID + log path döner) |
| `/ps [filtre]` | Çalışan süreçleri listele (opsiyonel filtre) |
| `/kill <pid>` | Sürece SIGTERM gönder |
| `/kill9 <pid>` | Sürece SIGKILL gönder |
| Dosya/fotoğraf gönder | Aktif dizine kaydet |

## Web Arayüzü

- `/` — Dosya yöneticisi (listeleme, indirme, yükleme, arama, **▶ Çalıştır**)
- `/processes` — Çalışan süreçler + SIGTERM ile durdurma

## `/run` Komutu Davranışı

- Dosya **executable** ise doğrudan çalıştırılır.
- `.py` uzantılı dosyalar `python3` ile çalıştırılır.
- `.sh` uzantılı dosyalar `bash` ile çalıştırılır.
- Diğer uzantılar için `xdg-open` denenir.
- `subprocess.Popen` kullanılır — bloklamaz.
- stdout/stderr `logs/<pid>.log` dosyasına yazılır.

## Güvenlik Uyarıları

- `config.json` içindeki `allowed_chat_id` alanına **yalnızca kendi** Telegram ID'ni gir.
  Tüm bot komutları bu ID dışındaki kullanıcılara yanıt vermez.
- `web_password` değerini güçlü bir şifre ile değiştir.
- `bot_token` ve `config.json`'ı asla repo'ya commit etme.
- Bu araç yetkisiz sunucularda çalıştırılmamalıdır.
