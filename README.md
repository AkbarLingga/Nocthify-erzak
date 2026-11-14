# Nocthify — erzak

**Dynamic Island, Control Center, dan Dock ala macOS untuk Windows 7 – 11 & Linux.**
Satu tema *liquid glass* ala iOS: bening, halus, ringan.

```
            ╭──────────────────────────╮
            │ 21:26          ▮▮▮  82% │   ← Dynamic Island (hover = membesar)
            ╰──────────────────────────╯

  ╭───────────────────────────────────────────────────────╮
  │  ▦   📁  🌐  </>  📝 │ 💬  🎵  ⚙        │  🗑  │   ← Dock (pengganti taskbar)
  ╰───────────────────────────────────────────────────────╯
```

---

## ✨ Fitur

### Dynamic Island / Notch
- **Compact**: jam di kiri, baterai di kanan. Saat musik jalan muncul **bar equalizer animasi** + ikon app. Saat timer jalan muncul hitung mundur.
- **Hover → membesar** dengan animasi pegas seperti iPhone:
  - jam besar + tanggal
  - ring **Baterai / CPU / RAM**
  - **Now Playing** (Spotify, YouTube di browser apa pun, VLC, foobar, MusicBee, …) + tombol ⏮ ⏯ ⏭
  - baris **shortcut** yang bisa diatur sendiri (Files, Browser, Terminal, Screenshot, Kalkulator, Timer, Apps, Control Center, Lock, Sleep, Dark Mode, Focus, Task Manager, + shortcut custom kamu)
- **Live Activities** otomatis: HUD volume, *Charging*, *Low Battery*, timer selesai, notifikasi sistem.
- **Scroll di atas island = ubah volume.**
- 2 gaya: **Floating Island** atau **Notch** (menempel di atas layar). 2 material: **Hitam** (asli iPhone) atau **Glass**.

### Control Center
Wi-Fi (nama jaringan), Bluetooth, Focus / Do Not Disturb, Dark Mode (beneran ganti tema sistem), Night Light, Project/Mirror, Screenshot, Lock, **slider Brightness & Volume** (klik ikon speaker = mute), Now Playing, Baterai/CPU/RAM, menu Power (Sleep, Restart, Shut Down, Log Out — pakai konfirmasi).

### Dock (pengganti taskbar)
- Aplikasi **pinned + yang sedang jalan** (digabung per aplikasi) dengan titik indikator. Ikon aplikasi **tetap asli**.
- **Magnification** halus ala macOS, label nama saat hover, animasi **bounce** saat membuka app.
- Klik = buka / fokus / minimize, klik lagi saat banyak jendela = pindah antar jendela, **klik tengah = jendela baru**, **scroll di ikon = ganti jendela**.
- **Drag ikon** untuk menyusun ulang, **drag keluar dock** untuk unpin.
- Klik kanan: daftar jendela, Keep in Dock, Close, posisi (bawah/kiri/kanan), auto-hide, magnification.
- Tombol **Apps** (launcher + pencarian, pengganti Start Menu) dan **Trash**.
- Jendela yang di-maximize **berhenti di atas dock** (pakai AppBar resmi Windows).

### Lainnya
- **Settings lengkap**, semua berubah **langsung (live)** tanpa restart: tema (auto/gelap/terang), warna aksen, tingkat bening kaca, blur sistem (eksperimental), ukuran & posisi semuanya, dll.
- Hotkey global: **Alt+Shift+Space** = Apps, **Alt+Shift+C** = Control Center (bisa diganti).
- **Otomatis sembunyi saat game / video fullscreen.**
- Mulai otomatis saat komputer menyala.
- Aman: taskbar Windows **selalu kembali** saat Nocthify ditutup, dan ada tombol darurat.

---

## 🚀 Install (salin 1 baris)

