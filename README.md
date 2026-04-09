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
| `usb_backup_dir` | string | USB kopyalarının yazılacağı hedef dizin |
| `usb_auto_enabled` | bool | USB otomatik kopyalama açılış durumu |
| `power_min_seconds` | integer | Power komutları için minimum saniye |
| `power_max_seconds` | integer | Power komutları için maksimum saniye |
| `ap_enabled` | bool | Access Point özelliğini aç/kapat |
| `ap_interface` | string | AP Wi-Fi arayüzü (`auto` önerilir) |
| `ap_ssid` | string | Varsayılan Access Point adı |
| `ap_password` | string | Varsayılan Access Point parolası (en az 8 karakter) |

> **Önemli:** `config.json` içinde token/parola bulunur. Repo'ya commit etme.

## Telegram Komutları

| Komut | Açıklama |
|---|---|
| `/start` / `/help` | Yardım menüsünü göster |
| `/ls [dizin]` | Dizin içeriğini listele |
| `/get <dosya_yolu>` | Dosyayı Telegram'a gönder (relative destekli) |
| `/cd <dizin>` | Aktif çalışma/yükleme dizinini değiştir (`/cd ..` destekli) |
| `/run <dosya_yolu>` | Dosyayı arka planda başlat (PID döner) |
| `/ps [filtre]` | Çalışan süreçleri kısa listele |
| `/ps full [filtre]` | Süreçleri full TXT olarak gönder |
| `/kill <pid>` | Nazik sonlandırma (SIGTERM) |
| `/kill9 <pid>` | Zorla sonlandırma (SIGKILL) |
| `/usb_list` | Takılı USB mountpoint listesini göster |
| `/usb_copy <mountpoint>` | Belirli mountpoint için anlık kopyalama başlat |
| `/usb_auto <on|off>` | USB otomatik kopyalamayı aç/kapat |
| `/usb_status` | USB izleyici ve aktif işler durumunu göster |
| `/shutdown <saniye>` | Gecikmeli kapatma planla |
| `/reboot <saniye>` | Gecikmeli yeniden başlatma planla |
| `/power_cancel` | Planlı güç işlemlerini iptal et |
| `/power_status` | Planlı güç işlemlerinin durumunu göster |
| `/ap_start [ssid] [parola]` | Access Point başlat |
| `/ap_stop` | Access Point durdur |
| `/ap_status` | AP durumunu göster |
| `/ap_clients` | AP'ye bağlı istemcileri göster |
| Dosya/fotoğraf gönder | Aktif dizine kaydet |

## Web Arayüzü

- `/` — Dosya yöneticisi (listeleme, indirme, yükleme, arama, **▶ Çalıştır**)
- `/processes` — Çalışan süreçler + SIGTERM ile durdurma
- `/usb` — USB izleme, otomatik kopyalama toggle, manuel kopyalama
- `/power` — Zamanlanmış kapatma/yeniden başlatma + iptal
- `/ap` — Access Point başlat/durdur/durum/istemciler

## `/run` Komutu Davranışı

- Dosya **executable** ise doğrudan çalıştırılır.
- `.py` uzantılı dosyalar `python3` (yoksa mevcut interpreter) ile çalıştırılır.
- `.sh` uzantılı dosyalar `bash` ile çalıştırılır.
- Diğer uzantılar için `xdg-open` denenir.
- `subprocess.Popen` kullanılır — bloklamaz.
- stdout/stderr log dosyasına yazılmaz.

## `/ps` Komutu Davranışı

- `/ps` : kısa liste (Telegram mesajı)
- `/ps full` veya `/ps txt` : tüm süreçler TXT dosyası olarak gönderilir

## Linux Tek Tık Kurulum (Ubuntu/Debian)

```bash
sudo bash scripts/install_linux.sh
```

Bu script:

- Gerekli paketleri kurar (`python3`, `venv`, `network-manager`, `iw`)
- Uygulamayı `/opt/filemanager` altına senkronize eder
- Sanal ortam ve pip bağımlılıklarını kurar
- AP profilini NetworkManager üzerinden hazırlar
- `systemd/filemanager.service` dosyasını kurar, servisi başlatır
- `scripts/post_install_check.sh` ile sağlık kontrolü yapar

Servis yönetimi:

```bash
systemctl status filemanager
systemctl restart filemanager
journalctl -u filemanager -f
```

Not: Bu yapılandırma kararına göre servis `root` kullanıcıyla çalışır.

## Güvenlik Uyarıları

- `config.json` içindeki `allowed_chat_id` alanına **yalnızca kendi** Telegram ID'ni gir.
  Tüm bot komutları bu ID dışındaki kullanıcılara yanıt vermez.
- `web_password` değerini güçlü bir şifre ile değiştir.
- `ap_password` değerini güçlü bir şifre ile değiştir.
- `bot_token` ve `config.json`'ı asla repo'ya commit etme.
- Mevcut token açıkta kaldıysa BotFather üzerinden token rotate et.
- Bu araç yetkisiz sunucularda çalıştırılmamalıdır.