### Windows 7 / 8 / 10 / 11
Buka **PowerShell** (atau `Win + R`), tempel, Enter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=3072; iex ((New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/AkbarLingga/Nocthify-by-erzak/main/install.ps1'))"
```

Installer akan otomatis:
1. mencari Python (kalau belum ada → install Python 3.12, atau **3.8.10 untuk Windows 7/8**),
2. download Nocthify ke `%LOCALAPPDATA%\Nocthify`,
3. install PyQt5 + psutil di environment terpisah (tidak mengotori sistem),
4. bikin shortcut di Start Menu, lalu langsung menjalankan.

### Linux (Ubuntu, Mint, Debian, Fedora, Arch, Manjaro, openSUSE, …)

```bash
curl -fsSL https://raw.githubusercontent.com/AkbarLingga/Nocthify-by-erzak/main/install.sh | bash
```

Lalu jalankan dengan perintah `nocthify` (atau dari menu aplikasi).

### Coba langsung dari folder ini (tanpa install)
- Windows: double-click **`run-dev.bat`**
- Install dari folder ini: double-click **`install.bat`**

---

## 🎮 Cara pakai

| Aksi | Hasil |
|---|---|
| Arahkan mouse ke island | Island membesar |
| Scroll di island | Ubah volume |
| Klik kanan island | Ganti gaya (Island/Notch, Hitam/Glass), Settings, Quit |
| Klik kanan area kosong dock | Posisi dock, auto-hide, magnification, **Show System Tray**, Settings |
| `Alt+Shift+Space` | Buka Apps (ketik untuk mencari, Enter untuk buka) |
| `Alt+Shift+C` | Buka Control Center |

Perintah baris (untuk shortcut keyboard di Linux):
```
nocthify --launcher | --control-center | --settings | --timer | --quit | --restore-taskbar
```

---

## 🆘 Taskbar Windows hilang?
Nocthify selalu mengembalikan taskbar saat ditutup. Kalau Nocthify dipaksa mati (misalnya lewat Task Manager):
- Start Menu → **Restore Windows Taskbar**, atau
- double-click **`restore-taskbar.bat`**, atau
- Settings → General → *Windows taskbar* → **Keep visible**.

Ikon tray (Wi-Fi, volume, dll.) tetap bisa dibuka lewat klik kanan dock → **Show System Tray**.

---

## ⚡ Performa
- Semua UI digambar sendiri di atas 3 jendela transparan. Tidak ada browser engine (bukan Electron).
- Tidak ada timer animasi yang jalan saat diam. CPU & RAM hanya dibaca saat panel yang menampilkannya terbuka.
- Pemakaian RAM ±55–80 MB (sudah termasuk Qt). Startup < 1 detik.
- Tanpa pywin32/comtypes: semua akses Windows lewat `ctypes` langsung.

## 🧩 Kompatibilitas

| Sistem | Status | Catatan |
|---|---|---|
| Windows 11 | ✅ | |
| Windows 10 | ✅ | |
| Windows 8 / 8.1 | ✅ | memakai Python 3.8 |
| Windows 7 SP1 | ✅ | memakai Python 3.8.10 (versi terakhir untuk Win7); Aero disarankan |
| Linux X11 (GNOME, KDE, XFCE, Cinnamon, MATE, LXQt, i3…) | ✅ | daftar jendela: `wmctrl`; media: `playerctl`; brightness: `brightnessctl` |
| Linux Wayland | ⚠️ | otomatis jalan lewat XWayland; daftar jendela terbatas di beberapa desktop |

## ⚙️ Konfigurasi
Semua tersimpan di satu file JSON (bisa diedit manual, langsung terbaca):
- Windows: `%APPDATA%\Nocthify\config.json`
- Linux: `~/.config/nocthify/config.json`

## 🗑️ Uninstall
- Windows: `powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Nocthify\app\uninstall.ps1"`
- Linux: `bash ~/.local/share/nocthify/app/uninstall.sh`

## 📁 Struktur project
```
nocthify/
  app.py              bootstrap, single-instance, hotkey, tray, autostart
  hub.py              satu-satunya tempat polling sistem (hemat), broadcast lewat signal
  config.py           settings JSON + live reload
  theme.py            palet warna, font, painter "liquid glass"
  icons.py            ikon vektor (SVG inline, tanpa file aset)
  backends/
    windows.py        Win32 via ctypes: jendela, ikon, volume (COM), media, taskbar, AppBar
    linux.py          wmctrl / pactl / playerctl / brightnessctl / .desktop
  ui/
    island.py         Dynamic Island
    dock.py           Dock
    control_center.py Control Center
    launcher.py       Apps / pencarian
    settings.py       jendela Settings
```

---
Dibuat oleh **erzak**. Lisensi MIT.
