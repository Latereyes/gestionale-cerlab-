from __future__ import annotations
import os, json, re, datetime, uuid, copy
import urllib.request
from pathlib import Path
from flask import Flask, request, redirect, url_for, flash, send_from_directory, render_template, session, jsonify
from jinja2.runtime import Undefined
from werkzeug.security import check_password_hash, generate_password_hash 
from functools import wraps
from werkzeug.utils import secure_filename
from dateutil.relativedelta import relativedelta
from packaging.version import parse as parse_version
import webbrowser
import threading
import os
from PIL import Image
from pystray import MenuItem as item
import pystray
from waitress import serve
import sys
import socket
import ctypes
import subprocess
import datetime
from datetime import timedelta
import shutil
import time  
from tkinter import Tk, Label, PhotoImage
from tkinter.ttk import Progressbar, Style
import queue
from tkinter import Tk, Label, PhotoImage, Button
# Fix di sicurezza per incompatibilità pyarrow residuo / namespace package orfano
import sys
try:
    import pyarrow
    if not hasattr(pyarrow, '__version__'):
        sys.modules['pyarrow'] = None
except Exception:
    sys.modules['pyarrow'] = None

import pandas as pd
import io
from flask import send_file
from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter


APP_VERSION = "3.0.0"  

GITHUB_REPO_OWNER = "Latereyes" 
GITHUB_REPO_NAME = "gestionale-cerlab-"

# Questo URL punta all'API per la release "più recente"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"

def get_persistent_data_dir():
    """
    Trova o crea una cartella dati permanente in AppData-Roaming.
    Questo è il posto giusto per salvare i dati creati dall'utente.
    """
    app_data_path = os.environ.get('APPDATA')
    if not app_data_path:
        # Fallback per sistemi non Windows o configurazioni strane
        app_data_path = os.path.expanduser('~')
    
    persistent_dir = Path(app_data_path) / "GestionalePreventivi"
    persistent_dir.mkdir(parents=True, exist_ok=True)
    return persistent_dir

# === Logica per selezionare la cartella dati (Sviluppo vs Produzione) ===
if "--debug" in sys.argv:
    # MODALITÀ DEBUG: Usa una cartella 'data' locale
    print(">>> INFO: Rilevato '--debug'. Utilizzo della cartella dati locale.")
    DATA_DIR = Path(__file__).parent / "data"
else:
    # MODALITÀ NORMALE/PRODUZIONE: Usa la cartella persistente in AppData
    DATA_DIR = get_persistent_data_dir()

# Le altre directory (clienti, preventivi, etc.) verranno create 
# automaticamente nel posto giusto in base alla modalità.
CLIENTS_DIR = DATA_DIR / "clienti"
QUOTES_DIR = DATA_DIR / "preventivi"
ALLEGATI_DIR = DATA_DIR / "allegati"
USERS_FILE = DATA_DIR / "users.json"
MESSAGES_FILE = DATA_DIR / "messages.json"
TASKS_FILE = DATA_DIR / "tasks.json"
PDF_LOG_FILE = DATA_DIR / "pdf_generation.log"
TAGBOX_FILE = DATA_DIR / "tagbox.json"
NOTIFICATIONS_FILE = DATA_DIR / "notifications.json"
ADMIN_TASKS_FILE = DATA_DIR / "admin_tasks.json"


# Creiamo le sottocartelle se non esistono
DATA_DIR.mkdir(parents=True, exist_ok=True)
CLIENTS_DIR.mkdir(exist_ok=True)
QUOTES_DIR.mkdir(exist_ok=True)
ALLEGATI_DIR.mkdir(exist_ok=True)
CHAT_ATTACHMENTS_DIR = DATA_DIR / "chat_attachments"
CHAT_ATTACHMENTS_DIR.mkdir(exist_ok=True)

# Definiamo il percorso scrivibile in AppData
APPDATA_DIR = os.path.join(os.environ.get('APPDATA', ''), 'gestionalepreventivi')
TEMPLATES_DIR = os.path.join(APPDATA_DIR, 'templates')

if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR)
USERS_FILE = os.path.join(APPDATA_DIR, 'users.json')
VERSION_FILE = os.path.join(APPDATA_DIR, 'version.txt')


# Il nome del file del token che leggeremo
TOKEN_FILE = DATA_DIR / "gh_token.txt"


def start_flask_server_thread():
    """Avvia solo il server Flask in un thread non bloccante."""
    setup_first_run()
    print("INFO: Avvio servizi principali dell'applicazione...")
    manage_firewall_rule(PORT)
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Apriamo il browser non appena il server parte
    webbrowser.open(DISPLAY_URL)

_TRAY_WIDGET = None

def tray_notify(message):
    """Mostra una notifica di Windows dal widget del server (se attivo). Non blocca mai la richiesta."""
    w = _TRAY_WIDGET
    if not w:
        return
    def _send():
        try:
            w.icon.notify(message[:250], "Gestionale Cerlab")
        except Exception as e:
            print(f"[tray] Notifica non inviata: {e}")
    threading.Thread(target=_send, daemon=True).start()

# --- Registro attività recenti: letto dal programma "Gestionale Notifiche" installato sugli altri PC ---
from collections import deque
_ATTIVITA_RECENTI = deque(maxlen=300)
_ATTIVITA_LOCK = threading.Lock()
_ATTIVITA_ULTIMO_ID = 0

def registra_attivita(testo, tipo="attivita", link=""):
    """Registra un evento (azione di un collega, PDF generato/fallito) per le notifiche sugli altri PC."""
    global _ATTIVITA_ULTIMO_ID
    try:
        ip = request.remote_addr
    except RuntimeError:
        ip = ""
    with _ATTIVITA_LOCK:
        _ATTIVITA_ULTIMO_ID += 1
        _ATTIVITA_RECENTI.append({"id": _ATTIVITA_ULTIMO_ID, "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                  "testo": testo, "tipo": tipo, "ip": ip, "link": link})

def annuncia(testo, tipo="attivita", link=""):
    """Registra l'evento per gli altri PC e lo mostra anche nel widget del PC server.
    Sul PC server: gli errori PDF sempre; il resto solo con 'Notifiche attività colleghi' attivo
    e se l'azione non è stata fatta proprio dal PC server."""
    registra_attivita(testo, tipo, link)
    w = _TRAY_WIDGET
    if not w:
        return
    if tipo == "pdf_errore" or (w.notifiche_attivita and not _richiesta_dal_pc_server()):
        tray_notify(testo)

def _chi():
    try:
        return session.get("user_name") or session.get("user_id") or "un utente"
    except RuntimeError:
        return "un utente"

def run_tray_icon_loop():
    """Icona nell'area di notifica (vicino all'orologio) con lo stato del server in tempo reale."""
    try:
        TrayWidget().run()
    except Exception as e:
        print(f"ERRORE: Impossibile creare l'icona nella tray. Dettagli: {e}")


class TrayWidget:
    """Widget del server nell'area di notifica di Windows.

    - icona con pallino verde/rosso in base allo stato reale del server (controllato ogni 15 s)
    - tooltip con stato, indirizzo, utenti collegati e da quanto tempo è attivo
    - menu con indirizzo copiabile, utenti collegati, cartelle dati/PDF, log e riavvio
    - notifica di Windows quando il server smette di rispondere o torna attivo, o cambia indirizzo IP
    """
    CHECK_EVERY_SECS = 15

    def __init__(self):
        self.started_at = datetime.datetime.now()
        self.online = None          # None = ancora in avvio
        self.last_error = ""
        self.lan_ip = LAN_IP
        self.notifiche_attivita = self._load_settings().get("notifiche_attivita", True)
        self.base_image = Image.open(resource_path("static/favicon.ico")).convert("RGBA").resize((64, 64))
        self.icon = pystray.Icon("Gestionale", self._image_for(None), self._tooltip(), self._menu())
        global _TRAY_WIDGET
        _TRAY_WIDGET = self

    # ---------- stato ----------
    @property
    def url(self):
        return f"http://{self.lan_ip}:{PORT}/"

    def _check_server(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as r:
                return r.status == 200, ""
        except Exception as e:
            return False, str(e)[:120]

    def _uptime(self):
        mins = int((datetime.datetime.now() - self.started_at).total_seconds() // 60)
        if mins < 60:
            return f"{mins} min"
        h, m = divmod(mins, 60)
        return f"{h} h {m} min" if h < 24 else f"{h // 24} g {h % 24} h"

    def _status_text(self):
        if self.online is None:
            return "Stato: avvio in corso..."
        return "Stato: ✔ server attivo" if self.online else "Stato: ✖ il server NON risponde"

    def _users_text(self):
        users = get_utenti_collegati()
        if not users:
            return "Nessun utente collegato"
        nomi = ", ".join(u["nome"] for u in users[:4]) + ("..." if len(users) > 4 else "")
        return f"{len(users)} collegat{'o' if len(users) == 1 else 'i'}: {nomi}"

    def _tooltip(self):
        # Windows limita il tooltip a 127 caratteri
        stato = "attivo" if self.online else ("in avvio" if self.online is None else "NON RISPONDE")
        n = len(get_utenti_collegati())
        text = f"Gestionale Cerlab v{APP_VERSION} - {stato}\n{self.url}\n{n} utent{'e' if n == 1 else 'i'} collegat{'o' if n == 1 else 'i'} - attivo da {self._uptime()}"
        return text[:127]

    def _image_for(self, online):
        img = self.base_image.copy()
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        color = (148, 163, 184) if online is None else ((22, 163, 74) if online else (220, 38, 38))
        d.ellipse((38, 38, 63, 63), fill=color, outline=(255, 255, 255), width=4)
        return img

    def _refresh(self):
        self.icon.icon = self._image_for(self.online)
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def _monitor_loop(self):
        while True:
            ok, err = self._check_server()
            was = self.online
            self.online, self.last_error = ok, err
            new_ip = get_lan_ip()
            ip_changed = new_ip != self.lan_ip and new_ip != "127.0.0.1"
            if ip_changed:
                self.lan_ip = new_ip
            try:
                self._refresh()
                if was is True and not ok:
                    self.icon.notify("Il server non risponde. Prova 'Riavvia server' dal menu dell'icona.", "Gestionale Cerlab")
                elif was is False and ok:
                    self.icon.notify("Il server è di nuovo attivo.", "Gestionale Cerlab")
                if ip_changed:
                    self.icon.notify(f"L'indirizzo del gestionale è cambiato: {self.url}", "Gestionale Cerlab")
            except Exception as e:
                print(f"[tray] Errore aggiornamento icona: {e}")
            time.sleep(self.CHECK_EVERY_SECS)

    # ---------- impostazioni (persistono tra i riavvii) ----------
    SETTINGS_FILE = DATA_DIR / "tray_settings.json"

    def _load_settings(self):
        try:
            return json.loads(self.SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _toggle_notifiche(self, icon=None, item_=None):
        self.notifiche_attivita = not self.notifiche_attivita
        try:
            self.SETTINGS_FILE.write_text(json.dumps({"notifiche_attivita": self.notifiche_attivita}), encoding="utf-8")
        except Exception as e:
            print(f"[tray] Impossibile salvare le impostazioni: {e}")
        self.icon.update_menu()

    # ---------- azioni ----------
    def _open(self, icon=None, item_=None):
        webbrowser.open(self.url)

    def _copy_url(self, icon=None, item_=None):
        try:
            subprocess.run(["clip"], input=self.url, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.icon.notify(f"Indirizzo copiato: {self.url}\nIncollalo nel browser degli altri PC.", "Gestionale Cerlab")
        except Exception as e:
            print(f"[tray] Impossibile copiare l'indirizzo: {e}")

    @staticmethod
    def _open_path(path):
        try:
            os.startfile(str(path))
        except Exception as e:
            print(f"[tray] Impossibile aprire {path}: {e}")

    @staticmethod
    def _confirm(text):
        try:
            # MB_YESNO | MB_ICONWARNING | MB_TOPMOST -> 6 = Sì
            return ctypes.windll.user32.MessageBoxW(0, text, "Gestionale Cerlab", 0x4 | 0x30 | 0x40000) == 6
        except Exception:
            return True

    def _restart(self, icon=None, item_=None):
        n = len(get_utenti_collegati())
        msg = "Riavviare il server del gestionale?"
        if n:
            msg += f"\n\n{n} utent{'e è' if n == 1 else 'i sono'} collegat{'o' if n == 1 else 'i'}: per qualche secondo non potranno lavorare."
        if self._confirm(msg):
            print("INFO: Riavvio dell'applicazione richiesto dal tray...")
            self.icon.stop()
            os.execl(sys.executable, sys.executable, *sys.argv)

    def _quit(self, icon=None, item_=None):
        n = len(get_utenti_collegati())
        msg = "Chiudere il gestionale?\n\nGli altri PC non potranno più usarlo finché non lo riavvii."
        if n:
            msg += f"\n\nIn questo momento {n} utent{'e è' if n == 1 else 'i sono'} collegat{'o' if n == 1 else 'i'}."
        if self._confirm(msg):
            self.icon.stop()
            os._exit(0)

    def _menu(self):
        M = pystray.MenuItem
        return pystray.Menu(
            M(f"Gestionale Cerlab v{APP_VERSION}", None, enabled=False),
            M(lambda i: self._status_text(), None, enabled=False),
            M(lambda i: f"Attivo da {self._uptime()}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            M("Apri Gestionale", self._open, default=True),
            M(lambda i: f"Copia indirizzo  ({self.url})", self._copy_url),
            M(lambda i: self._users_text(), None, enabled=False),
            M("Notifiche attività colleghi", self._toggle_notifiche, checked=lambda it: self.notifiche_attivita),
            pystray.Menu.SEPARATOR,
            M("Apri cartella dati", lambda i, it: self._open_path(DATA_DIR)),
            M("Apri cartella PDF", lambda i, it: self._open_path(QUOTES_DIR)),
            M("Apri log PDF", lambda i, it: self._open_path(PDF_LOG_FILE), enabled=lambda it: PDF_LOG_FILE.exists()),
            pystray.Menu.SEPARATOR,
            M("Riavvia server", self._restart),
            M("Esci", self._quit),
        )

    def run(self):
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        print("--- Il Launcher ha passato il testimone. Il programma ora attende la chiusura dal tray. ---")
        self.icon.run()  # chiamata bloccante che tiene vivo il programma

def restart_app(icon, menu_item):
    """Ferma l'icona, chiude il server e riavvia l'applicazione."""
    print("INFO: Riavvio dell'applicazione richiesto...")
    icon.stop()
    # Riavvia l'eseguibile corrente con gli stessi argomenti
    os.execl(sys.executable, sys.executable, *sys.argv)
# --- CLASSE DEL LAUNCHER (MODIFICATA PER ESSERE THREAD-SAFE) ---
# Sostituisci la vecchia classe AppLauncher e le funzioni esterne con questo blocco corretto

def login_or_local_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Verifica token PDF monouso (per browser headless nella generazione PDF)
        pdf_token = request.args.get('_pdf_token')
        quote_id = kwargs.get('quote_id', '')
        if pdf_token and verify_pdf_token(pdf_token, quote_id):
            return f(*args, **kwargs)
        # 2. Verifica sessione standard
        client_ip = request.remote_addr
        is_local_internal = (
            client_ip in ["127.0.0.1", "::1"] or 
            client_ip.startswith("192.168.") or 
            client_ip.startswith("10.") or 
            client_ip.startswith("172.")
        )
        if not session.get("logged_in") and not is_local_internal:
            flash("Effettua il login per accedere.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

class AppLauncher(Tk):
    def skip_update_check(self):
        """Imposta l'evento per segnalare di saltare il controllo aggiornamenti."""
        print("INFO: Richiesta di saltare il controllo aggiornamenti.")
        self.skip_button.config(state="disabled", text="Avvio...") # Disabilita il pulsante
        self.skip_requested.set() # Imposta l'evento

    def __init__(self):
        print("--- PASSO 2: INIZIALIZZAZIONE CLASSE AppLauncher ---")
        super().__init__()
        self.should_start_server = False
        self.title(f"{APP_NAME} - Avvio in corso...")
        self.geometry("450x250")
        self.resizable(False, False)
        self.configure(bg="#ffffff")

        try:
            icon_path = resource_path("static/favicon.ico")
            self.iconbitmap(icon_path)
        except Exception:
            print("Icona non trovata.")
        try:
            logo_path = resource_path("static/logo.png")
            self.logo_img = PhotoImage(file=logo_path)
            Label(self, image=self.logo_img, bg="#ffffff").pack(pady=(20, 10))
        except Exception:
            Label(self, text=APP_NAME, font=("Helvetica", 18, "bold"), bg="#ffffff").pack(pady=(20, 10))

        self.status_label = Label(self, text="Inizializzazione...", font=("Helvetica", 10), bg="#ffffff", fg="#333")
        self.status_label.pack(pady=5)
        style = Style(self)
        style.theme_use('clam')
        style.configure("green.Horizontal.TProgressbar", background='#28a745', troughcolor='#e0e0e0', bordercolor='#e0e0e0', lightcolor='#e0e0e0', darkcolor='#e0e0e0')
        self.progress = Progressbar(self, orient="horizontal", length=300, mode="determinate", style="green.Horizontal.TProgressbar")
        # Spostiamo il pulsante "Salta" QUI, prima della barra di progresso
        self.skip_button = Button(self, text="Salta Controllo e Avvia", command=self.skip_update_check, bg="#f0f0f0", relief="flat")
        self.skip_button.pack(pady=5)
        # E mettiamo la barra di progresso DOPO
        self.progress.pack(pady=10)
        
        self.version_label = Label(self, text=f"Versione Attuale: {APP_VERSION}", font=("Helvetica", 8), bg="#ffffff", fg="#666")
        self.version_label.pack(side="bottom", pady=5)

        self.queue = queue.Queue()
        self.skip_requested = threading.Event()
        self.process_thread = threading.Thread(target=self.run_startup_process, daemon=True)
        self.process_thread.start()
        self.after(100, self.process_queue)

    def process_queue(self):
        try:
            message = self.queue.get_nowait()
            if message[0] == 'update_status':
                _, text, value = message
                self.status_label.config(text=text)
                self.progress['value'] = value
            elif message[0] == 'update_status_button':
                new_state = message[1]
                if self.skip_button: # Controlla se il pulsante esiste
                    self.skip_button.config(state=new_state)    
            elif message[0] == 'run_action':
                action = message[1]
                if action == 'start_gestionale':
                    self.start_gestionale()
                elif action == 'run_installer':
                    installer_path = message[2]
                    self.run_installer_and_exit(installer_path)
                
                self.destroy()
        except queue.Empty:
            pass
        except Exception as e: # Aggiunto per debug
            print(f"Errore in process_queue: {e}")
        finally:
            if self.winfo_exists():
                 self.after(100, self.process_queue)

    
    def run_startup_process(self):
        """
        Controlla gli aggiornamenti con una logica di "retry"
        per dare tempo alla connessione di rete di attivarsi.
        """
        
        MAX_RETRIES = 4       # Numero massimo di tentativi (1 subito + 3)
        RETRY_DELAY_SEC = 15  # Secondi da aspettare tra i tentativi
        
        installer_path = None
        check_result = ""

        for attempt in range(MAX_RETRIES):
            # 1. Controlla se l'utente ha cliccato "Salta" nel frattempo
            if self.skip_requested.is_set():
                print("INFO: Controllo aggiornamenti saltato dall'utente.")
                break
            
            # 2. Aggiorna la UI e disabilita il pulsante durante il check
            progress = (attempt / MAX_RETRIES) * 100
            self.queue.put(('update_status_button', 'disabled'))
            if attempt == 0:
                self.queue.put(('update_status', "Ricerca aggiornamenti...", 10))
            else:
                self.queue.put(('update_status', f"Controllo aggiornamenti... (Tentativo {attempt + 1})", progress))

            # 3. Esegui il controllo
            check_result = self.check_for_updates()

            # 4. Analizza il risultato
            if isinstance(check_result, str) and check_result.endswith(".exe"):
                # CASO A: Trovato aggiornamento!
                installer_path = check_result
                break # Usciamo dal ciclo dei tentativi
            
            if check_result == "NO_UPDATE" or check_result == "FATAL_ERROR":
                # CASO B: Check OK (nessun update) o Errore Grave (token, ecc.)
                # In entrambi i casi, non ha senso riprovare.
                break # Usciamo dal ciclo dei tentativi
            
            if check_result == "NETWORK_ERROR":
                # CASO C: Errore di Rete.
                if attempt < MAX_RETRIES - 1:
                    # Non è l'ultimo tentativo, quindi aspettiamo
                    msg = f"Rete assente. Riprovo tra {RETRY_DELAY_SEC}s..."
                    self.queue.put(('update_status', msg, progress))
                    # Ri-abilita il pulsante "Salta" durante l'attesa
                    self.queue.put(('update_status_button', 'normal'))
                    
                    # Ciclo di attesa (controllando ogni secondo se l'utente "Salta")
                    for _ in range(RETRY_DELAY_SEC):
                        if self.skip_requested.is_set():
                            break
                        time.sleep(1)
                else:
                    # Era l'ultimo tentativo, ci arrendiamo
                    print("INFO: Errore di rete dopo tutti i tentativi.")
            
            # (Il ciclo for ricomincia se era NETWORK_ERROR)

        # 5. Finito il ciclo, decidiamo cosa fare
        if installer_path:
            # Trovato aggiornamento
            self.queue.put(('update_status', "Nuova versione trovata! Installazione...", 100))
            time.sleep(2)
            self.queue.put(('run_action', 'run_installer', installer_path))
        else:
            # Nessun aggiornamento, o l'utente ha saltato, o errore
            msg = "Avvio del gestionale..."
            if self.skip_requested.is_set():
                msg = "Avvio saltato dall'utente..."
            elif check_result == "NO_UPDATE":
                msg = "Nessun aggiornamento. Avvio del gestionale..."
            elif check_result == "NETWORK_ERROR":
                msg = "Offline. Avvio del gestionale..."

            self.queue.put(('update_status', msg, 100))
            time.sleep(1)
            self.queue.put(('run_action', 'start_gestionale'))
    
    def check_for_updates(self):
        """
        Controlla gli aggiornamenti da GitHub.
        Restituisce 3 possibili valori:
        - Il PERCORSO (str) dell'installer se trovato.
        - "NO_UPDATE" (str) se il check è OK ma non ci sono aggiornamenti.
        - "NETWORK_ERROR" (str) se il server non è raggiungibile.
        - "FATAL_ERROR" (str) per tutti gli altri problemi (token, file .exe mancante, ecc.)
        """
        
        # 1. Leggi il token
        try:
            with open(TOKEN_FILE, "r") as f:
                token = f.read().strip()
            if not token:
                raise FileNotFoundError
        except FileNotFoundError:
            print(f"ERRORE: File token '{TOKEN_FILE.name}' non trovato. L'aggiornamento automatico è disabilitato.")
            return "FATAL_ERROR" # Errore grave, non ha senso riprovare
        except Exception as e:
            print(f"ERRORE: Impossibile leggere il token. {e}")
            return "FATAL_ERROR"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        try:
            # 2. Chiama l'API di GitHub
            print(f"INFO: Contatto API GitHub: {GITHUB_API_URL}")
            req_manifest = urllib.request.Request(GITHUB_API_URL, headers=headers)
            with urllib.request.urlopen(req_manifest, timeout=10) as response:
                release_data = json.load(response)

            # 3. Confronta la versione
            latest_version_str = release_data.get("tag_name", "0.0.0").lstrip('v')
            if not latest_version_str:
                print("ERRORE: Il tag della release su GitHub è vuoto.")
                return "FATAL_ERROR" # Errore di configurazione

            print(f"INFO: Versione GitHub: {latest_version_str} / Versione Locale: {APP_VERSION}")
            if parse_version(latest_version_str) > parse_version(APP_VERSION):
                print(f"INFO: Nuova versione {latest_version_str} trovata.")
                
                # 4. Cerca l'asset .exe
                download_asset = None
                for asset in release_data.get("assets", []):
                    if asset.get("name", "").endswith(".exe"):
                        download_asset = asset
                        break
                
                if not download_asset:
                    print("ERRORE: Release trovata, ma nessun file .exe allegato.")
                    return "FATAL_ERROR" # Errore di configurazione
                
                download_api_url = download_asset.get("url")
                installer_filename = download_asset.get("name")
                
                if not download_api_url:
                     print("ERRORE: URL API per l'asset non trovato.")
                     return "FATAL_ERROR"

                self.queue.put(('update_status', f"Download versione {latest_version_str}...", 50))
                
                # 5. Scarica il file .exe
                updates_dir = DATA_DIR / "updates"
                updates_dir.mkdir(parents=True, exist_ok=True)
                local_installer_path = updates_dir / installer_filename

                print(f"INFO: Download di {installer_filename} in corso...")
                download_headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/octet-stream"
                }
                req_download = urllib.request.Request(download_api_url, headers=download_headers)
                
                with urllib.request.urlopen(req_download, timeout=600) as in_stream, open(local_installer_path, 'wb') as out_file:
                    shutil.copyfileobj(in_stream, out_file)
                
                print(f"INFO: Installer scaricato con successo in {local_installer_path}")
                # --- SUCCESSO: Restituisce il percorso ---
                return str(local_installer_path)
            
            else:
                print("INFO: L'applicazione è già aggiornata.")
                # --- SUCCESSO: Nessun aggiornamento ---
                return "NO_UPDATE"

        except urllib.error.URLError as e:
            # --- ERRORE DI RETE ---
            if hasattr(e, 'code') and e.code == 401:
                 print("ERRORE: Autenticazione fallita (401). Controlla il token 'gh_token.txt'.")
                 return "FATAL_ERROR" # Token sbagliato, inutile riprovare
            if hasattr(e, 'code') and e.code == 404:
                 print("INFO: Nessuna release 'latest' trovata (404).")
                 return "NO_UPDATE" # Lo trattiamo come "nessun aggiornamento"
                 
            print(f"ATTENZIONE: Impossibile contattare il server GitHub. (Sei offline?). Errore: {e}")
            return "NETWORK_ERROR"
        except Exception as e:
            # --- ERRORE GENERICO ---
            print(f"ERRORE non gestito in check_for_updates: {e}")
            return "FATAL_ERROR"

    def run_installer_and_exit(self, installer_path):
        """
        Crea un piccolo script .bat temporaneo che attende 3 secondi
        e poi lancia l'installer. Questo garantisce che l'eseguibile principale
        si sia chiuso prima che l'aggiornamento inizi.
        """
        log_dir = get_persistent_data_dir()
        log_path = log_dir / "installer_update_log.txt"
        installer_command = f'"{installer_path}" /SILENT /SP- /NORESTART /LOG="{log_path}"'

        # Contenuto dello script batch
        # timeout /t 5: attende 5 secondi
        # start "" ...: avvia l'installer
        # del "%~f0": elimina se stesso alla fine
        batch_content = f"""
        @echo off
        echo Attendo la chiusura del Gestionale... > "{log_path}"
        timeout /t 5 /nobreak > nul
        echo Avvio aggiornamento... >> "{log_path}"
        start "" {installer_command}
        del "%~f0"
        """

        try:
            # Creiamo il file .bat in una cartella temporanea di sistema
            temp_dir = os.environ.get("TEMP", os.path.expanduser("~"))
            batch_path = os.path.join(temp_dir, f"update_launcher_{uuid.uuid4().hex}.bat")
            
            with open(batch_path, "w") as f:
                f.write(batch_content)

            print(f"Creato script trampolino temporaneo: {batch_path}")

            # Avviamo lo script .bat in modo completamente indipendente e nascosto
            # CREATE_NO_WINDOW nasconde la finestra del prompt che altrimenti lampeggerebbe
            subprocess.Popen(['cmd.exe', '/c', batch_path], creationflags=subprocess.CREATE_NO_WINDOW)

        except Exception as e:
            print(f"!!! ERRORE CRITICO: Impossibile creare o lanciare lo script di aggiornamento. Errore: {e}")
            ctypes.windll.user32.MessageBoxW(0, f"Impossibile avviare il processo di aggiornamento.\n\nDettagli: {e}", "Errore Aggiornamento", 0x10)
        
        finally:
            # Usciamo immediatamente, lasciando che lo script .bat faccia il suo lavoro
            print("--- Gestionale chiuso per permettere l'aggiornamento. Il trampolino è stato lanciato. ---")
            os._exit(0)


    def start_gestionale(self):
        """Imposta il flag e avvia il thread del server Flask non bloccante."""
        self.should_start_server = True
        print("Avvio del server web in background...")
        start_flask_server_thread()

# --- FINE CLASSE DEL LAUNCHER ---


app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me"
APP_NAME = "Gestionale Preventivi"

import hmac, hashlib, time as _time

def generate_pdf_token(quote_id: str) -> str:
    """Genera un token HMAC firmato per autorizzare la stampa headless senza sessione.
    Il token ha validità di 10 minuti (600 secondi).
    Formato: <timestamp_hex>.<hmac_hex>
    """
    ts = format(int(_time.time()), 'x')  # Timestamp hex
    secret = app.config["SECRET_KEY"].encode()
    payload = f"{quote_id}:{ts}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"

def verify_pdf_token(token: str, quote_id: str, max_age: int = 600) -> bool:
    """Verifica che il token sia valido e non scaduto."""
    try:
        ts_hex, sig = token.split('.', 1)
        ts = int(ts_hex, 16)
        # Verifica scadenza
        if _time.time() - ts > max_age:
            return False
        # Verifica firma
        secret = app.config["SECRET_KEY"].encode()
        payload = f"{quote_id}:{ts_hex}".encode()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

@app.context_processor
def inject_debug_mode():
    """Rende la variabile 'debug_mode' disponibile in tutti i template."""
    return dict(debug_mode=app.config['DEBUG'])

# --- NOTE CLIENTE (pannello laterale nelle pagine di un preventivo) ---
@app.context_processor
def inject_current_quote_client():
    """Sulle pagine di un preventivo (URL con <quote_id>) espone il cliente collegato,
    usato da base.html per mostrare il pulsante "Note Cliente"."""
    quote_id = (request.view_args or {}).get("quote_id")
    if not quote_id or "user_id" not in session:
        return {}
    db = _DBSession()
    try:
        prev = db.query(_Preventivo).filter_by(numero=quote_id).first()
        if not prev or not prev.id_cliente:
            return {}
        cli = db.query(_Cliente).filter_by(id_cliente=prev.id_cliente).first()
        if not cli:
            return {}
        return dict(current_quote_id=quote_id, current_client_id=cli.id_cliente,
                    current_client_name=cli.cliente or cli.rag_sociale or cli.id_cliente)
    except Exception as e:
        print(f"[note_cliente] Errore context: {e}")
        return {}
    finally:
        db.close()


# --- INIZIO BLOCCO GESTIONE MARGINI (AGGIORNATO CON REGOLE COLORE) ---

MARGINI_FILE = DATA_DIR / "config_margini.json"

DEFAULT_MARGINI = {
    "fasce": [
        {
            "key": "economici", 
            "descrizione": "Fascia Bassa ", 
            "max_costo": 500, # <-- NUOVO LIMITE
            "pallini": {"verde": 80, "arancione": 70, "rosso": 60}, # <-- Ricarichi più alti
            "regole_colore": {
                "verde_min": 75, "verde_max": 85,        # Target Margine ~43-46%
                "arancione_min1": 65, "arancione_max1": 74,
                "arancione_min2": 86, "arancione_max2": 95
            }
        },
        {
            "key": "standard", 
            "descrizione": "Fascia Standard ", 
            "max_costo": 1500, # <-- NUOVO LIMITE
            "pallini": {"verde": 67, "arancione": 55, "rosso": 45}, # <-- Ricarichi medi (il tuo target 40% margine)
           "regole_colore": {
                "verde_min": 62, "verde_max": 72,        # Target Margine ~38-42%
                "arancione_min1": 55, "arancione_max1": 61,
                "arancione_min2": 73, "arancione_max2": 80
            }
        },
        {
            "key": "costosi", 
            "descrizione": "Fascia Alta ", 
            "max_costo": 999999,
            "pallini": {"verde": 50, "arancione": 40, "rosso": 30}, # <-- Ricarichi più bassi
           "regole_colore": {
                "verde_min": 45, "verde_max": 55,        # Target Margine ~31-35%
                "arancione_min1": 38, "arancione_max1": 44,
                "arancione_min2": 56, "arancione_max2": 65
            }
        }
    ]
}
def log_pdf_event(quote_id, message_type, message):
    """Logs an event related to PDF generation."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{quote_id}] [{message_type.upper()}] {message}\n"
    try:
        with open(PDF_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"ERRORE: Impossibile scrivere nel log PDF: {e}")

def get_browser_executable():
    """Trova il percorso dell'eseguibile di Chrome o Edge su Windows o Linux."""
    import shutil
    # 1. Controlla nel PATH
    for name in ["msedge", "chrome", "google-chrome", "chromium", "brave"]:
        found = shutil.which(name)
        if found:
            return found

    # 2. Percorsi standard di installazione su Windows
    standard_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in standard_paths:
        if os.path.isfile(p):
            return p
    return None

def load_margini_config():
    """Carica la configurazione dei margini dal DB SQLite (tabella config_margini)."""
    db = _DBSession()
    try:
        fasce_db = db.query(_ConfigMargini).all()
        if fasce_db:
            return {"fasce": [f.to_dict() for f in fasce_db]}
    except Exception:
        pass
    finally:
        db.close()
    # Fallback ai default se il DB e' vuoto
    return DEFAULT_MARGINI
# --- FINE BLOCCO GESTIONE MARGINI ---
def setup_first_run():
    """
    Controlla se i file di base (es. comuni.json) esistono nella cartella
    dati permanente. Se no, li copia dalla versione impacchettata.
    Inoltre, se rileva un DB vuoto con dati JSON V2 presenti, avvia
    automaticamente la migrazione V2 -> V3 (una sola volta).
    """
    dest_comuni_file = DATA_DIR / "comuni.json"
    if not dest_comuni_file.exists():
        print("INFO: Primo avvio, configurazione dati iniziali...")
        try:
            source_comuni_file = resource_path("data/comuni.json")
            shutil.copy2(source_comuni_file, dest_comuni_file)
            print(f"INFO: 'comuni.json' copiato in {dest_comuni_file}")
        except Exception as e:
            print(f"ERRORE CRITICO: Impossibile copiare i dati iniziali. Dettagli: {e}")

    # --- Migrazione automatica V2 -> V3 (one-shot) ---
    _run_auto_migration_if_needed()


def _run_auto_migration_if_needed():
    """
    Esegue migrate_v3_installer.py se:
    1. Il file sentinel 'migration_v3_done.flag' NON esiste (mai completata), E
    2. Esiste almeno un file JSON di clienti o preventivi in AppData.
    Se la migrazione dell'installer si e' interrotta a meta' viene ripresa: i record gia'
    presenti nel DB vengono saltati. Il sentinel lo scrive lo script solo a migrazione riuscita.
    """
    sentinel = DATA_DIR / "migration_v3_done.flag"
    if sentinel.exists():
        return  # Gia' eseguita, skip

    # Controlla se ci sono dati JSON V2 da migrare
    has_json_data = (
        any((DATA_DIR / "clienti").glob("*.json")) or
        any((DATA_DIR / "preventivi").glob("*.json")) or
        (DATA_DIR / "users.json").exists()
    )
    if not has_json_data:
        # Nessun dato V2 trovato: install fresh, segna come done
        sentinel.touch()
        return

    # Avvia la migrazione in un thread separato per non bloccare il boot del server
    print("INFO: Rilevati dati V2 da migrare. Avvio migrazione automatica V2 -> V3...")

    def _migration_thread():
        try:
            # Import diretto: funziona sia in dev che nell'EXE PyInstaller
            from migrate_v3_installer import main as run_migration
            import sys as _sys
            # Passiamo DATA_DIR come argomento simulando sys.argv
            _original_argv = _sys.argv[:]
            _sys.argv = ["migrate_v3_installer.py", str(DATA_DIR)]
            try:
                # Il flag di fine migrazione lo scrive migrate_v3_installer solo se tutto e' andato a buon fine
                if run_migration() == 0:
                    print("INFO: Migrazione V2 -> V3 completata con successo.")
                else:
                    print("ATTENZIONE: Migrazione V2 -> V3 incompleta, verra' ritentata al prossimo avvio.")
            finally:
                _sys.argv = _original_argv
        except Exception as e:
            print(f"ERRORE: Migrazione V2 -> V3 fallita: {e}")

    migration_thread = threading.Thread(target=_migration_thread, daemon=True, name="MigrazioneV3")
    migration_thread.start()
def get_installed_version():
    """Legge la versione dal file in AppData."""
    try:
        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.0"
def resource_path(relative_path):
    """ Ottiene il percorso assoluto della risorsa, funziona sia in dev che con PyInstaller """
    try:
        # PyInstaller crea una cartella temp e ci salva il percorso in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

try:
    with open(resource_path("data/comuni.json"), "r", encoding="utf-8") as f: GEO_DATA = json.load(f)
except FileNotFoundError: GEO_DATA = []; print("ATTENZIONE: File 'data/comuni.json' non trovato.")
# === A3/A4/A5: Import modelli SQLAlchemy ===
# Il DB sta nella cartella dati utente, non in quella del programma (cancellata dall'installer a ogni update).
# Nome diverso da "gestionale.db" per non riusare il vecchio DB di prova presente in alcune AppData.
os.environ.setdefault(
    "GESTIONALE_DB_PATH",
    str(DATA_DIR / ("gestionale.db" if "--debug" in sys.argv else "gestionale_v3.db"))
)
from models import (
    campi_extra as _campi_extra,
    SessionLocal as _DBSession,
    Preventivo as _Preventivo, Ordine as _Ordine, Bolla as _Bolla,
    Cliente as _Cliente,
    Utente as _Utente,
    Task as _Task, AdminTask as _AdminTask,
    Message as _Message, TagboxEntry as _TagboxEntry,
    Notification as _Notification, ConfigMargini as _ConfigMargini,
    ArticoloMagazzino as _ArticoloMagazzino, MovimentoMagazzino as _MovimentoMagazzino,
    init_db as _init_db
)
_init_db()  # Assicura che tutte le tabelle V3 esistano

# Chiavi che hanno una colonna dedicata (o una tabella collegata): tutto il resto finisce in 'extra'
_CAMPI_PREVENTIVO = set(_Preventivo.__table__.columns.keys()) | {"ordini_fornitore", "bolle"}
_CAMPI_ORDINE = set(_Ordine.__table__.columns.keys())
_CAMPI_BOLLA = set(_Bolla.__table__.columns.keys())
_CAMPI_CLIENTE = set(_Cliente.__table__.columns.keys())

def load_users():
    """Carica gli utenti dalla tabella SQLite 'utenti'."""
    db = _DBSession()
    try:
        return [u.to_dict() for u in db.query(_Utente).all()]
    except Exception:
        return []
    finally:
        db.close()

# Carichiamo il changelog (Sola lettura, resta nella cartella app)
try:
    with open(resource_path("data/changelog.json"), "r", encoding="utf-8") as f:
        CHANGELOG_DATA = json.load(f)
    # Il file puo' contenere una sola versione (oggetto) o un elenco di versioni
    if isinstance(CHANGELOG_DATA, dict):
        CHANGELOG_DATA = [CHANGELOG_DATA]
    CHANGELOG_DATA = [e for e in CHANGELOG_DATA if isinstance(e, dict) and e.get("version")]
except (FileNotFoundError, json.JSONDecodeError):
    CHANGELOG_DATA = []
    print("ATTENZIONE: File 'data/changelog.json' non trovato o corrotto.")
def save_users(users_data):
    """Salva lista di utenti nella tabella SQLite 'utenti' (upsert)."""
    db = _DBSession()
    try:
        for u in users_data:
            username = u.get("username")
            if not username:
                continue
            existing = db.query(_Utente).filter_by(username=username).first()
            if existing:
                existing.password_hash = u.get("password_hash", existing.password_hash)
                existing.full_name = u.get("full_name", existing.full_name)
                existing.role = u.get("role", existing.role)
                existing.sigla = u.get("sigla", existing.sigla)
                existing.force_password_reset = u.get("force_password_reset", False)
                existing.last_seen_version = u.get("last_seen_version", "")
            else:
                db.add(_Utente(
                    username=username,
                    password_hash=u.get("password_hash", ""),
                    full_name=u.get("full_name", ""),
                    role=u.get("role", "venditore"),
                    sigla=u.get("sigla", ""),
                    force_password_reset=u.get("force_password_reset", False),
                    last_seen_version=u.get("last_seen_version", "")
                ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_users] Errore: {e}")
    finally:
        db.close()
def get_template_path(filename):
    """Restituisce il percorso assoluto del template in AppData."""
    return os.path.join(TEMPLATES_DIR, filename)
def check_templates():
    """Verifica che i template esistano, altrimenti li ricopia dalla cartella app."""
    for template in ["modello cashflow.xlsx", "template_analisi.xlsx"]:
        dest = os.path.join(TEMPLATES_DIR, template)
        if not os.path.exists(dest):
            src = resource_path(os.path.join("data", template))
            if os.path.exists(src):
                shutil.copy(src, dest)

# Richiama la funzione all'avvio
check_templates()    

def get_all_quotes(user_role=None, full_name=None):
    """Restituisce l'elenco preventivi da SQLite, filtrato per venditore se richiesto."""
    db = _DBSession()
    try:
        q = db.query(
            _Preventivo.numero,
            _Preventivo.data,
            _Preventivo.cliente,
            _Preventivo.totale,
            _Preventivo.stato
        )
        if user_role == 'venditore' and full_name:
            q = q.filter(_Preventivo.venditore == full_name)
        results = q.order_by(_Preventivo.numero.desc()).all()
        return [
            {"numero": r.numero, "data": r.data, "cliente": r.cliente,
             "totale": r.totale, "stato": r.stato or "Bozza"}
            for r in results
        ]
    except Exception as e:
        print(f"[get_all_quotes] Errore SQLite: {e}")
        return []
    finally:
        db.close()
def get_new_quote_id(venditore_sigla):
    if not venditore_sigla: venditore_sigla = "XX"
    now = datetime.datetime.now()
    mesi_map = {1: "GN", 2: "FB", 3: "MR", 4: "AP", 5: "MG", 6: "GU", 7: "LU", 8: "AG", 9: "ST", 10: "OT", 11: "NV", 12: "DC"}
    prefix = "PREV-"; giorno = now.strftime('%d'); mese = mesi_map[now.month]; anno = now.strftime('%y'); ora = now.strftime('%I'); ampm = 'A' if now.strftime('%p') == 'AM' else 'P'; minuti = now.strftime('%M')
    return f"{prefix}{venditore_sigla.upper()}-{giorno}{mese}{anno}{ora}{ampm}{minuti}"
def load_quote(quote_id):
    """Carica un preventivo dal DB SQLite e lo restituisce come dict."""
    db = _DBSession()
    try:
        prev = db.query(_Preventivo).filter_by(numero=quote_id).first()
        if not prev:
            return None
        data = prev.to_dict()
        # Compatibilita edile: ricostruisce righe_edili da sezioni se vuote
        if data.get("tipo_preventivo") == "edile" and data.get("sezioni_edili"):
            if not data.get("righe_edili"):
                flat = []
                for s in data.get("sezioni_edili", []):
                    for r in s.get("righe", []):
                        flat.append(r)
                data["righe_edili"] = flat
        return data
    except Exception as e:
        print(f"[load_quote] Errore caricamento '{quote_id}': {e}")
        return None
    finally:
        db.close()


def save_quote(quote_id, data):
    """Salva un preventivo nel DB SQLite (upsert completo)."""
    data = aggiorna_stato_pagamento_globale(data)
    aggiorna_stato_consegna_globale(data)
    aggiorna_stato_avanzamento(data)
    # Ricostruisce righe_edili se necessario
    if data and data.get("tipo_preventivo") == "edile" and data.get("sezioni_edili"):
        flat = []
        for s in data.get("sezioni_edili", []):
            for r in s.get("righe", []):
                flat.append(r)
        data["righe_edili"] = flat

    db = _DBSession()
    try:
        prev = db.query(_Preventivo).filter_by(numero=quote_id).first()
        if not prev:
            prev = _Preventivo(numero=quote_id)
            db.add(prev)

        # Aggiorna tutti i campi scalari
        raw_no_iva = data.get("no_iva", False)
        prev.data = data.get("data", "")
        prev.venditore = data.get("venditore", "")
        prev.cliente = data.get("cliente", "")
        prev.regione = str(data.get("regione", ""))
        prev.regione_nome = data.get("regione_nome", "")
        prev.indirizzo = data.get("indirizzo", "")
        prev.email = data.get("email", "")
        prev.telefono = data.get("telefono", "")
        prev.referente = data.get("referente", "")
        prev.fee_pct = str(data.get("fee_pct", ""))
        prev.totale = str(data.get("totale", ""))
        prev.comune = data.get("comune", "")
        prev.provincia = data.get("provincia", "")
        prev.rag_sociale = data.get("rag_sociale", "")
        prev.p_iva = data.get("p_iva", "")
        prev.cap = data.get("cap", "")
        prev.stato = data.get("stato", "Bozza")
        prev.is_locked = bool(data.get("is_locked", False))
        prev.id_cliente = data.get("id_cliente")
        # V3
        prev.data_conferma = data.get("data_conferma")
        prev.no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")
        prev.tipo_preventivo = data.get("tipo_preventivo", "standard")
        prev.codice_univoco = data.get("codice_univoco", "")
        prev.iva_pct = data.get("iva_pct", "")
        prev.righe_edili = data.get("righe_edili", [])
        prev.sezioni_edili = data.get("sezioni_edili", [])
        # Calcolati
        prev.tot_imponibile_negozio = str(data.get("tot_imponibile_negozio", ""))
        prev.tot_imponibile_cliente = str(data.get("tot_imponibile_cliente", ""))
        prev.tot_iva = str(data.get("tot_iva", ""))
        prev.ricarico_medio_pct = str(data.get("ricarico_medio_pct", ""))
        prev.stato_consegna_globale = data.get("stato_consegna_globale", "")
        prev.stato_pagamento_globale = data.get("stato_pagamento_globale", "")
        prev.stato_fattura = data.get("stato_fattura", "")
        prev.data_chiusura = data.get("data_chiusura", "")
        # JSON annidati
        prev.righe = data.get("righe", [])
        prev.imponibili_iva = data.get("imponibili_iva", {})
        prev.tot_iva_dettaglio = data.get("tot_iva_dettaglio", {})
        prev.storico_pdf = data.get("storico_pdf", [])
        prev.pagamenti = data.get("pagamenti", [])
        prev.fatture_allegate = data.get("fatture_allegate", [])
        prev.extra = _campi_extra(data, _CAMPI_PREVENTIVO)
        db.flush()

        # --- Sync Ordini ---
        ordini_db_ids = {o.ordine_id for o in prev.ordini_rel}
        ordini_json = data.get("ordini_fornitore", [])
        ordini_json_ids = set()
        for ordine in ordini_json:
            oid = ordine.get("ordine_id")
            if not oid:
                import uuid as _uuid
                oid = _uuid.uuid4().hex[:8].upper()
                ordine["ordine_id"] = oid
            ordini_json_ids.add(oid)
            existing_o = db.query(_Ordine).filter_by(ordine_id=oid).first()
            if existing_o:
                existing_o.data_ordine = ordine.get("data_ordine", "")
                existing_o.azienda = ordine.get("azienda", "")
                existing_o.numero_conferma = ordine.get("numero_conferma", "")
                existing_o.importo = str(ordine.get("importo", ""))
                existing_o.importo_articoli = str(ordine.get("importo_articoli", ""))
                existing_o.importo_trasporto = str(ordine.get("importo_trasporto", ""))
                existing_o.iva_ordine = float(ordine.get("iva_ordine", 0) or 0)
                existing_o.data_arrivo = ordine.get("data_arrivo", "")
                existing_o.indici_righe = ordine.get("indici_righe", [])
                existing_o.allegati = ordine.get("allegati", [])
                existing_o.extra = _campi_extra(ordine, _CAMPI_ORDINE)
            else:
                db.add(_Ordine(
                    ordine_id=oid, preventivo_id=quote_id,
                    data_ordine=ordine.get("data_ordine", ""),
                    azienda=ordine.get("azienda", ""),
                    numero_conferma=ordine.get("numero_conferma", ""),
                    importo=str(ordine.get("importo", "")),
                    importo_articoli=str(ordine.get("importo_articoli", "")),
                    importo_trasporto=str(ordine.get("importo_trasporto", "")),
                    iva_ordine=float(ordine.get("iva_ordine", 0) or 0),
                    data_arrivo=ordine.get("data_arrivo", ""),
                    indici_righe=ordine.get("indici_righe", []),
                    allegati=ordine.get("allegati", []),
                    extra=_campi_extra(ordine, _CAMPI_ORDINE)
                ))
        # Rimuovi ordini cancellati
        for oid in ordini_db_ids - ordini_json_ids:
            db.query(_Ordine).filter_by(ordine_id=oid).delete()

        # --- Sync Bolle ---
        bolle_db = {b.id: b for b in prev.bolle_rel}
        bolle_json = data.get("bolle", [])
        bolle_json_ids = set()
        for bolla in bolle_json:
            bid = bolla.get("id")
            if not bid:
                continue
            bolle_json_ids.add(bid)
            if bid in bolle_db:
                b = bolle_db[bid]
                b.data = bolla.get("data", "")
                b.indirizzo_cantiere_id = bolla.get("indirizzo_cantiere_id", "")
                b.indici_righe = bolla.get("indici_righe", [])
                b.extra = _campi_extra(bolla, _CAMPI_BOLLA)
            else:
                db.add(_Bolla(
                    id=bid, preventivo_id=quote_id,
                    data=bolla.get("data", ""),
                    indirizzo_cantiere_id=bolla.get("indirizzo_cantiere_id", ""),
                    indici_righe=bolla.get("indici_righe", []),
                    extra=_campi_extra(bolla, _CAMPI_BOLLA)
                ))
        # Rimuovi bolle cancellate
        for bid, b in bolle_db.items():
            if bid not in bolle_json_ids:
                db.delete(b)

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_quote] Errore salvataggio '{quote_id}': {e}")
        raise
    finally:
        db.close()



def aggiorna_stato_consegna_globale(preventivo_data):
    """
    Ricalcola lo stato di consegna globale.
    """
    stato_preventivo = preventivo_data.get("stato")
    is_edile = preventivo_data.get("tipo_preventivo") == "edile"
    
    if is_edile:
        righe = get_flat_righe_edili(preventivo_data)
        if not righe:
            preventivo_data["stato_consegna_globale"] = "N/D"
            return
            
        # Consideriamo "Da Consegnare" se lo stato è nullo
        stati = {r.get("stato_consegna") or "Da Consegnare" for r in righe}
        
        if all(s == "Consegnato" for s in stati):
            preventivo_data["stato_consegna_globale"] = "Completato"
        elif any(s in ["Consegnato", "In Bolla", "Pronto per Consegna"] for s in stati):
            preventivo_data["stato_consegna_globale"] = "Parziale"
        else:
            preventivo_data["stato_consegna_globale"] = "Da Consegnare"
        return

    # 1. Trova tutti gli indici confermati (Per preventivi STANDARD)
    ordini_confermati = [
        o for o in _ordini_con_magazzino(preventivo_data)
        if o.get("numero_conferma", "").strip()
    ]
    
    indici_confermati = set()
    for o in ordini_confermati:
        indici_confermati.update(o.get("indici_righe", []))

    # --- INIZIO BLOCCO AGGIUNTO: Controllo stato ordini ---
    
    # 2a. Trova tutti gli indici delle righe valide (con un articolo)
    righe_preventivo = preventivo_data.get("righe", [])
    indici_righe_valide = {
        i for i, r in enumerate(righe_preventivo) 
        if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"
    }

    # 2b. Trova tutti gli indici già ordinati e quelli in attesa di conferma
    indici_gia_ordinati = set()
    articoli_in_attesa_conferma = 0
    ordini_fornitore = _ordini_con_magazzino(preventivo_data)
    
    for ordine in ordini_fornitore:
        indici_ordine = set(ordine.get("indici_righe", []))
        indici_gia_ordinati.update(indici_ordine)
        # Se l'ordine NON è confermato, conta i suoi articoli
        if not ordine.get("numero_conferma", "").strip():
            articoli_in_attesa_conferma += len(indici_ordine)

    # 2c. Calcola articoli ancora da ordinare
    articoli_da_ordinare_count = len(indici_righe_valide - indici_gia_ordinati)

    # 2d. Definisce lo stato "Tutto Ordinato e Confermato"
    #     Questo corrisponde allo stato "Ordinato" che desideri.
    is_tutto_ordinato_e_confermato = (articoli_da_ordinare_count == 0) and (articoli_in_attesa_conferma == 0)
    # --- FINE BLOCCO AGGIUNTO ---


    # 3. Se lo stato non è attivo OPPURE non ci sono proprio articoli confermati,
    # lo stato di consegna è Non Applicabile. (Logica originale invariata)
    if stato_preventivo in ["Bozza", "Inviato", "Annullato"] or not indici_confermati:
        preventivo_data["stato_consegna_globale"] = "N/D"
        return
        
    # 4. Controlla lo stato di consegna SOLO degli indici confermati (Logica originale invariata)
    stati_righe_confermate = set()
    
    for index in indici_confermati:
        if 0 <= index < len(righe_preventivo):
            riga = righe_preventivo[index]
            # Usa "Da Consegnare" come default se lo stato è vuoto o None
            stati_righe_confermate.add(riga.get("stato_consegna") or "Da Consegnare")

    # 5. Determina lo stato globale in base agli stati raccolti
    
    # Rimuovi None o stringhe vuote se sono finite nel set per errore
    stati_puliti = {s for s in stati_righe_confermate if s}

    # --- INIZIO BLOCCO MODIFICATO ---
    if all(s == "Consegnato" for s in stati_puliti):
        
        # Tutti gli articoli CONFERMATI sono stati consegnati.
        # ORA controlliamo se l'intero stato ordine è "Ordinato".
        if is_tutto_ordinato_e_confermato:
            # Sì, tutti gli articoli del preventivo sono ordinati, confermati E consegnati.
            preventivo_data["stato_consegna_globale"] = "Completato"
        else:
            # No, abbiamo consegnato solo gli articoli confermati, 
            # ma altri sono in attesa (da ordinare o da confermare).
            # Lo stato di consegna è quindi "Parziale".
            preventivo_data["stato_consegna_globale"] = "Parziale"

    elif all(s == "Da Consegnare" for s in stati_puliti):
        # Se TUTTI gli articoli confermati sono "Da Consegnare"
        preventivo_data["stato_consegna_globale"] = "Da Consegnare"
    else:
        # Se c'è un mix (alcuni consegnati, altri in bolla, altri da consegnare)
        preventivo_data["stato_consegna_globale"] = "Parziale"
    # --- FINE BLOCCO MODIFICATO ---
def aggiorna_stato_pagamento_globale(p):
    """
    Ricalcola il saldo correggendo:
    1. Formati numerici misti (virgola/punto).
    2. Gestione Esente IVA (usa l'imponibile come target).
    3. Supporto specifico per Preventivi Edili.
    4. [V3] Retrocompatibilita' preventivi V2 senza PAY ID.
    """
    def safe_money(val):
        """ Helper interno robusto per leggere formati moneta con simboli """
        if not val: return 0.0
        # Rimuove simboli valuta, percentuali e spazi extra
        s = re.sub(r"[€%\s]", "", str(val))
        if ',' in s:
            # Se c'è la virgola, rimuove il punto delle migliaia e usa la virgola come decimale
            s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except ValueError:
            return 0.0

    # --- GUARDIA RETROCOMPATIBILITA' V2 ---
    # Caso 1: Preventivo "Chiuso" = saldato per definizione.
    # Il workflow chiude il preventivo solo quando tutto e' a posto.
    if p.get("stato") == "Chiuso":
        def _to_ita(f):
            return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        totale_pagato_chiuso = sum(
            safe_money(pay.get("importo", "0"))
            for pay in p.get("pagamenti", [])
            if not pay.get("is_scheduled")
        )
        p["stato_pagamento_globale"] = "Saldato"
        p["totale_pagato"] = _to_ita(totale_pagato_chiuso)
        p["totale_da_saldare"] = "0,00"
        return p

    # Caso 2: Gia' "Saldato" senza pagamenti registrati = vecchio preventivo V2
    # saldato con sistema precedente all'introduzione dei PAY ID.
    if (p.get("stato_pagamento_globale") == "Saldato"
            and not p.get("pagamenti")
            and p.get("stato") not in ("Bozza", "Inviato", "Annullato")):
        def _to_ita(f):
            return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        totale_dovuto_v2 = safe_money(p.get("totale", "0"))
        p["totale_pagato"] = _to_ita(totale_dovuto_v2)
        p["totale_da_saldare"] = "0,00"
        return p
    # --- FINE GUARDIA ---

    if p.get("tipo_preventivo") == "edile":
        # Usiamo l'appiattimento per calcolare i totali globali in modo infallibile
        flat_righe = get_flat_righe_edili(p)
        tot_imp = sum(safe_money(r.get("prezzo_vendita")) for r in flat_righe)
        tot_iva = sum(safe_money(r.get("prezzo_vendita")) * (safe_money(r.get("iva_pct")) / 100) for r in flat_righe)
        
        p["tot_imponibile_cliente"] = f"{tot_imp:.2f}".replace(".", ",")
        p["tot_iva"] = f"{tot_iva:.2f}".replace(".", ",")
        p["totale"] = f"{(tot_imp + tot_iva):.2f}".replace(".", ",")
        
        # Dettaglio per aliquote
        imp_iva_map = {}
        for r in flat_righe:
            k = str(int(safe_money(r.get("iva_pct"))))
            imp_iva_map[k] = imp_iva_map.get(k, 0.0) + safe_money(r.get("prezzo_vendita"))
        p["imponibili_iva"] = {k: f"{v:.2f}".replace(".", ",") for k, v in imp_iva_map.items()}

    # 1. Determina il "Totale Dovuto" (Target)
    if p.get("no_iva") is True:
        # SE ESENTE IVA: Il cliente deve pagare solo l'imponibile!
        # Usiamo tot_imponibile_cliente se esiste, altrimenti fallback su totale
        totale_dovuto = safe_money(p.get("tot_imponibile_cliente", p.get("totale", "0")))
    else:
        # CASO NORMALE: Il cliente paga il totale (inclusa IVA)
        totale_dovuto = safe_money(p.get("totale", "0"))
    
    # 2. Somma i pagamenti effettuati (escludendo quelli ancora programmati/non confermati)
    totale_pagato = 0.0
    for pay in p.get("pagamenti", []):
        if not pay.get("is_scheduled"):
            totale_pagato += safe_money(pay.get("importo", "0"))
        
    # 3. Calcola il rimanente
    da_saldare = totale_dovuto - totale_pagato
    
    # Tolleranza di 0.05€ per arrotondamenti
    if da_saldare <= 0.05:
        da_saldare = 0.0
        nuovo_stato = "Saldato"
    else:
        nuovo_stato = "Da Saldare"
        
    # 4. Scrive i valori corretti nel JSON
    # Formattiamo alla 'italiana' per la visualizzazione
    def to_ita_str(f_val):
        return f"{f_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    p["totale_pagato"] = to_ita_str(totale_pagato)
    p["totale_da_saldare"] = to_ita_str(da_saldare)
    p["stato_pagamento_globale"] = nuovo_stato
    
    return p

def aggiorna_stato_avanzamento(preventivo_data):
    """
    Aggiorna lo stato di avanzamento del preventivo ('In Lavorazione', 'Chiuso')
    in base alla presenza di ordini, pagamenti, e allo stato di consegna/saldo.
    """
    stato_attuale = preventivo_data.get("stato")

    # MODIFICA 1: Rimuovi "Chiuso" da questo controllo.
    # Vogliamo che i preventivi chiusi vengano RIVALUTATI.
    if stato_attuale in ["Bozza", "Inviato", "Annullato"]:
        return

    # --- La logica di controllo rimane invariata ---
    is_saldato = preventivo_data.get("stato_pagamento_globale") == "Saldato"
    # MODIFICA 2: "Completato" è la chiave per chiudere
    is_consegnato_completamente = preventivo_data.get("stato_consegna_globale") == "Completato"
    is_fatturato = preventivo_data.get("stato_fattura") == "Fatturato"
    is_no_iva = preventivo_data.get("no_iva") == True
    condizione_fattura_ok = is_fatturato or is_no_iva

    # --- MODIFICA 3: Logica di Chiusura / Riapertura ---
    
    # CASO A: Le condizioni per la chiusura SONO soddisfatte
    if is_saldato and is_consegnato_completamente and condizione_fattura_ok:
        if stato_attuale != "Chiuso":
            # Mettiamo in "Chiuso" solo se non lo era già
            preventivo_data["stato"] = "Chiuso"
            preventivo_data["is_locked"] = True
            if "data_chiusura" not in preventivo_data:
                preventivo_data["data_chiusura"] = datetime.date.today().strftime('%Y-%m-%d')
        return # È chiuso e merita di esserlo.

    # CASO B: Le condizioni per la chiusura NON sono soddisfatte
    else:
        # Se NON merita di essere chiuso, ma è segnato come "Chiuso",
        # dobbiamo riaprilo e impostarlo a "In Lavorazione".
        if stato_attuale == "Chiuso":
            preventivo_data["stato"] = "In Lavorazione"
            preventivo_data["is_locked"] = True # Rimane bloccato
            preventivo_data.pop("data_chiusura", None) # Rimuovi la data di chiusura
            return

    # CASO C: Non è "Chiuso" e non merita di esserlo.
    # Controlla se deve passare da "Confermato" a "In Lavorazione"
    has_ordini = bool(preventivo_data.get("ordini_fornitore"))
    has_pagamenti = bool(preventivo_data.get("pagamenti"))
    if (has_ordini or has_pagamenti) and stato_attuale == "Confermato":
        preventivo_data["stato"] = "In Lavorazione"
        preventivo_data["is_locked"] = True 
        return
  

def get_new_client_id(): return f"CLT-{uuid.uuid4().hex[:6].upper()}"
def load_client(client_id):
    """Carica un cliente dal DB SQLite."""
    db = _DBSession()
    try:
        c = db.query(_Cliente).filter_by(id_cliente=client_id).first()
        return c.to_dict() if c else None
    except Exception as e:
        print(f"[load_client] Errore: {e}")
        return None
    finally:
        db.close()

def save_client(client_id, data):
    """Salva un cliente nel DB SQLite (upsert)."""
    db = _DBSession()
    try:
        existing = db.query(_Cliente).filter_by(id_cliente=client_id).first()
        if existing:
            existing.cliente = data.get("cliente", "")
            existing.telefono = data.get("telefono", "")
            existing.email = data.get("email", "")
            existing.regione_nome = data.get("regione_nome", "")
            existing.provincia = data.get("provincia", "")
            existing.comune = data.get("comune", "")
            existing.cap = data.get("cap", "")
            existing.indirizzo = data.get("indirizzo", "")
            existing.p_iva = data.get("p_iva", "")
            existing.rag_sociale = data.get("rag_sociale", "")
            existing.has_ci = bool(data.get("has_ci", False))
            existing.has_privacy = bool(data.get("has_privacy", False))
            existing.has_contratto = bool(data.get("has_contratto", False))
            existing.documenti_anagrafici = data.get("documenti_anagrafici", [])
            existing.extra = _campi_extra(data, _CAMPI_CLIENTE)
        else:
            db.add(_Cliente(
                id_cliente=client_id,
                cliente=data.get("cliente", ""),
                telefono=data.get("telefono", ""),
                email=data.get("email", ""),
                regione_nome=data.get("regione_nome", ""),
                provincia=data.get("provincia", ""),
                comune=data.get("comune", ""),
                cap=data.get("cap", ""),
                indirizzo=data.get("indirizzo", ""),
                p_iva=data.get("p_iva", ""),
                rag_sociale=data.get("rag_sociale", ""),
                has_ci=bool(data.get("has_ci", False)),
                has_privacy=bool(data.get("has_privacy", False)),
                has_contratto=bool(data.get("has_contratto", False)),
                documenti_anagrafici=data.get("documenti_anagrafici", []),
                extra=_campi_extra(data, _CAMPI_CLIENTE)
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_client] Errore: {e}")
    finally:
        db.close()

def find_clients_by_term(search_term):
    """Ricerca clienti per nome o ragione sociale nel DB SQLite."""
    if not search_term:
        return []
    db = _DBSession()
    try:
        term = f"%{search_term.lower()}%"
        from sqlalchemy import func
        results = db.query(_Cliente).filter(
            (func.lower(_Cliente.cliente).like(term)) |
            (func.lower(_Cliente.rag_sociale).like(term))
        ).all()
        return [c.to_dict() for c in results]
    except Exception as e:
        print(f"[find_clients_by_term] Errore: {e}")
        return []
    finally:
        db.close()
EMPTY_STATE = {"venditore": "", "numero": "", "data": "", "cliente": "", "regione": "", "regione_nome": "","indirizzo": "", "email": "", "telefono": "", "referente": "", "fee_pct": "", "iva_pct": "22 %","no_iva": False,"totale": "","riepilogo": "", "comune": "", "provincia": "", "rag_sociale": "", "p_iva": "", "cap": "", "righe": [], "stato": "Bozza", "is_locked": False,
  "ordini_fornitore": []}
def money_ui(value):
    if value is None or isinstance(value, Undefined) or str(value).strip() == "": return ""
    try: num = float(str(value).replace(",", ".")); return f"{num:.2f}".replace(".", ",") + " €"
    except (ValueError, TypeError): return ""
app.jinja_env.globals["money_ui"] = money_ui
app.jinja_env.filters["money_ui"] = money_ui

def today_date_filter(value):
    return datetime.date.today().strftime('%Y-%m-%d')

# Registra il nuovo filtro nell'ambiente Jinja
app.jinja_env.filters['today_date'] = today_date_filter

def data_it_filter(value):
    """Converte 'YYYY-MM-DD' in 'DD/MM/YYYY' (lascia invariato tutto il resto)."""
    try:
        return datetime.datetime.strptime(str(value)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return value or ""
app.jinja_env.filters['data_it'] = data_it_filter
app.jinja_env.globals['enumerate'] = enumerate

def _str_to_date(date_str):
    """Converte una stringa 'YYYY-MM-DD' in oggetto date. Ritorna None se fallisce."""
    try:
        if not date_str: return None
        return datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

### LOGIN, LOGOUT E SICUREZZA ###
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        users = load_users()
        user_found = next((u for u in users if u["username"] == username), None)
        if user_found and check_password_hash(user_found["password_hash"], password):
            next_url = session.get("next_url", "")
            # Cancella la vecchia sessione, inclusi i nostri "segnali"
            session.clear() 
            session["user_id"] = user_found["username"]
            session["user_name"] = user_found["full_name"]
            session["user_role"] = user_found["role"]
            session["user_sigla"] = user_found.get("sigla", "XX")
            session["force_password_reset"] = user_found.get("force_password_reset", False)
            lega_utente_al_pc(request.remote_addr, user_found["username"], user_found["full_name"])

            flash(f"Benvenuto, {user_found['full_name']}!", "success")
            
            # Torna alla pagina richiesta prima del login (solo percorsi interni), altrimenti dashboard
            if next_url.startswith("/") and not next_url.startswith("//") and not session["force_password_reset"]:
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        else:
            flash("Credenziali non valide. Riprova.", "error")
# --------------------------------------------------

    return render_template("login.html", app_version=APP_VERSION)

@app.route("/logout", methods=['GET', 'POST'])
def logout():
    if "user_id" in session:
        stacca_utente_dal_pc(request.remote_addr, session["user_id"])
    session.clear()
    return redirect(url_for("login"))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.method == "GET":
                session["next_url"] = request.full_path
            return redirect(url_for("login"))
        # NUOVO: Controlla se l'utente deve cambiare password
        if session.get("force_password_reset") and request.endpoint != 'cambia_password':
            flash("Per favore, imposta una nuova password.", "warning")
            return redirect(url_for("cambia_password"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    """Decorator per limitare l'accesso a ruoli specifici."""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("user_role") not in roles:
                flash("Accesso non autorizzato.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper
@app.route('/ack_changelog', methods=['POST'])
def ack_changelog():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non loggato'}), 401
    
    installed_ver = get_installed_version()
    users = load_users()
    updated = False
    
    for u in users:
        if u['username'] == session['user_id']:
            u['last_seen_version'] = installed_ver
            updated = True
            break
    
    if updated:
        save_users(users)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Utente non trovato'})

# --- File: gestionale.py (Intorno alla riga 515) ---
@app.route("/changelog")
@login_required
def changelog():
    """Mostra la pagina con tutte le novità, senza filtri di lettura."""
    # Ordiniamo tutto il changelog per versione decrescente
    updates_to_show = sorted(CHANGELOG_DATA, key=lambda x: parse_version(x['version']), reverse=True)
        
    return render_template("changelog.html", title="Novità", changelog_updates=updates_to_show)
# --------------------------------------------------

@app.route("/mark-changelog-as-seen")
@login_required
def mark_changelog_as_seen():
    """Aggiorna la versione vista dall'utente e lo reindirizza alla dashboard."""
    users = load_users()
    
    # Trova la versione più alta presente nel changelog.json
    if CHANGELOG_DATA:
        latest_json_version = max([entry['version'] for entry in CHANGELOG_DATA], key=parse_version)
    else:
        latest_json_version = APP_VERSION

    user_updated = False
    for user in users:
        if user["username"] == session["user_id"]:
            # Aggiorna alla versione effettiva letta nel changelog
            user["last_seen_version"] = latest_json_version
            user_updated = True
            break
    
    if user_updated:
        save_users(users)
        flash("Novità contrassegnate come lette.", "success")
    return redirect(url_for("dashboard"))

@app.before_request
def make_session_permanent_and_timed():
    session.permanent = True
    # La sessione scadrà dopo 1 ore di completa inattività
    app.permanent_session_lifetime = timedelta(hours=1)
    # Questa riga resetta il timer ad ogni azione dell'utente
    session.modified = True

# --- Utenti collegati (mostrati nel widget del server vicino all'orologio) ---
_UTENTI_ATTIVITA = {}   # user_id -> {"nome", "ip", "ts"}
_UTENTI_ATTIVITA_LOCK = threading.Lock()

@app.before_request
def traccia_utente_collegato():
    if request.endpoint in (None, "static", "health") or "user_id" not in session:
        return
    with _UTENTI_ATTIVITA_LOCK:
        _UTENTI_ATTIVITA[session["user_id"]] = {
            "nome": session.get("user_name") or session["user_id"],
            "ip": request.remote_addr,
            "ts": time.time(),
        }
    # Le richieste automatiche delle pagine aperte (GET /api/...: badge, chat, notifiche) non contano:
    # solo un'azione vera "lega" l'utente al PC, così una scheda dimenticata aperta non lo ricollega.
    if request.method != "GET" or not request.path.startswith("/api/"):
        lega_utente_al_pc(request.remote_addr, session["user_id"], session.get("user_name"))

# --- Chi sta usando il gestionale su ciascun PC ---
# Il programma "Gestionale Notifiche" mostra chat e notifiche di questo utente, non di chi lo ha installato:
# se sullo stesso PC lavorano più persone, i messaggi seguono chi ha fatto l'ultima azione nel gestionale.
_UTENTE_DEL_PC = {}               # chiave PC -> {"user", "nome", "ts"}
UTENTE_DEL_PC_MAX_ORE = 12        # dopo una giornata senza usare il gestionale il PC torna "libero"

def _chiave_pc(ip):
    """Il PC server arriva come 127.0.0.1 o con l'IP di rete: è sempre lo stesso PC."""
    return "server" if ip in ("127.0.0.1", "::1", LAN_IP) else (ip or "")

def lega_utente_al_pc(ip, username, nome=None):
    with _UTENTI_ATTIVITA_LOCK:
        _UTENTE_DEL_PC[_chiave_pc(ip)] = {"user": username, "nome": nome or username, "ts": time.time()}

def utente_del_pc(ip):
    """Username di chi sta usando il gestionale dal PC con questo IP, oppure None."""
    with _UTENTI_ATTIVITA_LOCK:
        info = _UTENTE_DEL_PC.get(_chiave_pc(ip))
    if not info or time.time() - info["ts"] > UTENTE_DEL_PC_MAX_ORE * 3600:
        return None
    return info["user"]

def stacca_utente_dal_pc(ip, username=None):
    """Il PC non è più di nessuno (uscita dal gestionale, PC bloccato o inattivo)."""
    with _UTENTI_ATTIVITA_LOCK:
        info = _UTENTE_DEL_PC.get(_chiave_pc(ip))
        if info and (username is None or info["user"] == username):
            del _UTENTE_DEL_PC[_chiave_pc(ip)]

def get_utenti_collegati(minuti=10):
    """Utenti che hanno usato il gestionale negli ultimi `minuti` minuti (i più recenti prima)."""
    limite = time.time() - minuti * 60
    with _UTENTI_ATTIVITA_LOCK:
        attivi = [dict(v, user_id=k) for k, v in _UTENTI_ATTIVITA.items() if v["ts"] >= limite]
    return sorted(attivi, key=lambda u: u["ts"], reverse=True)

# --- Notifiche attività nel widget del server ---
# endpoint -> testo (formattato con: chi, q = numero preventivo, cliente, importo)
_NOTIFICHE_ATTIVITA = {
    "nuovo_preventivo":        "📝 {chi} ha creato un nuovo preventivo",
    "nuovo_preventivo_edile":  "📝 {chi} ha creato un nuovo preventivo edile",
    "clona_preventivo":        "📝 {chi} ha clonato il preventivo {q}",
    "conferma_preventivo":     "🎉 {chi} ha confermato il preventivo {q}{cliente}",
    "annulla_preventivo":      "🚫 {chi} ha annullato il preventivo {q}{cliente}",
    "sblocca_preventivo":      "🔓 {chi} ha riportato in Bozza il preventivo {q}{cliente}",
    "aggiungi_pagamento":      "💶 {chi} ha registrato un pagamento{importo} sul preventivo {q}{cliente}",
    "conferma_incasso":        "💶 {chi} ha confermato un incasso sul preventivo {q}{cliente}",
    "rettifica_pagamento":     "💶 {chi} ha rettificato un pagamento sul preventivo {q}{cliente}",
    "crea_bolla":              "🚚 {chi} ha creato una bolla per il preventivo {q}{cliente}",
    "marca_pronto":            "📦 {chi} ha segnato merce pronta per la consegna ({q}{cliente})",
    "marca_consegnato":        "✅ {chi} ha segnato merce consegnata ({q}{cliente})",
    "salva_ordine":            "🛒 {chi} ha creato un ordine fornitore per il preventivo {q}{cliente}",
    "aggiungi_a_ordine":       "🛒 {chi} ha aggiunto articoli a un ordine fornitore ({q}{cliente})",
    "allega_fattura":          "🧾 {chi} ha allegato una fattura al preventivo {q}{cliente}",
    "crea_cliente":            "👤 {chi} ha creato un nuovo cliente",
}

def _richiesta_dal_pc_server():
    return request.remote_addr in ("127.0.0.1", "::1", LAN_IP)

@app.after_request
def notifica_attivita_nel_widget(response):
    """Avvisa con una notifica di Windows (sul PC del server) quando un collega fa un'azione importante."""
    try:
        testo = _NOTIFICHE_ATTIVITA.get(request.endpoint)
        if not testo or response.status_code >= 400:
            return response
        if request.method != "POST" and request.endpoint not in ("nuovo_preventivo", "nuovo_preventivo_edile", "clona_preventivo"):
            return response
        # Azione rifiutata? (risposta JSON con errore oppure messaggio flash di errore)
        if response.is_json:
            dati = response.get_json(silent=True) or {}
            if dati.get("success") is False or dati.get("error"):
                return response
        if any(cat == "error" for cat, _ in session.get("_flashes", [])):
            return response
        q = (request.view_args or {}).get("quote_id", "")
        cliente, link = "", "/"
        if q:
            db = _DBSession()
            try:
                prev = db.query(_Preventivo).filter_by(numero=q).first()
                cliente = f" - {prev.cliente}" if prev and prev.cliente else ""
                edile = bool(prev and prev.tipo_preventivo == "edile")
            finally:
                db.close()
            ep = request.endpoint
            if ep in ("aggiungi_pagamento", "conferma_incasso", "rettifica_pagamento"):
                link = url_for("gestione_pagamenti", quote_id=q)
            elif ep in ("crea_bolla", "marca_pronto", "marca_consegnato"):
                link = url_for("gestione_consegna", quote_id=q)
            elif ep in ("salva_ordine", "aggiungi_a_ordine"):
                link = url_for("conferma_ordine", quote_id=q)
            elif ep == "allega_fattura":
                link = url_for("editor_fattura", quote_id=q)
            else:
                link = url_for("editor_preventivo_edile" if edile else "editor_preventivo", quote_id=q)
        importo = request.form.get("importo", "").strip() if request.endpoint == "aggiungi_pagamento" else ""
        annuncia(testo.format(chi=_chi(), q=q, cliente=cliente, importo=f" di {importo} €" if importo else ""), link=link)
    except Exception as e:
        print(f"[tray] Errore notifica attività: {e}")
    return response

def _ip_rete_locale(ip):
    ip = ip or ""
    return ip in ("127.0.0.1", "::1") or ip.startswith(("192.168.", "10.", "172."))

@app.route("/api/attivita")
def api_attivita():
    """Eventi recenti per il programma "Gestionale Notifiche" degli altri PC (solo rete locale).
    ?dopo=<id> restituisce gli eventi successivi; senza parametro solo l'ultimo id (nessun arretrato)."""
    if not _ip_rete_locale(request.remote_addr):
        return jsonify({"error": "Accesso consentito solo dalla rete locale"}), 403
    try:
        dopo = int(request.args.get("dopo", "0"))
    except ValueError:
        dopo = 0
    with _ATTIVITA_LOCK:
        ultimo = _ATTIVITA_ULTIMO_ID
        eventi = [e for e in _ATTIVITA_RECENTI if e["id"] > dopo] if "dopo" in request.args else []
    return jsonify({"app": "Gestionale Cerlab", "version": APP_VERSION, "ultimo_id": ultimo,
                    "eventi": eventi, "tuo_ip": request.remote_addr,
                    "utenti_collegati": len(get_utenti_collegati())})

def _percorso_programma_notifiche():
    nome = "GestionaleNotifiche.exe"
    candidati = [Path(sys.executable).parent / nome, Path(__file__).parent / "dist" / "Gestionale" / nome,
                 Path(__file__).parent / "dist" / nome]
    return next((c for c in candidati if c.is_file()), None)

@app.route("/notifiche/scarica")
@login_required
def scarica_programma_notifiche():
    """Scarica il programma che mostra le notifiche del gestionale sugli altri PC."""
    exe = _percorso_programma_notifiche()
    if not exe:
        flash("Il programma notifiche non è incluso in questa installazione.", "error")
        return redirect(request.referrer or url_for("dashboard"))
    return send_from_directory(exe.parent, exe.name, as_attachment=True)

# --- API per il programma "Gestionale Notifiche" (widget sui PC): accesso con token personale ---
WIDGET_TOKENS_FILE = DATA_DIR / "widget_tokens.json"
_WIDGET_TOKENS_LOCK = threading.Lock()

def _widget_tokens():
    try:
        return json.loads(WIDGET_TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _widget_autorizzato():
    """Il widget ha un token valido (header X-Widget-Token): il PC è stato abilitato con un accesso."""
    token = request.headers.get("X-Widget-Token", "")
    return bool(token) and hashlib.sha256(token.encode()).hexdigest() in _widget_tokens()

def _widget_user():
    """Utente di cui il widget mostra messaggi e notifiche: chi sta usando il gestionale da quel PC
    (non chi ha fatto l'accesso al widget), oppure None se in questo momento nessuno lo sta usando."""
    username = utente_del_pc(request.remote_addr)
    return next((u for u in load_users() if u["username"] == username), None) if username else None

def _widget_risposta_non_autorizzato():
    return jsonify({"ok": False, "error": "non_autorizzato"}), 401

@app.route("/api/widget/login", methods=["POST"])
def api_widget_login():
    """Il widget si collega una volta con utente e password e riceve un token (salvato solo su quel PC) che abilita
    il PC; i messaggi mostrati poi seguono chi sta usando il gestionale da quel PC."""
    if not _ip_rete_locale(request.remote_addr):
        return jsonify({"ok": False, "error": "Accesso consentito solo dalla rete locale"}), 403
    data = request.get_json(silent=True) or {}
    username, password = data.get("username", ""), data.get("password", "")
    user = next((u for u in load_users() if u["username"].lower() == username.strip().lower()), None)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"ok": False, "error": "Utente o password non validi"}), 401
    import secrets
    token = secrets.token_urlsafe(32)
    with _WIDGET_TOKENS_LOCK:
        tokens = _widget_tokens()
        tokens[hashlib.sha256(token.encode()).hexdigest()] = {
            "user": user["username"], "pc": str(data.get("pc", ""))[:60], "ip": request.remote_addr,
            "creato": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        WIDGET_TOKENS_FILE.write_text(json.dumps(tokens, indent=1), encoding="utf-8")
    lega_utente_al_pc(request.remote_addr, user["username"], user["full_name"])  # chi accede qui è seduto a quel PC
    return jsonify({"ok": True, "token": token, "username": user["username"], "full_name": user["full_name"]})

@app.route("/api/widget/feed")
def api_widget_feed():
    """Novità per l'utente del widget: messaggi chat ricevuti e notifiche non lette.
    ?msg=<ultimo id messaggio visto>; senza parametro restituisce solo il punto di partenza (niente arretrati)."""
    if not _widget_autorizzato():
        return _widget_risposta_non_autorizzato()
    user = _widget_user()
    if not user:
        # nessuno sta usando il gestionale da questo PC: niente messaggi personali
        return jsonify({"ok": True, "segue_pc": True, "username": None, "full_name": None, "ultimo_msg_id": None,
                        "messaggi": [], "messaggi_non_letti": 0, "notifiche": []})
    me = user["username"]
    db = _DBSession()
    try:
        from sqlalchemy import func
        ultimo = db.query(func.max(_Message.id)).scalar() or 0
        messaggi = []
        if "msg" in request.args:
            try:
                dopo = int(request.args.get("msg", "0"))
            except ValueError:
                dopo = ultimo
            rows = db.query(_Message).filter(_Message.to_user == me, _Message.id > dopo, _Message.read == False  # noqa: E712
                                             ).order_by(_Message.id).limit(20).all()
            messaggi = [{"id": m.id, "from": m.from_user, "from_name": m.from_name or m.from_user,
                         "text": m.text or "", "allegato": m.original_filename or "", "ts": m.timestamp} for m in rows]
        non_letti = db.query(_Message).filter(_Message.to_user == me, _Message.read == False).count()  # noqa: E712
        notifiche = [{"id": n.id, "text": n.text or "", "link": n.link or "/", "ts": n.timestamp}
                     for n in db.query(_Notification).filter(_Notification.target_user == me, _Notification.read == False  # noqa: E712
                                                             ).limit(30).all()]
    finally:
        db.close()
    return jsonify({"ok": True, "segue_pc": True, "username": me, "full_name": user["full_name"], "ultimo_msg_id": ultimo,
                    "messaggi": messaggi, "messaggi_non_letti": non_letti, "notifiche": notifiche})

@app.route("/api/widget/rispondi", methods=["POST"])
def api_widget_rispondi():
    """Risposta rapida dal widget: invia un messaggio chat e segna come letti quelli ricevuti da quel collega."""
    if not _widget_autorizzato():
        return _widget_risposta_non_autorizzato()
    data = request.get_json(silent=True) or {}
    user = _widget_user()
    # l'avviso era di un altro utente (nel frattempo al PC si è seduto un collega): non si risponde a suo nome
    if not user or ("come" in data and data["come"] != user["username"]):
        return jsonify({"ok": False, "error": "su questo PC ora c'è un altro utente"}), 409
    to_user, text = str(data.get("to", "")), str(data.get("text", "")).strip()
    if not to_user or not text:
        return jsonify({"ok": False, "error": "Messaggio vuoto"}), 400
    db = _DBSession()
    try:
        db.query(_Message).filter(_Message.to_user == user["username"], _Message.from_user == to_user,
                                  _Message.read == False).update({_Message.read: True}, synchronize_session=False)  # noqa: E712
        db.add(_Message(from_user=user["username"], from_name=user["full_name"], to_user=to_user, text=text,
                        attachment="", original_filename="",
                        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), read=False))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[widget] Errore risposta: {e}")
        return jsonify({"ok": False, "error": "Errore durante l'invio"}), 500
    finally:
        db.close()
    return jsonify({"ok": True})

@app.route("/api/widget/notifica-letta", methods=["POST"])
def api_widget_notifica_letta():
    if not _widget_autorizzato():
        return _widget_risposta_non_autorizzato()
    user = _widget_user()
    if not user:
        return jsonify({"ok": False, "error": "nessun utente su questo PC"}), 409
    nid = str((request.get_json(silent=True) or {}).get("id", ""))
    db = _DBSession()
    try:
        db.query(_Notification).filter(_Notification.id == nid, _Notification.target_user == user["username"]
                                       ).update({_Notification.read: True}, synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})

@app.route("/api/widget/rilascia", methods=["POST"])
def api_widget_rilascia():
    """Il widget segnala che il PC è bloccato o inattivo: da qui in poi nessun messaggio personale
    finché qualcuno non torna a usare il gestionale da quel PC."""
    if not _widget_autorizzato():
        return _widget_risposta_non_autorizzato()
    stacca_utente_dal_pc(request.remote_addr, (request.get_json(silent=True) or {}).get("user"))
    return jsonify({"ok": True})

@app.route("/health")
def health():
    """Controllo leggero usato dal widget del server per sapere se risponde."""
    return jsonify({"ok": True, "version": APP_VERSION, "utenti_collegati": len(get_utenti_collegati())})

# ### NUOVE ROUTE PER GESTIONE PASSWORD ###
@app.route("/cambia-password", methods=["GET", "POST"])
@login_required
def cambia_password():
    if request.method == "POST":
        p1 = request.form.get("new_password1")
        p2 = request.form.get("new_password2")
        if not p1 or p1 != p2:
            flash("Le password non coincidono. Riprova.", "error")
            return redirect(url_for("cambia_password"))

        users = load_users()
        user_found = False
        for user in users:
            if user["username"] == session["user_id"]:
                user["password_hash"] = generate_password_hash(p1)
                user["force_password_reset"] = False # Rimuovi l'obbligo
                user_found = True
                break
        
        if user_found:
            save_users(users)
            session["force_password_reset"] = False # Aggiorna la sessione
            flash("Password aggiornata con successo.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Errore: utente non trovato.", "error")

    return render_template("cambia_password.html", title="Cambia Password")

@app.route("/admin/utenti")
@login_required
def gestisci_utenti():
    if session.get("user_role") not in ['amministratore', 'ceo']:
        flash("Accesso non autorizzato.", "error")
        return redirect(url_for("dashboard"))
    
    users = load_users()
    return render_template("gestisci_utenti.html", title="Gestione Utenti", users=users)

@app.route("/admin/reset_password/<username>")
@login_required
def reset_password(username):
    if session.get("user_role") not in ['amministratore', 'ceo']:
        flash("Accesso non autorizzato.", "error")
        return redirect(url_for("dashboard"))

    users = load_users()
    user_to_reset = next((u for u in users if u["username"] == username), None)
    if user_to_reset and user_to_reset.get("role") == 'amministratore':
        flash("Impossibile resettare la password del amministratore.", "error")
        return redirect(url_for("gestisci_utenti"))
    user_found = False
    for user in users:
        if user["username"] == username:
            new_temp_password = f"{username}123"
            user["password_hash"] = generate_password_hash(new_temp_password)
            user["force_password_reset"] = True # Obbliga al cambio password
            user_found = True
            break
    
    if user_found:
        save_users(users)
        flash(f"Password per {username} resettata a '{new_temp_password}'. L'utente dovrà cambiarla al prossimo accesso.", "success")
    else:
        flash("Utente non trovato.", "error")
        
    return redirect(url_for("gestisci_utenti"))

def _ha_consegne_aperte(p):
    """Stessa regola della dashboard Consegne: articoli confermati non ancora consegnati."""
    if p.get("tipo_preventivo") == "edile":
        return any(r.get("stato_consegna") != "Consegnato"
                   for s in p.get("sezioni_edili", []) for r in s.get("righe", []))
    righe = p.get("righe", [])
    for o in _ordini_con_magazzino(p):
        if not o.get("numero_conferma", "").strip():
            continue
        for i in o.get("indici_righe", []):
            if 0 <= i < len(righe) and righe[i].get("stato_consegna") != "Consegnato":
                return True
    return False


def _residuo_da_saldare(p):
    """Stessa regola della dashboard Pagamenti: i pagamenti programmati non contano come incassati."""
    pagato = sum(_to_float(x.get("importo")) for x in p.get("pagamenti", []) if not x.get("is_scheduled"))
    if p.get("no_iva"):
        pagato += _to_float(p.get("tot_iva"))
    return round(_to_float(p.get("totale")) - pagato, 2)


@app.route("/")
@login_required
def dashboard():
    user_role = session.get("user_role")
    full_name = session.get("user_name")
    
    # 1. Carichiamo TUTTI i preventivi, senza filtri
    all_quotes_summary = get_all_quotes()
    
    my_active_quotes = []
    grouped_active_quotes = {}
    chiusi_visibili = []
    today = datetime.date.today()
    stati_ordine_validi = ["Confermato", "In Lavorazione"]

    # 2. Iteriamo e filtriamo
    for summary in all_quotes_summary:
        p = load_quote(summary["numero"])
        if not p: continue

        # Filtro universale: Salta chiusi e annullati
        if p.get("stato") in ["Chiuso", "Annullato"]:
            # I chiusi contano comunque per Saldo e Fatture (come nelle rispettive dashboard)
            if p.get("stato") == "Chiuso" and (user_role != 'venditore' or p.get("venditore") == full_name):
                chiusi_visibili.append(p)
            continue
        
        # Filtro segreteria: Salta bozze
        if user_role == 'segreteria' and p.get("stato") == "Bozza":
            continue

        # --- INIZIO BLOCCO AGGIUNTO ---
        # Visto che "Chiuso" e "Annullato" sono esclusi,
        # controlliamo gli stati attivi per ricalcolare il saldo.
        
        stati_attivi_pagamento = ["Confermato", "In Lavorazione"]
        
        if p.get("stato") in stati_attivi_pagamento:
            today = datetime.date.today()
            totale_preventivo = _to_num(p.get("totale"))
            
            # Somma pagamenti
            totale_pagato_effettivo = 0.0
            for pag in p.get("pagamenti", []):
                totale_pagato_effettivo += _to_num(pag.get("importo"))
            
            # Gestione No-IVA (IVA saldata virtualmente)
            raw_no_iva = p.get("no_iva")
            is_no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")
            if is_no_iva:
                totale_pagato_effettivo += _to_num(p.get("tot_iva"))

            # Rispetto flag SALDATO
            if p.get("stato_pagamento_globale") == "Saldato":
                 p["stato_pagamento_globale"] = "Saldato"
            else:
                da_saldare = totale_preventivo - totale_pagato_effettivo
                if da_saldare <= 0.05: 
                     p["stato_pagamento_globale"] = "Saldato"
                else:
                     p["stato_pagamento_globale"] = "Da Saldare"
        
        elif p.get("stato") in ["Bozza", "Inviato"]:
            p["stato_pagamento_globale"] = "N/D"

        if p.get("stato") in stati_ordine_validi:
            totale_pagato_effettivo = 0.0
            for pag in p.get("pagamenti", []):
                if pag.get("is_scheduled"): 
                    continue
            righe_preventivo = p.get("righe", [])
            indici_righe_valide = {i for i, r in enumerate(righe_preventivo) if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"}
            indici_gia_ordinati = set()
            articoli_in_attesa_conferma = 0
            
            ordini_fornitore = _ordini_con_magazzino(p)
            for ordine in ordini_fornitore:
                indici_ordine = set(ordine.get("indici_righe", []))
                indici_gia_ordinati.update(indici_ordine)
                if not ordine.get("numero_conferma", "").strip():
                    articoli_in_attesa_conferma += len(indici_ordine)

            p["articoli_da_ordinare_count"] = len(indici_righe_valide - indici_gia_ordinati)
            p["articoli_da_ordinare_totale"] = len(indici_righe_valide)
            p["articoli_in_attesa_conferma"] = articoli_in_attesa_conferma
        
        else:
            p["articoli_da_ordinare_count"] = 0
            p["articoli_da_ordinare_totale"] = 0
            p["articoli_in_attesa_conferma"] = 0
        
        venditore = p.get("venditore", "Sconosciuto")

        # 3. Logica di smistamento
        if user_role in ['amministratore', 'ceo']:
            if venditore == full_name:
                my_active_quotes.append(p)
            else:
                grouped_active_quotes.setdefault(venditore, []).append(p)
        
        elif user_role == 'segreteria':
            grouped_active_quotes.setdefault(venditore, []).append(p)
        
        elif user_role == 'venditore':
            if venditore == full_name:
                my_active_quotes.append(p)

    # 4. Contatori per le schede della home (sui preventivi visibili all'utente)
    visibili = my_active_quotes + [q for lista in grouped_active_quotes.values() for q in lista]
    attivi = [q for q in visibili if q.get("stato") in stati_ordine_validi]
    home_stats = {
        "aperti": len([q for q in visibili if q.get("stato") in ["Bozza", "Inviato"]]),
        "attivi": len(attivi),
        # Solo i preventivi personali dell'utente, per il saluto in testa alla home
        "miei_attivi": len([q for q in my_active_quotes if q.get("stato") in stati_ordine_validi]),
        "miei_aperti": len([q for q in my_active_quotes if q.get("stato") in ["Bozza", "Inviato"]]),
        "da_ordinare": len([q for q in attivi if q.get("articoli_da_ordinare_count", 0) > 0 or q.get("articoli_in_attesa_conferma", 0) > 0]),
        "da_consegnare": len([q for q in attivi if _ha_consegne_aperte(q)]),
        "da_saldare": len([q for q in attivi + chiusi_visibili if _residuo_da_saldare(q) > 0.01]),
        "da_fatturare": len([q for q in attivi + chiusi_visibili if q.get("stato_fattura") != "Fatturato"]),
    }

    return render_template("dashboard.html", 
        title="Dashboard",
        app_name=APP_NAME,
        my_quotes=my_active_quotes, # Per 'venditore' e 'admin'/'ceo'
        grouped_quotes=grouped_active_quotes, # Per 'segreteria' e 'admin'/'ceo'
        home_stats=home_stats,
        oggi=today
    )
@app.route("/allert")
@login_required
def allert_page():
    """Pagina che raccoglie pagamenti scaduti e documenti mancanti solo per i clienti attivi."""
    alerts = []
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    active_statuses = ["Bozza", "Inviato", "In Lavorazione"]
    active_client_ids = set()

    # 1. Query bulk su DB: carica tutti i preventivi non chiusi/annullati
    db = _DBSession()
    try:
        preventivi_db = db.query(_Preventivo).filter(
            _Preventivo.stato.notin_(["Annullato", "Chiuso"])
        ).all()
        preventivi_data = [p.to_dict() for p in preventivi_db]

        # Raccoglie anche i preventivi in stato attivo per identificare i clienti attivi
        for p in preventivi_data:
            if p.get("stato") in active_statuses:
                active_client_ids.add(p.get("id_cliente"))

        clienti_db = db.query(_Cliente).all()
        clienti_data = [c.to_dict() for c in clienti_db]
    finally:
        db.close()

    # 2. Scansione Preventivi per Pagamenti Scaduti, Merce
    for p in preventivi_data:
        try:
            # --- ALERT PAGAMENTI ---
            for pag in p.get("pagamenti", []):
                if pag.get("is_scheduled") and pag.get("data") <= today_str:
                    alerts.append({
                        "tipo": "PAGAMENTO",
                        "oggetto_id": p.get("numero"),
                        "oggetto_nome": p.get("cliente"),
                        "dettaglio": f"Pagamento da {money_ui(pag.get('importo'))} scaduto il {data_it_filter(pag.get('data'))}",
                        "link_risoluzione": url_for('gestione_pagamenti', quote_id=p.get("numero")),
                        "icona": "fas fa-hand-holding-usd",
                        "colore": "text-danger"
                    })

            # --- ALERT MERCE & INSERIMENTO DATE ---
            for ordine in p.get("ordini_fornitore", []):
                data_creazione_ordine = ordine.get("data_ordine") 
                data_prevista = ordine.get("data_arrivo")
                
                # 1. CONTROLLO INSERIMENTO DATA (Entro 3gg dalla creazione)
                if data_creazione_ordine and not data_prevista:
                    try:
                        d_creazione = datetime.datetime.strptime(data_creazione_ordine, '%Y-%m-%d').date()
                        scadenza_inserimento = d_creazione + datetime.timedelta(days=3)
                        
                        if today > scadenza_inserimento:
                            alerts.append({
                                "tipo": "ORDINE",
                                "oggetto_id": p.get("numero"),
                                "oggetto_nome": p.get("cliente"),
                                "dettaglio": f"Manca data arrivo prevista per ordine {ordine.get('azienda')} (creato il {data_it_filter(data_creazione_ordine)})",
                                "link_risoluzione": url_for('conferma_ordine', quote_id=p.get("numero")),
                                "icona": "fas fa-calendar-times",
                                "colore": "text-warning"
                            })
                    except (ValueError, TypeError): pass

                # 2. CONTROLLO RITARDO ARRIVO (Con tolleranza 5gg)
                if data_prevista:
                    try:
                        d_prevista = datetime.datetime.strptime(data_prevista, '%Y-%m-%d').date()
                        data_limite_tolleranza = d_prevista + datetime.timedelta(days=5)
                        
                        if data_limite_tolleranza <= today:
                            righe = p.get("righe", [])
                            mancanti_in_ordine = []
                            for idx in ordine.get("indici_righe", []):
                                if 0 <= idx < len(righe):
                                    riga = righe[idx]
                                    if not riga.get("data_arrivo_in_house"):
                                        mancanti_in_ordine.append(riga.get("articolo", "Articolo"))
                            
                            if mancanti_in_ordine:
                                alerts.append({
                                    "tipo": "MERCE",
                                    "oggetto_id": p.get("numero"),
                                    "oggetto_nome": p.get("cliente"),
                                    "dettaglio": f"Ritardo da {ordine.get('azienda')} (previsto il {data_it_filter(data_prevista)}, {(today - d_prevista).days} giorni fa). {len(mancanti_in_ordine)} articoli mancanti.",
                                    "link_risoluzione": url_for('gestione_consegna', quote_id=p.get("numero")),
                                    "icona": "fas fa-truck-loading",
                                    "colore": "text-blue"
                                })
                    except (ValueError, TypeError): continue
        except: continue

    # 3. Scansione Clienti per Documenti Mancanti (Solo se il cliente è attivo)
    for c in clienti_data:
        try:
            client_id = c.get("id_cliente")

            # Salta il controllo se il cliente non ha preventivi attivi
            if client_id not in active_client_ids:
                continue

            mancanti = []
            if not c.get("has_ci"): mancanti.append("Carta Identità")
            if not c.get("has_privacy"): mancanti.append("Privacy")
            if not c.get("has_contratto"): mancanti.append("Contratto")
            
            if mancanti:
                alerts.append({
                    "tipo": "DOCUMENTI",
                    "oggetto_id": client_id,
                    "oggetto_nome": c.get("cliente"),
                    "dettaglio": "Mancano: " + ", ".join(mancanti),
                    "link_risoluzione": url_for('dettaglio_cliente', client_id=client_id),
                    "icona": "fas fa-id-card",
                    "colore": "text-warning"
                })
        except: continue

    # Ordine di priorità: pagamenti, merce, ordini, documenti
    priorita = {"PAGAMENTO": 0, "MERCE": 1, "ORDINE": 2, "DOCUMENTI": 3}
    alerts.sort(key=lambda a: priorita.get(a["tipo"], 9))

    return render_template("allert.html", title="Centro Notifiche & Alert", alerts=alerts)


@app.route("/admin/refresh-all-quotes")
@login_required
@role_required('amministratore', 'ceo')
def refresh_all_quotes():
    """
    Cicla tutti i preventivi e ricalcola i loro stati globali (pagamento, consegna, avanzamento).
    Questo corregge i dati "stale" che potrebbero essere rimasti inconsistenti.
    """
    print("--- INIZIO: Aggiornamento stati globali di tutti i preventivi ---")
    db_ids = _DBSession()
    try:
        all_numeri = [r.numero for r in db_ids.query(_Preventivo.numero).all()]
    finally:
        db_ids.close()

    processed_count = 0
    updated_count = 0
    
    for numero in all_numeri:
        try:
            p = load_quote(numero)
            if not p:
                continue
            
            # Fai una copia per confrontare se ci sono state modifiche
            p_original = copy.deepcopy(p)
            
            # Applica le funzioni di aggiornamento in ordine
            aggiorna_stato_pagamento_globale(p)
            aggiorna_stato_consegna_globale(p)
            aggiorna_stato_avanzamento(p) # Questo dipende dai primi due
            
            processed_count += 1
            
            # Salva solo se i dati sono cambiati
            if p != p_original:
                save_quote(p["numero"], p)
                updated_count += 1
                
        except Exception as e:
            print(f"ERRORE: Impossibile aggiornare il preventivo {numero}. Dettagli: {e}")

    print(f"--- FINE: Elaborati {processed_count}. Aggiornati {updated_count}. ---")
    flash(f"Aggiornamento completato. Elaborati {processed_count}/{len(all_numeri)} preventivi. Aggiornati {updated_count}.", "success")
    return redirect(url_for("dashboard"))

def sincronizza_stati_tutti_preventivi():
    """
    Allinea in background gli stati globali di tutti i preventivi (pagamento, consegna, avanzamento).
    Eseguito all'avvio dell'applicazione per garantire che nessun preventivo resti bloccato con stati obsoleti.
    """
    try:
        updated_count = 0
        db_ids = _DBSession()
        try:
            numeri = [r.numero for r in db_ids.query(_Preventivo.numero).all()]
        finally:
            db_ids.close()

        for numero in numeri:
            try:
                p = load_quote(numero)
                if not p:
                    continue
                p_original = copy.deepcopy(p)
                aggiorna_stato_pagamento_globale(p)
                aggiorna_stato_consegna_globale(p)
                aggiorna_stato_avanzamento(p)
                if p != p_original:
                    save_quote(p.get("numero", numero), p)
                    updated_count += 1
            except Exception:
                pass
        if updated_count > 0:
            print(f"INFO: Sincronizzazione automatica: aggiornati stati di {updated_count} preventivi.")
    except Exception as e:
        print(f"Avviso durante sincronizzazione automatica preventivi: {e}")

@app.route("/admin/margini", methods=["GET", "POST"])
@login_required
@role_required('amministratore', 'ceo')
def gestisci_margini():
    """Pagina per visualizzare e modificare i margini di ricarico."""
    if request.method == "POST":
        try:
            # --- INIZIO BLOCCO DINAMICO (CORRETTO) ---
            
            # 1. Carica la configurazione COMPLETA esistente (incluse le regole_colore)
            config = load_margini_config()
            
            # 2. Itera su ogni fascia presente nella configurazione
            for i, fascia in enumerate(config["fasce"]):
                
                # 3. Aggiorna i pallini leggendo i dati dal form usando l'indice
                fascia["pallini"]["verde"] = int(request.form.get(f"verde_{i}"))
                fascia["pallini"]["arancione"] = int(request.form.get(f"arancione_{i}"))
                fascia["pallini"]["rosso"] = int(request.form.get(f"rosso_{i}"))

                # 4. Aggiorna max_costo SOLO se non è l'ultima fascia
                if i < len(config["fasce"]) - 1:
                    fascia["max_costo"] = int(request.form.get(f"max_costo_{i}"))

            # 5. Salva ogni fascia aggiornata nel DB (tabella config_margini)
            db = _DBSession()
            try:
                for fascia in config["fasce"]:
                    record = db.query(_ConfigMargini).filter_by(key=fascia["key"]).first()
                    if record:
                        record.pallino_verde     = fascia["pallini"]["verde"]
                        record.pallino_arancione = fascia["pallini"]["arancione"]
                        record.pallino_rosso     = fascia["pallini"]["rosso"]
                        if "max_costo" in fascia:
                            record.max_costo = fascia["max_costo"]
                    else:
                        print(f"[gestisci_margini] WARN: fascia '{fascia['key']}' non trovata nel DB.")
                db.commit()
            except Exception as db_err:
                db.rollback()
                raise db_err
            finally:
                db.close()

            # --- FINE BLOCCO DINAMICO ---

            flash("Configurazione dei margini salvata con successo.", "success")
        except (ValueError, TypeError):
            flash("Errore: Assicurati di inserire solo numeri interi per i margini e i costi.", "error")
        return redirect(url_for('gestisci_margini'))

    # La parte GET (che carica la pagina) rimane invariata
    margini_config = load_margini_config()
    return render_template("margini_ricarico.html", title="Gestione Margini", config=margini_config)


@app.route("/archivio")
@login_required
def archivio_globale():
    """Pagina di archivio che mostra la ricerca e l'elenco completo dei preventivi."""
    
    # 1. Chiamo get_all_quotes senza argomenti per ottenere tutti i preventivi senza filtri
    all_quotes_summary = get_all_quotes()

    # 2. Carico i dati completi di ogni preventivo per la visualizzazione
    all_quotes_full = []
    for summary in all_quotes_summary:
        p = load_quote(summary["numero"])
        if not p:
            continue

        # --- INIZIO BLOCCO MODIFICATO ---
        # Filtra solo i preventivi che sono in uno stato "finale"
        if p.get("stato") in ["Chiuso", "Annullato"]:
            p["totale_num"] = _to_float(p.get("totale"))
            all_quotes_full.append(p)
        # --- FINE BLOCCO MODIFICATO ---

    # Ordina i preventivi per numero (più recente prima)
    all_quotes_full.sort(key=lambda x: x.get("numero", ""), reverse=True)

    # 3. Rendo il template, passando la lista (ora filtrata)
    return render_template("archivio_globale.html", 
        title="Archivio Globale",
        all_quotes=all_quotes_full
    )

@app.route("/anagrafica-clienti")
@login_required
def anagrafica_clienti():
    """Mostra l'elenco completo dei dati anagrafici con flag per preventivi attivi."""
    active_statuses = ["Bozza", "Inviato", "In Lavorazione"]

    db = _DBSession()
    try:
        # 1. Trova gli id_cliente con almeno un preventivo in stato attivo
        active_ids_rows = db.query(_Preventivo.id_cliente).filter(
            _Preventivo.stato.in_(active_statuses)
        ).distinct().all()
        active_client_ids = {r.id_cliente for r in active_ids_rows}

        # 2. Carica tutti i clienti dal DB
        clienti_db = db.query(_Cliente).order_by(_Cliente.cliente).all()
        clients = []
        for c in clienti_db:
            d = c.to_dict()
            d["has_active_quote"] = c.id_cliente in active_client_ids
            clients.append(d)
    finally:
        db.close()
    
    return render_template("anagrafica_clienti.html", 
        title="Anagrafica Clienti", 
        clients=clients
    )

@app.route("/preventivi-cliente")
@login_required
def dashboard_clienti():
    """Pagina che raggruppa i preventivi aperti per cliente."""

    tutti_i_preventivi = get_all_quotes()
    clienti_preventivi = {}
    today = datetime.date.today()

# --- Intorno alla riga 650 (all'interno di dashboard_clienti) ---
    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p:
            continue

        # Gestione differenziata per preventivi Edili
        is_edile = p.get("tipo_preventivo") == "edile"
        
        if is_edile:
            # --- MODIFICA: RIMOSSO IL RICALCOLO FORZATO ---
            # Non sovrascriviamo più i totali (p["totale"], p["tot_iva"]).
            # Utilizziamo i valori già calcolati e salvati nel file JSON
            # (tot_imponibile_cliente, tot_iva, totale).
            # Impostiamo solo i contatori degli ordini a 0 per la visualizzazione corretta.
            
            p["articoli_da_ordinare_count"] = 0
            p["articoli_da_ordinare_totale"] = 0
            p["articoli_in_attesa_conferma"] = 0
            
        # Se l'utente è segreteria, salta anche le bozze
        if session.get("user_role") == 'segreteria' and p.get("stato") == "Bozza":
            continue
        
        is_attivo = p.get("stato") not in ["Chiuso", "Annullato"]
        if not is_attivo:
            continue
        
        # Individua la sorgente delle righe in base al tipo
        is_edile = p.get("tipo_preventivo") == "edile"
        righe_preventivo = get_flat_righe_edili(p) if is_edile else p.get("righe", [])
        
        cliente_nome = p.get("cliente", "Senza Nome")
        if cliente_nome not in clienti_preventivi:

            clienti_preventivi[cliente_nome] = {
                "preventivi": [],
                "totale_attivo": 0.0,
                "id_cliente": p.get("id_cliente") # Aggiungiamo l'ID per i link
            }

        # --- 1. Calcolo Pagamenti (da dashboard_pagamenti) ---
        righe_preventivo = p.get("righe", [])
        indici_confermati = set()
        stati_ordine_validi = ["Confermato", "In Lavorazione", "Chiuso"]
        
        # Definiamo il totale lordo (con IVA) come riferimento base
        totale_preventivo = _to_num(p.get("totale"))
        
        if p.get("stato") in stati_ordine_validi:
            totale_pagato_effettivo = 0.0
            for pag in p.get("pagamenti", []):
                if pag.get("is_scheduled"): 
                    continue
            totale_pagato_effettivo = 0.0
            for pag in p.get("pagamenti", []):
                importo_float = _to_num(pag.get("importo"))
                try:
                    payment_date = datetime.datetime.strptime(pag.get("data"), '%Y-%m-%d').date()
                except (ValueError, TypeError, KeyError):
                    payment_date = today 
                
                if payment_date <= today:
                    totale_pagato_effettivo += importo_float
            
            # SE ESENTE IVA: Aggiungiamo il valore dell'IVA ai pagamenti effettuati
            # per pareggiare il totale lordo (Logica identica a gestione_pagamenti)
            if p.get("no_iva") is True:
                totale_pagato_effettivo += _to_num(p.get("tot_iva"))

            # Aggiorniamo i valori nel dizionario per il template
            p["totale_pagato"] = round(totale_pagato_effettivo, 2)
            p["totale_da_saldare"] = round(totale_preventivo - totale_pagato_effettivo, 2)
            
            # Rispetto del flag manuale o calcolato
            if p.get("stato_pagamento_globale") == "Saldato" or p["totale_da_saldare"] <= 0.05:
                p["totale_da_saldare"] = 0.0
                p["stato_pagamento_globale"] = "Saldato"
            else:
                p["stato_pagamento_globale"] = "Da Saldare"

        else:
            # Se lo stato non è valido (Bozza, Inviato), imposta tutto a 0 e N/D
            p["totale_pagato"] = 0.0
            p["totale_da_saldare"] = 0.0
            p["stato_pagamento_globale"] = "N/D"

        # --- 2. Calcolo Ordini (da dashboard_ordini) ---
        stati_ordine_validi = ["Confermato", "In Lavorazione", "Chiuso"]
        if p.get("stato") in stati_ordine_validi:
            
            # Utilizza righe_preventivo (che ora punta alla lista corretta)
            indici_righe_valide = {i for i, r in enumerate(righe_preventivo) if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"}
            indici_gia_ordinati = set()

            articoli_in_attesa_conferma = 0
            
            ordini_fornitore = _ordini_con_magazzino(p)
            for ordine in ordini_fornitore:
                indici_ordine = set(ordine.get("indici_righe", []))
                indici_gia_ordinati.update(indici_ordine)
                if ordine.get("numero_conferma", "").strip():
                    indici_confermati.update(indici_ordine)
                else:
                    articoli_in_attesa_conferma += len(indici_ordine)

            p["articoli_da_ordinare_count"] = len(indici_righe_valide - indici_gia_ordinati)
            p["articoli_da_ordinare_totale"] = len(indici_righe_valide)
            p["articoli_in_attesa_conferma"] = articoli_in_attesa_conferma
            p["articoli_in_attesa_conferma_totale"] = len(indici_gia_ordinati)
        else:
            # Se lo stato non è valido (es. Bozza, Inviato), imposta tutti i contatori a 0
            p["articoli_da_ordinare_count"] = 0
            p["articoli_da_ordinare_totale"] = 0
            p["articoli_in_attesa_conferma"] = 0
            p["articoli_in_attesa_conferma_totale"] = 0    

        # --- 3. Calcolo Consegne (da dashboard_consegne) ---
        if p.get("stato") in stati_ordine_validi:
            # --- MODIFICA PER EDILIZIA ---
            if is_edile:
                righe_lavorazione = get_flat_righe_edili(p)
                p["articoli_da_consegnare_totale"] = len(righe_lavorazione)
                p["articoli_da_consegnare_count"] = sum(
                    1 for r in righe_lavorazione if r.get("stato_consegna") != "Consegnato"
                )
            else:
                # Logica standard per preventivi con articoli
                articoli_da_consegnare_count = 0
                for index in indici_confermati:
                    if 0 <= index < len(righe_preventivo):
                        riga = righe_preventivo[index]
                        if riga.get("stato_consegna") != "Consegnato":
                            articoli_da_consegnare_count += 1
                
                p["articoli_da_consegnare_count"] = articoli_da_consegnare_count
                p["articoli_da_consegnare_totale"] = len(indici_confermati)

        else:
            # Se lo stato non è valido, imposta i contatori a 0
            p["articoli_da_consegnare_count"] = 0
            p["articoli_da_consegnare_totale"] = 0    
        
        # --- 4. Aggiungi alla lista ---
        clienti_preventivi[cliente_nome]['preventivi'].append(p)
        clienti_preventivi[cliente_nome]['totale_attivo'] += totale_preventivo

    return render_template("dashboard_clienti.html", 
        title="Preventivi per Cliente",
        clienti_preventivi=clienti_preventivi
    )
@app.route("/cliente/dettaglio/<client_id>")
@login_required
def dettaglio_cliente(client_id):
    """Pagina che mostra il dettaglio documentale, con modalità archivio opzionale."""
    
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    # 1. Controlla se siamo arrivati da un preventivo specifico
    source_quote_id = request.args.get('source_quote_id')
    source_quote = load_quote(source_quote_id) if source_quote_id else None
    
    # 2. Controlla se siamo in modalità "Archivio"
    is_archivio_mode = request.args.get('archivio') == '1'

    # Controlla se siamo in modalità "Archivio" tramite un parametro nell'URL
    is_archivio_mode = request.args.get('archivio') == '1'

    tutti_i_preventivi = get_all_quotes()
    
    preventivi_cliente = []
    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if p and p.get("id_cliente") == client_id:
            # Se NON siamo in modalità archivio, applichiamo il filtro
            if not is_archivio_mode and p.get("stato") in ["Chiuso", "Annullato"]:
                continue
            p["totale_num"] = _to_float(p.get("totale"))
            preventivi_cliente.append(p)
            
    # Ordina i preventivi dal più recente al più vecchio
    preventivi_cliente.sort(key=lambda x: x.get("numero", ""), reverse=True)

    return render_template("dettaglio_cliente.html", 
        title=f"Dettaglio Cliente {client_data.get('cliente')}",
        cliente=client_data,
        preventivi=preventivi_cliente,
        is_archivio_mode=is_archivio_mode, # Passa la modalità al template
        source_quote=source_quote,
    )

@app.route("/preventivo/<quote_id>/upload-riga-edile", methods=["POST"])
@login_required
@role_required('amministratore', 'ceo')
def upload_riga_edile_ajax(quote_id):
    """Upload tecnico per riga edile: salva il file ma non modifica il JSON."""
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "Nessun file selezionato"}), 400
    
    try:
        quote_dir = ALLEGATI_DIR / quote_id
        quote_dir.mkdir(parents=True, exist_ok=True)
        
        filename = secure_filename(file.filename)
        file.save(quote_dir / filename)
        
        # Restituiamo solo il successo e il nome, il salvataggio nel JSON 
        # avverrà al click su "Salva Modifiche" nel form principale.
        return jsonify({"success": True, "filename": filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- Cerca la rotta allega_documento esistente (intorno alla 920) e assicurati che sia invariata per gli allegati generici ---
@app.route("/cliente/<client_id>/allega", methods=["POST"])
@login_required
def allega_documento_cliente(client_id):
    """Gestisce l'upload di documenti anagrafici per il cliente."""
    c = load_client(client_id)
    file = request.files.get('file')
    tipo_doc = request.form.get("tipo_documento", "Altro")
    
    if file and file.filename != '':
        client_dir = ALLEGATI_DIR / "clienti" / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(file.filename)
        file.save(client_dir / filename)
        
        if "documenti_anagrafici" not in c: 
            c["documenti_anagrafici"] = []
            
        c["documenti_anagrafici"].append({
            "filename": filename, 
            "tipo": tipo_doc, 
            "data_upload": datetime.date.today().strftime('%Y-%m-%d')
        })

        # --- GESTIONE FLAG ---
        if tipo_doc == "Carta Identità":
            c["has_ci"] = True
        elif tipo_doc == "Autorizzazione Privacy":
            c["has_privacy"] = True
        elif tipo_doc == "Contratto Vendita":
            c["has_contratto"] = True
        # ---------------------

        save_client(client_id, c)
        flash(f"Documento '{tipo_doc}' caricato!", "success")
    return redirect(request.referrer)
@app.route("/cliente/<client_id>/elimina-documento", methods=["POST"])
@login_required
def elimina_documento_cliente(client_id):
    """Elimina un documento anagrafico dal JSON e dal disco."""
    c = load_client(client_id)
    filename = request.form.get("filename")
    
    if c and filename:
        # Rimuove il file dalla lista
        c["documenti_anagrafici"] = [d for d in c.get("documenti_anagrafici", []) if d.get("filename") != filename]
        
        # --- RICALCOLO FLAG ---
        documenti = c.get("documenti_anagrafici", [])
        c["has_ci"] = any(d.get("tipo") == "Carta Identità" for d in documenti)
        c["has_privacy"] = any(d.get("tipo") == "Autorizzazione Privacy" for d in documenti)
        c["has_contratto"] = any(d.get("tipo") == "Contratto Vendita" for d in documenti)
        # ----------------------

        try:
            file_path = ALLEGATI_DIR / "clienti" / client_id / filename
            if file_path.exists(): os.remove(file_path)
        except: pass
        
        save_client(client_id, c)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Dati mancanti"})

@app.route("/api/messages/download/<filename>")
@login_required
def download_chat_attachment(filename):
    return send_from_directory(CHAT_ATTACHMENTS_DIR, filename)

@app.route("/allegati/cliente/<client_id>/<path:filename>")
@login_required
def serve_allegato_cliente(client_id, filename):
    """Serve i file caricati nell'anagrafica cliente."""
    directory = (ALLEGATI_DIR / "clienti" / client_id).resolve()
    action = request.args.get('action', 'download')
    return send_from_directory(directory, filename, as_attachment=(action != 'view'))


@app.route("/preventivo/<quote_id>/allega", methods=["POST"])
@login_required
def allega_documento(quote_id):
    """Gestisce l'upload di un nuovo allegato per un preventivo."""
    p = load_quote(quote_id)
    if not p:
        if request.form.get("is_ajax") == "1": return jsonify({"success": False, "error": "Non trovato"}), 404
        flash("Preventivo non trovato.", "error")
        return redirect(request.referrer or url_for('dashboard'))

    if 'file' not in request.files:
        if request.form.get("is_ajax") == "1": return jsonify({"success": False, "error": "No file"}), 400
        flash("Nessun file selezionato.", "error")
        return redirect(request.referrer)

    file = request.files['file']
    descrizione = request.form.get("descrizione", "Nessuna descrizione")

    if file.filename == '':
        if request.form.get("is_ajax") == "1": return jsonify({"success": False, "error": "No filename"}), 400
        flash("Nessun file selezionato.", "error")
        return redirect(request.referrer)

    if file:
        quote_allegati_dir = ALLEGATI_DIR / quote_id
        quote_allegati_dir.mkdir(exist_ok=True)
        
        filename = secure_filename(file.filename)
        file.save(quote_allegati_dir / filename)

        if "allegati" not in p:
            p["allegati"] = []
        
        p["allegati"].append({
            "filename": filename,
            "descrizione": descrizione,
            "data_upload": datetime.date.today().strftime('%Y-%m-%d')
        })
        save_quote(quote_id, p)
        
        if request.form.get("is_ajax") == "1":
            return jsonify({"success": True, "filename": filename})
            
        flash("Documento allegato con successo!", "success")

    return redirect(request.referrer)

@app.route("/preventivo/<quote_id>/elimina-allegato", methods=["POST"])
@login_required
def elimina_allegato(quote_id):
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    filename = request.form.get("filename")
    if not filename:
        return jsonify({"success": False, "error": "Nome file non specificato"})

    allegati_originali = p.get("allegati", [])
    allegati_filtrati = [att for att in allegati_originali if att.get("filename") != filename]

    if len(allegati_filtrati) == len(allegati_originali):
        return jsonify({"success": False, "error": "Allegato non trovato nel preventivo."})

    # 1. Aggiorna la lista nel preventivo
    p["allegati"] = allegati_filtrati
    
    # 2. Ora, elimina il file fisico dal disco
    try:
        # Usiamo secure_filename per sicurezza nel costruire il percorso
        file_path = ALLEGATI_DIR / quote_id / secure_filename(filename)
        if file_path.exists():
            os.remove(file_path)
        else:
            print(f"ATTENZIONE: File da eliminare non trovato su disco: {file_path}")
    except Exception as e:
        print(f"ERRORE: Impossibile eliminare il file {filename}. Dettagli: {e}")
        # Non blocchiamo l'operazione se il file non c'è, continuiamo a salvare il JSON
    
    save_quote(quote_id, p)
    return jsonify({"success": True})

@app.route("/allegati/<quote_id>/<path:filename>")
@login_required
def serve_allegato(quote_id, filename):
    """Permette di scaricare/visualizzare un file allegato."""
    directory = (ALLEGATI_DIR / quote_id).resolve()
    
    # Controlla se l'URL richiede di 'visualizzare' o 'scaricare' il file
    action = request.args.get('action', 'download') # Default a 'download'
    
    # Se l'azione NON è 'view', forza il download. Altrimenti, visualizza.
    should_download = action != 'view'
    
    return send_from_directory(directory, filename, as_attachment=should_download)

# --- LOGICA: Recupera l'azione sia dal link (GET) che dal form (POST) ---
@app.route("/cliente/cerca", methods=["GET", "POST"])
@login_required
def cerca_cliente():
    # Recupera l'azione: se non c'è nel form (POST), cercala nell'URL (GET)
    action = request.form.get('action') or request.args.get('action') or 'open_archive'
    
    if request.method == "POST":
        search_term = request.form.get("search_term", "")
        clients = find_clients_by_term(search_term)

        return render_template(
            "risultati_ricerca_cliente.html", 
            title="Risultati Ricerca", 
            clients=clients, 
            search_term=search_term,
            action=action  # Assicurati di passare l'action ai risultati
        )
        
    return render_template("cerca_cliente.html", title="Cerca Cliente", action=action)
@app.route("/cliente/cerca/live")
@login_required
def cerca_cliente_live():
    """Endpoint API per la ricerca live dei clienti."""
    term = request.args.get("term", "").strip()
    
    # Restituisce una lista vuota se il termine è più corto di 3 caratteri
    if len(term) < 3:
        return jsonify([])
    
    clients = find_clients_by_term(term)
    return jsonify(clients)

@app.route("/cliente/crea", methods=["GET", "POST"])
@login_required
def crea_cliente():
    # Recupera l'azione dalla query string (GET) o dal form (POST)
    action = request.args.get('action') or request.form.get('action') or 'new_quote'
    
    if request.method == "POST":
        new_client_id = get_new_client_id()
        client_data = { "id_cliente": new_client_id }
        form_keys = ["cliente", "rag_sociale", "p_iva", "indirizzo", "cap", "comune", "provincia", "regione", "regione_nome", "email", "telefono", "codice_univoco"]
        for key in form_keys: client_data[key] = request.form.get(key, "")
        save_client(new_client_id, client_data)
        flash("Nuovo cliente creato con successo.")
        
        # Reindirizza al tipo di preventivo corretto in base all'azione
        if action == 'new_quote_edile':
            return redirect(url_for("nuovo_preventivo_edile", client_id=new_client_id))
        return redirect(url_for("nuovo_preventivo", client_id=new_client_id))
        
    return render_template("crea_cliente.html", title="Crea Nuovo Cliente", geo_data=GEO_DATA, action=action)

@app.route("/cliente/modifica/<client_id>", methods=["GET", "POST"])
@login_required
def modifica_cliente(client_id):
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.", "error")
        return redirect(url_for("anagrafica_clienti"))
        
    if request.method == "POST":
        form_keys = ["cliente", "rag_sociale", "p_iva", "indirizzo", "cap", "comune", "provincia", "regione", "regione_nome", "email", "telefono", "codice_univoco"]
        for key in form_keys: 
            client_data[key] = request.form.get(key, "")
        save_client(client_id, client_data)
        flash("Dati anagrafici aggiornati con successo.", "success")
        return redirect(url_for("anagrafica_clienti"))
        
    # Aggiungiamo il parametro 'id' ai dati inviati al template per far commutare il bottone in "Salva Modifiche"
    client_data["id"] = client_id
    return render_template("crea_cliente.html", title="Modifica Cliente", geo_data=GEO_DATA, p=client_data, action="edit")

@app.route("/cliente/elimina/<client_id>", methods=["POST"])
@login_required
def elimina_cliente(client_id):
    client_data = load_client(client_id)
    if not client_data:
        return jsonify({"success": False, "error": "Cliente non trovato."})

    db = _DBSession()
    try:
        # Verifica preventivi attivi via DB
        has_active = db.query(_Preventivo).filter(
            _Preventivo.id_cliente == client_id,
            _Preventivo.stato.notin_(["Annullato", "annullato"])
        ).first() is not None

        if has_active:
            return jsonify({"success": False, "error": "Preventivi presenti per questo cliente, annullare tutti i preventivi o contattare l'amministratore di sistema."})

        # Elimina il record dal DB
        cliente_obj = db.query(_Cliente).filter_by(id_cliente=client_id).first()
        if not cliente_obj:
            return jsonify({"success": False, "error": "Cliente non trovato nel database."})
        db.delete(cliente_obj)
        db.commit()
        return jsonify({"success": True, "message": "Cliente eliminato con successo."})
    except Exception as e:
        db.rollback()
        print(f"[elimina_cliente] Errore: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()

@app.route("/preventivo-edile/nuovo/<client_id>")
@login_required
@role_required('amministratore', 'ceo')
def nuovo_preventivo_edile(client_id):
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.")
        return redirect(url_for("dashboard"))

    venditore_sigla = session.get("user_sigla", "XX")
    full_name = session.get("user_name", "Sconosciuto")
    
    # Genera ID con prefisso ED (Edile) per tenerlo separato
    now = datetime.datetime.now()
    new_quote_id = f"EDIL-{venditore_sigla.upper()}-{now.strftime('%d%m%y%H%M')}"
    
    p = EMPTY_STATE.copy()
    p.update(client_data)
    p["numero"] = new_quote_id
    p["tipo_preventivo"] = "edile"
    p["venditore"] = full_name
    p["data"] = now.strftime('%Y-%m-%d')
    # Inizializziamo con una sezione predefinita vuota
    p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": []}] 
    
    save_quote(new_quote_id, p)
    return redirect(url_for("editor_preventivo_edile", quote_id=new_quote_id))

@app.route("/preventivo-edile/edit/<quote_id>")
@login_required
@role_required('amministratore', 'ceo')
def editor_preventivo_edile(quote_id):
    p = load_quote(quote_id)
    if p is None: 
        flash(f"Preventivo Edile '{quote_id}' non trovato.")
        return redirect(url_for("dashboard"))
    
    # Migrazione/Inizializzazione per compatibilità con vecchi preventivi
    if "sezioni_edili" not in p:
        if "righe_edili" in p and p["righe_edili"]:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": p["righe_edili"]}]
        else:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": []}]
    
    return render_template("editor_edile.html", title=f"Edile - {quote_id}", p=p, geo_data=GEO_DATA)

@app.route("/salva-righe-edili/<quote_id>", methods=["POST"])
@login_required
@role_required('amministratore', 'ceo')
def salva_righe_edili(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Non trovato"}), 404
    
    form = request.form
    
    # Inizializzazione di sicurezza per prevenire KeyError su vecchi preventivi
    if "sezioni_edili" not in p:
        if "righe_edili" in p:
            p["sezioni_edili"] = [{"titolo": "Computo Metrico / Lavorazioni", "righe": p.get("righe_edili", [])}]
        else:
            p["sezioni_edili"] = []

    if form.get("is_locked") != 'true':
        p["data"] = form.get("data", p.get("data"))
        p["referente"] = form.get("referente", p.get("referente"))
        p["riepilogo"] = form.get("riepilogo", p.get("riepilogo", ""))
        p["no_iva"] = True if form.get("no_iva") else False 

    nuove_sezioni = []
    pat = re.compile(r"^s\[(\d+)\](?:\[titolo\]|\[costi_vivi_json\]|\[r\]\[(\d+)\]\[(.+)\])$")
    
    sez_map = {}
    for key, val in form.items():
        m = pat.match(key)
        if m:
            s_idx = int(m.group(1))
            sez_map.setdefault(s_idx, {"titolo": "", "costi_vivi_json": "[]", "righe": {}})
            
            if "[titolo]" in key:
                sez_map[s_idx]["titolo"] = val
            elif "[costi_vivi_json]" in key:
                sez_map[s_idx]["costi_vivi_json"] = val
            else:
                r_idx = int(m.group(2))
                field = m.group(3)
                sez_map[s_idx]["righe"].setdefault(r_idx, {})[field] = val

    if sez_map:
        for s_i in sorted(sez_map.keys()):
            r_list = []
            righe_dic = sez_map[s_i]["righe"]
            for r_i in sorted(righe_dic.keys()):
                r_list.append(righe_dic[r_i])
            nuove_sezioni.append({"titolo": sez_map[s_i]["titolo"], "costi_vivi_json": sez_map[s_i].get("costi_vivi_json", "[]"), "righe": r_list})
        p["sezioni_edili"] = nuove_sezioni

    # 1. Recupera azioni di AGGIUNTA dall'URL (Query String via formaction)
    action_add_section = request.args.get("add_section")
    action_add_row_to = request.args.get("add_row")
    
    # 2. Recupera azioni di ELIMINAZIONE dal corpo del FORM (via JS hidden inputs)
    del_s_idx = form.get("delete_section")
    del_r_idx = form.get("delete_row")
    del_whole_s_idx = form.get("delete_whole_section")

    if action_add_section == "1":
        p["sezioni_edili"].append({"titolo": "Nuova Sezione", "righe": []})
    
    elif action_add_row_to is not None:
        try:
            s_idx = int(action_add_row_to)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                p["sezioni_edili"][s_idx]["righe"].append({
                    "articolo": "", 
                    "prezzo_vendita": "0", 
                    "iva_pct": "10", 
                    "costo_stimato": "0"
                })
        except ValueError:
            pass

    elif del_s_idx is not None and del_r_idx is not None:
        try:
            s_idx = int(del_s_idx)
            r_idx = int(del_r_idx)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                if 0 <= r_idx < len(p["sezioni_edili"][s_idx]["righe"]):
                    p["sezioni_edili"][s_idx]["righe"].pop(r_idx)
        except ValueError:
            pass

    elif del_whole_s_idx is not None:
        try:
            s_idx = int(del_whole_s_idx)
            if 0 <= s_idx < len(p["sezioni_edili"]):
                p["sezioni_edili"].pop(s_idx)
        except ValueError:
            pass
    
    # --- FINE LOGICA CORRETTA AZIONI ---

    # Sincronizzazione dell'elenco piatto righe_edili per ripulire il JSON dai dati eliminati
    flat_righe = []
    for sezione in p.get("sezioni_edili", []):
        for riga in sezione.get("righe", []):
            flat_righe.append(riga)
    p["righe_edili"] = flat_righe
        
    save_quote(quote_id, p)
    if form.get("is_ajax") == "1": return jsonify({"success": True})
    return redirect(url_for("editor_preventivo_edile", quote_id=quote_id))

@app.route("/preventivo/nuovo/<client_id>")
@login_required
def nuovo_preventivo(client_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    client_data = load_client(client_id)
    if not client_data:
        flash("Cliente non trovato.")
        return redirect(url_for("dashboard"))

    venditore_sigla = session.get("user_sigla", "XX")
    # Prendiamo sia lo username che il nome completo dalla sessione
    username = session.get("user_id", "sconosciuto")
    full_name = session.get("user_name", "Sconosciuto")
    
    new_quote_id = get_new_quote_id(venditore_sigla)
    p = EMPTY_STATE.copy()
    p.update(client_data)
    p["numero"] = new_quote_id
    p["data"] = datetime.date.today().strftime('%Y-%m-%d')
    # Salviamo lo USERNAME nel campo "venditore"
    p["venditore"] = full_name
    p["righe"] = []
    p["default_iva_switch"] = "22"
    
    save_quote(new_quote_id, p)
    return redirect(url_for("editor_preventivo", quote_id=new_quote_id))
@app.route("/preventivo/edit/<quote_id>")
@login_required
def editor_preventivo(quote_id):
    p = load_quote(quote_id)
    if p is None: flash(f"Preventivo '{quote_id}' non trovato."); return redirect(url_for("dashboard"))
    margini_config = load_margini_config()
    return render_template("editor.html", title=f"Modifica {p.get('numero', 'Preventivo')}", app_name=APP_NAME, data_dir=str(DATA_DIR.resolve()), p=p, geo_data=GEO_DATA, margini_config=margini_config)
@app.route("/salva-righe/<quote_id>", methods=["POST"])
@login_required
def salva_righe(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash(f"Preventivo '{quote_id}' non trovato.")
        return redirect(url_for("dashboard"))
    
    form = request.form
    iva_selezionata_dal_form = form.get("default-iva-switch", "22")
    header_keys = ["venditore", "numero", "data", "cliente", "regione", "regione_nome", "indirizzo", "comune", "provincia", "email", "telefono", "referente", "fee_pct", "rag_sociale", "p_iva", "codice_univoco" , "cap", "default_iva_switch"]
    for key in header_keys:
        if key in form: p[key] = form.get(key, "")
    p["default_iva_switch"] = iva_selezionata_dal_form    
    p.pop("iva_pct", None)

    # --- MODIFICA CHIAVE PER LA PERSISTENZA DEI DATI ---
    # Non ricostruiamo le righe da zero. Invece, le aggiorniamo.
    righe_esistenti = p.get("righe", [])
    nuove_righe_mappate = {}
    pat = re.compile(r"^r\[(\d+)\]\[(.+)\]$")
    for key, val in form.items():
        m = pat.match(key)
        if m:
            i, field = int(m.group(1)), m.group(2)
            if field == 'spese_incasso' and val:
                # Se riceviamo ancora il vecchio campo, lo trattiamo come 'extra'
                nuove_righe_mappate.setdefault(i, {})['extra'] = val
            else:
                nuove_righe_mappate.setdefault(i, {})[field] = val
    
    righe_aggiornate = []
    num_righe_form = len(nuove_righe_mappate)
    
    for i in range(max(len(righe_esistenti), num_righe_form)):
        # Prendi la riga esistente se c'è, altrimenti un dizionario vuoto
        riga = righe_esistenti[i] if i < len(righe_esistenti) else {}
        # Aggiorna la riga con i nuovi dati dal form, se presenti
        if i in nuove_righe_mappate:
            riga.update(nuove_righe_mappate[i])
        righe_aggiornate.append(riga)

    p["righe"] = righe_aggiornate
    # --- FINE MODIFICA CHIAVE ---

    def _to_num(x, default=0.0):
        if x is None: return float(default)
        s = re.sub(r"[€%\s]", "", str(x));
        if not s: return float(default)
        if "," in s and "." in s: s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
        s = s.replace(",", ".");
        try: return float(s)
        except ValueError: return float(default)
    def _fmt_price(n: float) -> str: return f"{float(n):.2f}".replace(".", ",")
    
    fee_effettiva = _to_num(p.get("fee_pct")) / 100
    if fee_effettiva > 0: fee_effettiva *= 1.166
    
    imponibili_per_iva = {}
    tot_imponibile_negozio_globale = 0.0
    # Rimuoviamo le righe che non hanno più un articolo
    p["righe"] = [r for r in p["righe"] if str(r.get("articolo", "")).strip()]

    for r in p["righe"]:
        qt = _to_num(r.get("qt", 0)); incasso = _to_num(r.get("spese_incasso", 0))
        extra = _to_num(r.get("extra", 0))
        ric = _to_num(r.get("ricarico_pct", 0)) / 100; trasp = _to_num(r.get("costo_trasporto", 0))
        unt = r.get("unt", "").strip().upper(); iva_riga_pct = _to_num(r.get("iva_pct", 22))
        # Variabili che popoleremo nell'if/else
        tot_unit_imponibile = 0.0
        tot_riga_imponibile = 0.0
        tot_riga_negozio = 0.0

        if unt == "S":
            # --- INIZIO BLOCCO MODIFICATO ---
            qt = 1.0 # Forza la quantità a 1
            r["qt"] = "1"
            
            # Leggiamo i valori
            ric = _to_num(r.get("ricarico_pct", 0)) / 100
            prezzo_catalogo_val = _to_num(r.get("prezzo_catalogo"))

            if ric > 0:
                # CASO 1: Ricarico PRESENTE (P.Catalogo è un COSTO)
                costo_negozio = prezzo_catalogo_val
                # Applichiamo fee E ricarico
                prezzo_con_fee_e_ricarico = costo_negozio * (1 + fee_effettiva) * (1 + ric)
                
                tot_unit_imponibile = round(prezzo_con_fee_e_ricarico, 2)
                tot_riga_imponibile = tot_unit_imponibile * qt
                tot_riga_negozio = costo_negozio * qt
                prezzo_con_margini_o_fee = prezzo_con_fee_e_ricarico
            
            else:
                # CASO 2: Ricarico ASSENTE (P.Catalogo è GUADAGNO PURO)
                prezzo_servizio = prezzo_catalogo_val
                # Applichiamo solo la fee (se presente)
                prezzo_con_fee = prezzo_servizio * (1 + fee_effettiva) 
            
                tot_unit_imponibile = round(prezzo_con_fee, 2)
                tot_riga_imponibile = tot_unit_imponibile * qt
                tot_riga_negozio = 0.0 # Costo negozio è zero
                prezzo_con_margini_o_fee = prezzo_con_fee

            # Azzera solo i campi non pertinenti per S
            r["costo_trasporto"] = "0"
            r["extra"] = "0"
            r["spese_incasso"] = "0"
            r["s1"] = "0"
            r["s2"] = "0"
            r["s3"] = "0"
            # --- FINE BLOCCO MODIFICATO ---

        else:
            # CASO 2: È UN ARTICOLO NORMALE (PZ, MQ, ML)
            prezzo_scontato = (_to_num(r.get("prezzo_catalogo")) * (1 - _to_num(r.get("s1"))/100) * (1 - _to_num(r.get("s2"))/100) * (1 - _to_num(r.get("s3"))/100))
            prezzo_con_margini = prezzo_scontato * (1 + fee_effettiva) * (1 + ric)
            trasp_con_margini = trasp * (1 + fee_effettiva) * (1 + ric)
            extra_con_margini = extra * (1 + fee_effettiva) * (1 + ric)
            
            subtotale_unitario = 0
            if unt == "MQ": subtotale_unitario = prezzo_con_margini + trasp_con_margini
            elif unt in ["PZ", "ML"]: subtotale_unitario = prezzo_con_margini + (trasp_con_margini / qt if qt > 0 else 0)
            else: subtotale_unitario = prezzo_con_margini
            
            extra_per_unita_con_margini = (extra_con_margini / qt if qt > 0 else 0)
            tot_unit_imponibile = subtotale_unitario + extra_per_unita_con_margini
            tot_unit_imponibile = round(tot_unit_imponibile, 2)
            tot_riga_imponibile = tot_unit_imponibile * qt

            # Aggiungi questo blocco dentro al ciclo, dopo il calcolo di 'tot_riga_imponibile'
            costo_unitario_negozio = prezzo_scontato
            if unt == "MQ":
                costo_unitario_negozio += trasp
            elif unt in ["PZ", "ML"]:
                costo_unitario_negozio += (trasp / qt if qt > 0 else 0)
            costo_unitario_negozio += (incasso / qt if qt > 0 else 0)

            costo_unitario_negozio += (extra / qt if qt > 0 else 0)
            costo_unitario_negozio = round(costo_unitario_negozio, 2)
            tot_riga_negozio = costo_unitario_negozio * qt
            prezzo_con_margini_o_fee = prezzo_con_margini
        
        tot_imponibile_negozio_globale += tot_riga_negozio
            
        iva_unitaria_val = tot_unit_imponibile * (iva_riga_pct / 100)
        tot_iva_riga_val = tot_riga_imponibile * (iva_riga_pct / 100)

        r["prezzo"] = _fmt_price(prezzo_con_margini_o_fee)
        r["tot_prezzo_unitario"] = _fmt_price(tot_unit_imponibile)
        r["tot_prezzo"] = _fmt_price(tot_riga_imponibile)
        r["iva_pct"] = f"{int(iva_riga_pct)} %"
        r["iva_unitaria"] = _fmt_price(iva_unitaria_val) 
        r["tot_iva_riga"] = _fmt_price(tot_iva_riga_val)

        aliquota_key = str(int(iva_riga_pct))
        imponibili_per_iva.setdefault(aliquota_key, 0.0)
        imponibili_per_iva[aliquota_key] += tot_riga_imponibile

    #  blocco di salvataggio dei totali 
    tot_imponibile_cliente_globale = sum(imponibili_per_iva.values())
    tot_iva_globale = sum(valore * (int(aliquota)/100) for aliquota, valore in imponibili_per_iva.items())

    p["imponibili_iva"] = {k: _fmt_price(v) for k, v in imponibili_per_iva.items()}
    p["tot_iva_dettaglio"] = {k: _fmt_price(v * (int(k)/100)) for k, v in imponibili_per_iva.items()}

    # Salvataggio dei nuovi totali
    p["tot_imponibile_negozio"] = _fmt_price(tot_imponibile_negozio_globale)
    p["tot_imponibile_cliente"] = _fmt_price(tot_imponibile_cliente_globale)
    p["tot_iva"] = _fmt_price(tot_iva_globale)
    p["totale"] = _fmt_price(tot_imponibile_cliente_globale + tot_iva_globale)

    # Calcolo e salvataggio ricarico medio
    totale_guadagno = tot_imponibile_cliente_globale - tot_imponibile_negozio_globale
    if tot_imponibile_negozio_globale > 0:
        ricarico_medio_pct = (totale_guadagno / tot_imponibile_negozio_globale) * 100
    else:
        ricarico_medio_pct = 0.0
    p["ricarico_medio_pct"] = f"{ricarico_medio_pct:.2f}".replace('.', ',') + " %"

    # Rimuoviamo la vecchia chiave per pulizia
    p.pop("tot_imponibile", None)
    
    # --- MODIFICA: Imposta flag no_iva manuale ---
    # Se il preventivo è bloccato (is_locked='true'), i checkbox disabilitati non vengono inviati dal browser.
    # In questo caso NON dobbiamo toccare il valore esistente (altrimenti si resetterebbe a False).
    # Aggiorniamo il valore SOLO se l'editor è sbloccato.
    if form.get("is_locked") != 'true':
        p["no_iva"] = True if form.get("no_iva") else False
    # --- FINE MODIFICA ---

    aggiorna_stato_consegna_globale(p)
    aggiorna_stato_pagamento_globale(p)
    aggiorna_stato_avanzamento(p)
    
    # Gestione eliminazione riga (deve lavorare con la lista aggiornata)
    if request.args.get('delete_row') is not None:
        idx = int(request.args.get('delete_row'))
        if 0 <= idx < len(p["righe"]):
            p["righe"].pop(idx)
        anchor = 'ancora-fine-righe'
# Gestione aggiunta riga
    elif request.args.get('add_row') == '1':
        # --- INIZIO MODIFICA: Leggi l'IVA di default dal form ---
        
        # 1. Leggi il valore dal selettore (es. "22"), con un default di sicurezza
        default_iva_value = iva_selezionata_dal_form
        
        # 2. Crea il dizionario base per la nuova riga
        new_row = {k: "" for k in ["articolo", "unt", "qt", "prezzo_catalogo", "costo_trasporto", "spese_incasso", "s1", "s2", "s3", "ricarico_pct"]}
        
        # 3. Imposta l'iva_pct in base al valore letto, formattandolo
        new_row["iva_pct"] = f"{default_iva_value} %"
        
        # 4. Aggiungi la nuova riga al preventivo
        p["righe"].append(new_row)
        anchor = 'ancora-fine-righe'
        # --- FINE MODIFICA ---
    else: 
        flash("Preventivo Salvato.")
        anchor = 'ancora-fine-righe'
    
    save_quote(quote_id, p)
    
    if request.form.get("is_ajax") == "1": return jsonify({"success": True})
    return redirect(url_for("editor_preventivo", quote_id=quote_id, _anchor=anchor))

def _to_num(x, default=0.0):
    if x is None or isinstance(x, Undefined) or str(x).strip() == "": return float(default)
    try:
        s = str(x).strip().replace("€", "").replace("%", "").strip()
        if "," in s and "." in s:
            s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
        s = s.replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return float(default)
    
@app.route("/preventivo/<quote_id>/clona")
@login_required
def clona_preventivo(quote_id):
    """
    Crea una copia esatta di un preventivo esistente (Edile o Standard),
    gestendo correttamente la struttura a sezioni.
    """
    # 1. Carica il preventivo originale
    p_originale = load_quote(quote_id)
    if not p_originale:
        return jsonify({"success": False, "error": "Preventivo originale non trovato."})

    # 2. Crea una copia profonda
    p_clonato = copy.deepcopy(p_originale)

    # 3. Genera nuovo ID
    venditore_sigla = session.get("user_sigla", "XX")
    nuovo_id = get_new_quote_id(venditore_sigla)
    
    p_clonato["numero"] = nuovo_id
    p_clonato["data"] = datetime.date.today().strftime('%Y-%m-%d')
    p_clonato["stato"] = "Bozza"
    p_clonato["is_locked"] = False
    
    # 4. Copia esplicita della struttura a sezioni (fondamentale per Edili)
    if "sezioni_edili" in p_originale:
        p_clonato["sezioni_edili"] = copy.deepcopy(p_originale["sezioni_edili"])
    
    # 5. Pulizia dati specifici del vecchio preventivo
    campi_da_rimuovere = [
        "pdf_attivo", "storico_pdf", "pagamenti", "bolle", 
        "fatture_allegate", "ordini_fornitore", "data_conferma", "data_chiusura",
        # Campi conservati dalla migrazione V2 (colonna 'extra'): non vanno ereditati dal clone.
        # Gli allegati sono file nella cartella del vecchio preventivo, nel clone sarebbero link rotti.
        "fatture_per_iva", "stati_fattura_iva", "stato_fattura", "data_annullamento",
        "allegati", "totale_pagato", "totale_da_saldare"
    ]
    for campo in campi_da_rimuovere:
        p_clonato.pop(campo, None)
    
    # Resetta stato consegna righe (sia standard che edili)
    if "righe" in p_clonato:
        for r in p_clonato["righe"]:
            r.pop("stato_consegna", None); r.pop("bolla_id", None); r.pop("data_consegna", None)
            r.pop("magazzino_scaricato", None)
            
    if "sezioni_edili" in p_clonato:
        for sez in p_clonato["sezioni_edili"]:
            for r in sez.get("righe", []):
                r.pop("stato_consegna", None); r.pop("bolla_id", None); r.pop("data_consegna", None)

    # 6. Salva
    save_quote(nuovo_id, p_clonato)

    # 7. Restituisci JSON strutturato correttamente
    return jsonify({
        "success": True, 
        "vecchio_id": quote_id, 
        "nuovo_id": nuovo_id,
        "new_url": url_for('editor_preventivo_edile', quote_id=nuovo_id) if p_clonato.get("tipo_preventivo") == "edile" else url_for('editor_preventivo', quote_id=nuovo_id)
    })

@app.route("/preventivo/<quote_id>/conferma-ordine") 
@login_required
def conferma_ordine(quote_id):
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard"))
    
    ordini_fornitore = p.get("ordini_fornitore", [])
    needs_saving = False
    for ordine in ordini_fornitore:
        if "ordine_id" not in ordine or not ordine["ordine_id"]:
            ordine["ordine_id"] = f"ORD-{uuid.uuid4().hex[:8].upper()}"
            ordine["data_ordine"] = datetime.date.today().strftime('%Y-%m-%d')
            needs_saving = True

    if needs_saving:
        save_quote(quote_id, p)
        print(f"INFO: Aggiunti ID ordine mancanti per preventivo {quote_id}")

    righe_preventivo = p.get("righe", [])
    tutti_gli_indici_validi = {
        i for i, r in enumerate(righe_preventivo) 
        if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"}
    # Le righe prese dal magazzino non vanno ordinate al fornitore
    tutti_gli_indici_validi -= _indici_righe_magazzino(p)

    # Funzioni helper per i calcoli, ora include anche le spese di incasso
    def _get_shop_cost(riga):
        prezzo_scontato = (_to_num(riga.get("prezzo_catalogo")) * (1 - _to_num(riga.get("s1"))/100) * (1 - _to_num(riga.get("s2"))/100) * (1 - _to_num(riga.get("s3"))/100))
        return prezzo_scontato * _to_num(riga.get("qt", 1))

    def _get_transport_cost(riga):
        trasp_riga = _to_num(riga.get("costo_trasporto", 0))
        qt_riga = _to_num(riga.get("qt", 1))
        unt_riga = riga.get("unt", "").strip().upper()
        if unt_riga == "MQ":
            return trasp_riga * qt_riga
        return trasp_riga

    indici_gia_ordinati = set()
    tutti_gli_ordini = p.get("ordini_fornitore", [])
    ordini_confermati = []
    ordini_in_attesa = []

    # 1. Associa articoli e calcola i totali per ogni ordine
    for ordine in tutti_gli_ordini:
        # --- LOGICA CORRETTA PER POPOLARE GLI ARTICOLI ---
        items_in_ordine = []
        for item_index in ordine.get("indici_righe", []):
            if 0 <= item_index < len(righe_preventivo):
                riga = righe_preventivo[item_index].copy() 
                riga["original_index"] = item_index
                riga["costo_presunto_articolo"] = _get_shop_cost(riga)
                items_in_ordine.append(riga)
                indici_gia_ordinati.add(item_index)
        
        ordine["articoli"] = items_in_ordine 
        # --- FINE LOGICA ARTICOLI ---

        # --- 1. CALCOLA COSTI PREVENTIVATI (ORA FUNZIONANTE) ---
        costo_netto_articoli = sum(item["costo_presunto_articolo"] for item in items_in_ordine)
        costo_trasporto_preventivato = sum(_get_transport_cost(item) for item in items_in_ordine)
        
        # --- 2. LOGICA COSTI EFFETTIVI (BLOCCO INVARIATO) ---
        trasporto_incluso = ordine.get("trasporto_incluso", True) 
        importo_articoli_lordo_salvato = _to_num(ordine.get("importo_articoli"))
        importo_trasporto_lordo_salvato = _to_num(ordine.get("importo_trasporto"))
        importo_totale_lordo_salvato = _to_num(ordine.get("importo")) # Vecchio campo (solo articoli)
        
        costo_effettivo_articoli_imponibile = 0.0
        costo_effettivo_trasporto_imponibile = 0.0

        if "importo_articoli" in ordine:
            # CASO 1: Ordine "Nuovo" (o già modificato)
            ordine["importo_articoli_form"] = ordine.get("importo_articoli", "0")
            ordine["importo_trasporto_form"] = ordine.get("importo_trasporto", "0")
            
            if trasporto_incluso:
                # Il trasporto è INCLUSO. L'importo articoli è il totale.
                costo_effettivo_articoli_imponibile = importo_articoli_lordo_salvato / 1.22
                costo_effettivo_trasporto_imponibile = 0.0 # È già dentro, quindi il costo separato è 0
            else:
                # Il trasporto è SEPARATO.
                costo_effettivo_articoli_imponibile = importo_articoli_lordo_salvato / 1.22
                if importo_trasporto_lordo_salvato > 0:
                    # Se è stato specificato un costo trasporto, usa quello
                    costo_effettivo_trasporto_imponibile = importo_trasporto_lordo_salvato / 1.22
                else:
                    # Altrimenti (è 0 o vuoto), usa il fallback del costo presunto
                    costo_effettivo_trasporto_imponibile = costo_trasporto_preventivato

        else:
            # CASO 2: Ordine "Legacy" (Logica precedente)
            costo_effettivo_articoli_imponibile = importo_totale_lordo_salvato / 1.22
            costo_effettivo_trasporto_imponibile = costo_trasporto_preventivato # Fallback

            # Popoliamo i campi per il bottone "Modifica"
            ordine["importo_articoli_form"] = ordine.get("importo", "0") 
            ordine["importo_trasporto_form"] = f"{(costo_effettivo_trasporto_imponibile * 1.22):.2f}".replace(".", ",")
            
            # Sovrascriviamo il flag per il JS, così la modale si apre in modalità "separata"
            trasporto_incluso = False 

        # Aggiungiamo il flag per passarlo al bottone "Modifica"
        ordine["trasporto_incluso_flag"] = trasporto_incluso
        
        # --- 3. CALCOLO FINALE (PULITO) ---
        costo_totale_effettivo_imponibile = costo_effettivo_articoli_imponibile + costo_effettivo_trasporto_imponibile
        
        # Ricalcoliamo l'importo totale lordo (IVA incl.)
        importo_totale_lordo_usato = (costo_effettivo_articoli_imponibile * 1.22) + (costo_effettivo_trasporto_imponibile * 1.22)

        # L'IVA calcolata è la differenza tra il lordo e il netto
        iva_calcolata = importo_totale_lordo_usato - costo_totale_effettivo_imponibile

        # Assegna i valori per il template
        ordine["costo_effettivo_articoli_imponibile"] = costo_effettivo_articoli_imponibile
        ordine["costo_effettivo_trasporto_imponibile"] = costo_effettivo_trasporto_imponibile
        ordine["costo_totale_effettivo_imponibile"] = costo_totale_effettivo_imponibile
        ordine["iva_calcolata"] = iva_calcolata
        
        # Assegna i totali preventivati (calcolati sopra)
        ordine["costo_netto_articoli"] = costo_netto_articoli
        ordine["costo_trasporto_preventivato"] = costo_trasporto_preventivato
        ordine["costo_totale_preventivato"] = costo_netto_articoli + costo_trasporto_preventivato

        # Suddivide gli ordini in "attesa" o "confermati"
        if ordine.get("numero_conferma", "").strip():
            ordini_confermati.append(ordine)
        else:
            ordini_in_attesa.append(ordine)

    # 2. Isola gli articoli non ancora ordinati (logica invariata)
    indici_non_ordinati = sorted(list(tutti_gli_indici_validi - indici_gia_ordinati))
    righe_non_ordinate = []
    for item_index in indici_non_ordinati:
        riga = righe_preventivo[item_index]
        riga["original_index"] = item_index
        riga["costo_presunto_articolo"] = _get_shop_cost(riga)
        righe_non_ordinate.append(riga)

    # 3. Calcola i totali globali, aggiungendo le spese incasso
    totale_presunto_globale = sum(
        _get_shop_cost(r) + _get_transport_cost(r)
        for i, r in enumerate(righe_preventivo) if i in tutti_gli_indici_validi
    )
    totale_effettivo_globale = sum(o.get("costo_totale_effettivo_imponibile", 0) for o in tutti_gli_ordini)


    return render_template("conferma_ordine.html", 
        title="Gestione Ordini", p=p,
        righe_non_ordinate=righe_non_ordinate,
        ordini_confermati=ordini_confermati, 
        ordini_in_attesa=ordini_in_attesa,   
        totale_presunto=totale_presunto_globale,
        totale_effettivo=totale_effettivo_globale
    )

@app.route("/preventivo/<quote_id>/salva-ordine", methods=["POST"])
@login_required
def salva_ordine(quote_id):
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    form_data = request.form

    # --- INIZIO MODIFICA: Leggiamo i costi separati ---
    importo_articoli_val = _to_num(form_data.get("importo_articoli"))
    importo_trasporto_val = _to_num(form_data.get("importo_trasporto"))
    importo_totale_val = importo_articoli_val + importo_trasporto_val # Somma
    
    # L'IVA viene calcolata sul totale
    iva_calcolata = importo_totale_val - (importo_totale_val / 1.22)
    # --- FINE MODIFICA ---

    # Crea un nuovo oggetto "Ordine Fornitore"
    nuovo_ordine = {
        "ordine_id": f"ORD-{uuid.uuid4().hex[:8].upper()}",
        "data_ordine": datetime.date.today().strftime('%Y-%m-%d'),
        "azienda": form_data.get("azienda"),
        "numero_conferma": form_data.get("numero_conferma"),
        
        # --- INIZIO MODIFICA: Salviamo i nuovi campi ---
        "importo": f"{importo_totale_val:.2f}".replace(".", ","), # Manteniamo il totale per compatibilità
        "importo_articoli": form_data.get("importo_articoli"),
        "importo_trasporto": form_data.get("importo_trasporto"),
        "iva_ordine": iva_calcolata,
        # --- FINE MODIFICA ---
        
        "data_arrivo": form_data.get("data_arrivo"),
        "indici_righe": [int(i) for i in form_data.getlist("indici_righe[]")]
    }

    # Aggiunge il nuovo ordine alla lista
    if "ordini_fornitore" not in p:
        p["ordini_fornitore"] = []
    p["ordini_fornitore"].append(nuovo_ordine)
    aggiorna_stato_avanzamento(p)

    if nuovo_ordine["numero_conferma"]:
        aggiorna_stato_consegna_globale(p)

    save_quote(quote_id, p)
    return jsonify({"success": True})

@app.route("/preventivo/<quote_id>/modifica-ordine", methods=["POST"])
@login_required
def modifica_ordine(quote_id):
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    form_data = request.form
    ordine_id_da_modificare = form_data.get("ordine_id")
    ordine_trovato = None

    # Cerca l'ordine da modificare
    for ordine in p.get("ordini_fornitore", []):
        if ordine.get("ordine_id") == ordine_id_da_modificare:
            ordine_trovato = ordine
            break

    if ordine_trovato:
        trasporto_incluso = form_data.get("trasporto_incluso") == 'true'
        # --- INIZIO MODIFICA: Leggiamo i costi separati ---
        importo_articoli_val = _to_num(form_data.get("importo_articoli"))
        importo_trasporto_val = _to_num(form_data.get("importo_trasporto"))
        importo_totale_val = importo_articoli_val + importo_trasporto_val # Somma
        
        # L'IVA viene calcolata sul totale
        iva_calcolata = importo_totale_val - (importo_totale_val / 1.22)
        # --- FINE MODIFICA ---

        # Aggiorna i dati dell'ordine
        ordine_trovato["azienda"] = form_data.get("azienda")
        ordine_trovato["numero_conferma"] = form_data.get("numero_conferma")
        
        # --- INIZIO MODIFICA: Salviamo i nuovi campi ---
        ordine_trovato["importo"] = f"{importo_totale_val:.2f}".replace(".", ",")
        ordine_trovato["importo_articoli"] = form_data.get("importo_articoli")
        ordine_trovato["importo_trasporto"] = form_data.get("importo_trasporto")
        ordine_trovato["iva_ordine"] = iva_calcolata
        ordine_trovato["trasporto_incluso"] = trasporto_incluso
        # --- FINE MODIFICA ---
        
        ordine_trovato["data_arrivo"] = form_data.get("data_arrivo")

        aggiorna_stato_consegna_globale(p)
        save_quote(quote_id, p)
        flash("Ordine fornitore modificato con successo.")
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "L'ordine originale non è stato trovato nel preventivo."})

@app.route("/preventivo/<quote_id>/svincola-articolo", methods=["POST"])
@login_required
def svincola_articolo(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})
    
    data = request.json
    ordine_id_target = data.get("ordine_id")
    item_index = data.get("item_index")

    ordine_trovato = next((o for o in p.get("ordini_fornitore", []) if o.get("ordine_id") == ordine_id_target), None)
    
    if not ordine_trovato:
        return jsonify({"success": False, "error": "Ordine non trovato"})

    if int(item_index) in ordine_trovato.get("indici_righe", []):
        ordine_trovato["indici_righe"].remove(int(item_index))
        save_quote(quote_id, p)
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Articolo non trovato nell'ordine"})

@app.route("/preventivo/<quote_id>/aggiungi-a-ordine", methods=["POST"])
@login_required
def aggiungi_a_ordine(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    form_data = request.form
    target_ordine_id = form_data.get("target_ordine_id")
    indici_da_aggiungere = [int(i) for i in form_data.getlist("indici_righe[]")]

    ordine_trovato = next((o for o in p.get("ordini_fornitore", []) if o.get("ordine_id") == target_ordine_id), None)
    
    if not ordine_trovato:
        return jsonify({"success": False, "error": "Ordine di destinazione non trovato"})
    
    # Aggiunge i nuovi indici assicurandosi che non ci siano duplicati
    ordine_trovato["indici_righe"] = sorted(list(set(ordine_trovato.get("indici_righe", []) + indici_da_aggiungere)))
    
    save_quote(quote_id, p)
    return jsonify({"success": True})


@app.route("/preventivo/<quote_id>/elimina-ordine", methods=["POST"])
@login_required
def elimina_ordine(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    ordine_id_da_eliminare = request.form.get("ordine_id")
    ordini_originali = p.get("ordini_fornitore", [])
    ordini_filtrati = [o for o in ordini_originali if o.get("ordine_id") != ordine_id_da_eliminare]

    if len(ordini_filtrati) < len(ordini_originali):
        p["ordini_fornitore"] = ordini_filtrati
        save_quote(quote_id, p)
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Ordine non trovato"})
@app.route("/cliente/<client_id>/indirizzi-cantiere")
@login_required
def get_indirizzi_cantiere(client_id):
    """Restituisce gli indirizzi cantiere di un cliente in formato JSON."""
    client_data = load_client(client_id)
    if not client_data:
        return jsonify({"error": "Cliente non trovato"}), 404
    
    return jsonify({"indirizzi": client_data.get("indirizzi_cantiere", [])})

@app.route("/preventivo/<quote_id>/allega-a-ordine", methods=["POST"])
@login_required
def allega_a_ordine(quote_id):
    """Gestisce l'upload di un allegato per uno specifico ordine fornitore."""
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(request.referrer or url_for('dashboard'))

    # Dati dal form
    ordine_id_target = request.form.get("ordine_id")
    descrizione = request.form.get("descrizione", "Conferma d'ordine")
    file = request.files.get('file')

    if not all([ordine_id_target, file, file.filename]):
        flash("Dati mancanti: assicurati di selezionare un file e che l'ID ordine sia presente.", "error")
        return redirect(request.referrer)

    # Trova l'ordine corretto
    ordine_trovato = next((o for o in p.get("ordini_fornitore", []) if o.get("ordine_id") == ordine_id_target), None)
    if not ordine_trovato:
        flash("Ordine fornitore non trovato.", "error")
        return redirect(request.referrer)

    # Logica di salvataggio del file
    quote_allegati_dir = ALLEGATI_DIR / quote_id
    quote_allegati_dir.mkdir(exist_ok=True)
    
    filename = secure_filename(file.filename)
    file.save(quote_allegati_dir / filename)

    # Aggiungi il riferimento al file nel JSON dell'ordine
    if "allegati" not in ordine_trovato:
        ordine_trovato["allegati"] = []
    
    ordine_trovato["allegati"].append({
        "filename": filename,
        "descrizione": descrizione,
        "data_upload": datetime.date.today().strftime('%Y-%m-%d')
    })

    save_quote(quote_id, p)
    flash("Conferma d'ordine allegata con successo!", "success")
    return redirect(request.referrer)

@app.route("/cliente/<client_id>/salva-indirizzo-cantiere", methods=["POST"])
@login_required
def salva_indirizzo_cantiere(client_id):
    """Salva o aggiorna un indirizzo cantiere per un cliente."""
    client_data = load_client(client_id)
    if not client_data:
        return jsonify({"success": False, "error": "Cliente non trovato"})

    if "indirizzi_cantiere" not in client_data:
        client_data["indirizzi_cantiere"] = []

    form = request.form
    address_id = form.get("id")
    
    address_data = {
        "descrizione": form.get("descrizione"),
        "indirizzo": form.get("indirizzo"),
        "regione": form.get("regione"),
        "regione_nome": form.get("regione_nome"),
        "provincia": form.get("provincia"),
        "comune": form.get("comune"),
        "cap": form.get("cap"),
    }

    if address_id:
        # Aggiorna indirizzo esistente
        found = False
        for addr in client_data["indirizzi_cantiere"]:
            if addr.get("id") == address_id:
                addr.update(address_data)
                found = True
                break
        if not found:
            return jsonify({"success": False, "error": "ID indirizzo non trovato"})
    else:
        # Aggiungi nuovo indirizzo
        address_id = f"CANT-{uuid.uuid4().hex[:6].upper()}"
        address_data["id"] = address_id
        client_data["indirizzi_cantiere"].append(address_data)

    save_client(client_id, client_data)
    return jsonify({"success": True, "new_address_id": address_id})


@app.route("/admin/utenti/aggiungi", methods=["GET", "POST"])
@login_required
def aggiungi_utente():
    if session.get("user_role") != 'amministratore':
        flash("Accesso non autorizzato.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        users = load_users()
        username = request.form.get("username")
        
        # Controlla se l'utente esiste già
        if any(u["username"] == username for u in users):
            flash(f"Errore: L'utente '{username}' esiste già.", "error")
            return redirect(url_for("aggiungi_utente"))

        # Crea il nuovo utente
        new_password = f"{username}123"
        new_user = {
            "username": username,
            "password_hash": generate_password_hash(new_password),
            "full_name": request.form.get("full_name"),
            "role": request.form.get("role"),
            "sigla": request.form.get("sigla", "").upper(),
            "force_password_reset": True
        }
        users.append(new_user)
        save_users(users)
        flash(f"Utente '{username}' creato con successo.", "success")
        return redirect(url_for("gestisci_utenti"))

    return render_template("aggiungi_utente.html", title="Aggiungi Utente")
@app.route("/admin/utenti/elimina/<username>")
@login_required
def elimina_utente(username):
    if session.get("user_role") != 'amministratore':
        flash("Accesso non autorizzato.", "error")
        return redirect(url_for("dashboard"))

    if username == session["user_id"]:
        flash("Non puoi eliminare te stesso.", "error")
        return redirect(url_for("gestisci_utenti"))

    users = load_users()
    users_filtered = [user for user in users if user["username"] != username]

    if len(users) == len(users_filtered):
        flash(f"Errore: Utente '{username}' non trovato.", "error")
    else:
        save_users(users_filtered)
        flash(f"Utente '{username}' eliminato con successo.", "success")
        
    return redirect(url_for("gestisci_utenti"))
@app.route("/admin/utenti/modifica/<username>", methods=["GET", "POST"])
@login_required
def modifica_utente(username):
    if session.get("user_role") != 'amministratore':
        flash("Accesso non autorizzato.", "error")
        return redirect(url_for("dashboard"))

    users = load_users()
    user_to_edit = next((u for u in users if u["username"] == username), None)

    if not user_to_edit:
        flash("Utente non trovato.", "error")
        return redirect(url_for("gestisci_utenti"))

    if request.method == "POST":
        user_to_edit["full_name"] = request.form.get("full_name")
        user_to_edit["sigla"] = request.form.get("sigla", "").upper()
        user_to_edit["role"] = request.form.get("role")
        
        save_users(users)
        flash(f"Dati dell'utente '{username}' aggiornati con successo.", "success")
        return redirect(url_for("gestisci_utenti"))
    return render_template("modifica_utente.html", title="Modifica Utente", user=user_to_edit)
@app.route("/preventivo/<quote_id>/sblocca", methods=["POST"])

@login_required
def sblocca_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    password = request.json.get("password")
    if not password:
        return jsonify({"success": False, "error": "Password non fornita"})

    users = load_users()
    user = next((u for u in users if u["username"] == session["user_id"]), None)

    if user and check_password_hash(user["password_hash"], password):
        # Password corretta: sblocca, imposta a Bozza E ANNULLA IL PDF ATTIVO
        p["stato"] = "Bozza"
        p["is_locked"] = False
        p.pop("pdf_attivo", None) # <-- MODIFICA CHIAVE: Rimuove il riferimento al PDF attivo

        save_quote(quote_id, p)
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Password errata. Riprova."})
    
@app.route("/preventivo/<quote_id>/invia", methods=["POST"])
@login_required
def invia_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Inviato"
    p["is_locked"] = True
    save_quote(quote_id, p)
    flash("Preventivo impostato come 'Inviato' e bloccato.", "success")
    return redirect(url_for("editor_preventivo", quote_id=quote_id))    

# --- File: gestionale.py (intorno alla riga 1680) ---

@app.route("/preventivo/<quote_id>/conferma", methods=["POST"])
@login_required
def conferma_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Confermato"
    p["is_locked"] = True
    # Un preventivo già confermato e riportato in Bozza per modifiche mantiene la data
    # di conferma originale: riconfermarlo non deve spostarlo in un altro periodo.
    if not p.get("data_conferma"):
        p["data_conferma"] = datetime.date.today().strftime('%Y-%m-%d')

    # Se Edile, marca come Pronto per Consegna le righe non ancora avviate
    # (senza toccare righe già in bolla/consegnate né le date di arrivo già registrate)
    if p.get("tipo_preventivo") == "edile":
        for riga in p.get("righe_edili", []):
            if riga.get("stato_consegna") not in ("Consegnato", "In Bolla", "Pronto per Consegna"):
                riga["stato_consegna"] = "Pronto per Consegna"
            if not riga.get("data_arrivo_in_house"):
                riga["data_arrivo_in_house"] = datetime.date.today().strftime('%Y-%m-%d')
    else:
        # Le righe prese dal magazzino sono gia' in sede: pronte per la consegna
        for i in _indici_righe_magazzino(p):
            riga = p["righe"][i]
            if riga.get("stato_consegna") not in ("Consegnato", "In Bolla", "Pronto per Consegna"):
                riga["stato_consegna"] = "Pronto per Consegna"
            if not riga.get("data_arrivo_in_house"):
                riga["data_arrivo_in_house"] = datetime.date.today().strftime('%Y-%m-%d')

    # --- BLOCCO AGGIUNTO ---
    # Aggiorniamo lo stato di pagamento, che passerà a "Da Pagare" se era "Non Definito"
    aggiorna_stato_pagamento_globale(p)


    save_quote(quote_id, p)
    flash("Preventivo confermato e bloccato.", "success")
    return redirect(url_for("editor_preventivo", quote_id=quote_id))

@app.route("/preventivo/<quote_id>/annulla", methods=["POST"])
@login_required
def annulla_preventivo(quote_id):
    if session.get("user_role") == 'segreteria':
        flash("Non disponi delle autorizzazioni per eseguire questa azione.", "error")
        return redirect(url_for("dashboard"))
    
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))
    
    p["stato"] = "Annullato"
    p["is_locked"] = True
    
    # --- RIGA AGGIUNTA ---
    p["data_annullamento"] = datetime.date.today().strftime('%Y-%m-%d')
    # --- FINE RIGA AGGIUNTA ---

    save_quote(quote_id, p)
    flash("Preventivo annullato.", "warning")
    return redirect(url_for("editor_preventivo", quote_id=quote_id))

# ===============================================
# === MAGAZZINO ===
# ===============================================
# Gli articoli stanno in 'magazzino_articoli'. Una riga di un preventivo commerciale presa dal
# magazzino porta il campo 'id_articolo_magazzino': finche' non e' consegnata la sua quantita'
# risulta "prenotata"; quando la consegna viene registrata la giacenza viene scalata e la riga
# riceve 'magazzino_scaricato' (quantita' scaricata), cosi' non viene scalata due volte.

RUOLI_GESTIONE_MAGAZZINO = ('segreteria', 'ceo', 'amministratore')
UNITA_MAGAZZINO = ('PZ', 'ML', 'MQ')


def _fmt_qt(n):
    """Quantita' in formato italiano senza decimali inutili (3 -> '3', 2.5 -> '2,5')."""
    n = round(float(n or 0), 3)
    return (f"{n:.3f}".rstrip("0").rstrip(".")).replace(".", ",") if n % 1 else str(int(n))


def _id_articolo_riga(r):
    try:
        return int(str(r.get("id_articolo_magazzino") or "").strip())
    except ValueError:
        return None


def _indici_righe_magazzino(p):
    """Indici delle righe di un preventivo commerciale prese dal magazzino."""
    if p.get("tipo_preventivo") == "edile":
        return set()
    return {i for i, r in enumerate(p.get("righe", []))
            if _id_articolo_riga(r) and str(r.get("articolo", "")).strip()}


def _ordini_con_magazzino(p):
    """Ordini fornitore piu' un ordine 'virtuale' gia' confermato con le righe prese dal magazzino.
    Non viene mai salvato: serve a far seguire a queste righe il flusso consegne senza ordinarle."""
    ordini = list(p.get("ordini_fornitore", []))
    indici = sorted(_indici_righe_magazzino(p))
    if indici:
        ordini.append({
            "ordine_id": "MAGAZZINO", "numero_conferma": "MAGAZZINO", "azienda": "Magazzino interno",
            "indici_righe": indici, "data_arrivo": "", "da_magazzino": True,
        })
    return ordini


def calcola_prenotazioni_magazzino():
    """articolo_id -> {"qt": totale prenotato, "preventivi": [...]}.
    Prenotano le righe non ancora scaricate dei preventivi commerciali non annullati."""
    prenotazioni = {}
    db = _DBSession()
    try:
        rows = db.query(_Preventivo.numero, _Preventivo.cliente, _Preventivo.stato,
                        _Preventivo.tipo_preventivo, _Preventivo.righe).all()
    finally:
        db.close()
    for numero, cliente, stato, tipo, righe in rows:
        if stato == "Annullato" or tipo == "edile":
            continue
        for r in righe or []:
            aid = _id_articolo_riga(r)
            if not aid or r.get("magazzino_scaricato") or not str(r.get("articolo", "")).strip():
                continue
            qt = _to_num(r.get("qt"))
            if qt <= 0:
                continue
            voce = prenotazioni.setdefault(aid, {"qt": 0.0, "preventivi": []})
            voce["qt"] += qt
            voce["preventivi"].append({"numero": numero, "cliente": cliente or "", "stato": stato or "", "qt": qt})
    return prenotazioni


def _articoli_magazzino_con_disponibilita():
    prenotazioni = calcola_prenotazioni_magazzino()
    db = _DBSession()
    try:
        articoli = db.query(_ArticoloMagazzino).filter(_ArticoloMagazzino.attivo != False) \
                     .order_by(_ArticoloMagazzino.descrizione).all()
        lista = [a.to_dict() for a in articoli]
    finally:
        db.close()
    for a in lista:
        pren = prenotazioni.get(a["id"], {"qt": 0.0, "preventivi": []})
        a["prenotato"] = pren["qt"]
        a["prenotazioni"] = pren["preventivi"]
        a["disponibile"] = a["giacenza"] - pren["qt"]
        a["valore"] = a["giacenza"] * a["costo"]
    return lista


def _registra_movimento(db, articolo, delta, tipo, preventivo_id="", note="", costo_unitario=None):
    articolo.giacenza = (articolo.giacenza or 0.0) + delta
    articolo.aggiornato_il = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    mov = _MovimentoMagazzino(
        articolo_id=articolo.id, data=articolo.aggiornato_il, tipo=tipo, quantita=delta,
        giacenza_dopo=articolo.giacenza,
        costo_unitario=(articolo.costo or 0.0) if costo_unitario is None else costo_unitario,
        preventivo_id=preventivo_id,
        utente=session.get("user_name", "") if session else "", note=note)
    db.add(mov)
    return mov


def scarica_righe_magazzino(p, indici):
    """Scala dalla giacenza le righe consegnate prese dal magazzino (una volta sola per riga)."""
    if p.get("tipo_preventivo") == "edile":
        return
    righe = p.get("righe", [])
    db = _DBSession()
    try:
        for i in indici:
            if not (0 <= i < len(righe)):
                continue
            r = righe[i]
            aid = _id_articolo_riga(r)
            if not aid or r.get("magazzino_scaricato"):
                continue
            art = db.get(_ArticoloMagazzino, aid)
            qt = _to_num(r.get("qt"))
            if not art or qt <= 0:
                continue
            _registra_movimento(db, art, -qt, "scarico", p.get("numero", ""), "Consegna al cliente")
            r["magazzino_scaricato"] = _fmt_qt(qt)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def storna_righe_magazzino(p, indici):
    """Se una consegna viene annullata, rimette in giacenza quanto era stato scaricato."""
    if p.get("tipo_preventivo") == "edile":
        return
    righe = p.get("righe", [])
    db = _DBSession()
    try:
        for i in indici:
            if not (0 <= i < len(righe)):
                continue
            r = righe[i]
            aid = _id_articolo_riga(r)
            scaricato = _to_num(r.get("magazzino_scaricato"))
            if not aid or scaricato <= 0:
                continue
            art = db.get(_ArticoloMagazzino, aid)
            if art:
                _registra_movimento(db, art, scaricato, "storno", p.get("numero", ""), "Consegna annullata")
            r.pop("magazzino_scaricato", None)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def costo_righe_magazzino(p):
    """Costo delle righe di un preventivo prese dal magazzino (quantita' x costo salvato sulla riga).
    Nei conti CEO vale come costo reale del preventivo, al pari degli ordini fornitore."""
    costo = 0.0
    for i in _indici_righe_magazzino(p):
        r = p["righe"][i]
        prezzo = _to_num(r.get("prezzo_catalogo"))
        for s in ("s1", "s2", "s3"):
            prezzo *= 1 - _to_num(r.get(s)) / 100
        costo += prezzo * _to_num(r.get("qt"))
    return round(costo, 2)


def acquisti_magazzino(start_date, end_date):
    """Spesa per la merce messa in magazzino nel periodo (logica di cassa, come gli ordini fornitore):
    la quantita' iniziale di un articolo nuovo al suo costo e ogni "Carico merce" al prezzo pagato.
    Le correzioni da "Modifica" (errori, inventario), le consegne e gli storni non sono spese."""
    db = _DBSession()
    try:
        rows = (db.query(_MovimentoMagazzino, _ArticoloMagazzino.descrizione, _ArticoloMagazzino.codice)
                  .join(_ArticoloMagazzino, _ArticoloMagazzino.id == _MovimentoMagazzino.articolo_id)
                  .filter(_MovimentoMagazzino.tipo.in_(["creazione", "carico"])).all())
    finally:
        db.close()
    out = []
    for m, descrizione, codice in rows:
        d = _str_to_date((m.data or "")[:10])
        importo = round((m.quantita or 0.0) * (m.costo_unitario or 0.0), 2)
        if d and start_date <= d <= end_date and importo:
            out.append({"data": d, "articolo": descrizione or "", "codice": codice or "",
                        "quantita": m.quantita or 0.0, "costo_unitario": m.costo_unitario or 0.0,
                        "importo": importo, "note": m.note or ""})
    return out


@app.route("/magazzino")
@login_required
def dashboard_magazzino():
    articoli = _articoli_magazzino_con_disponibilita()
    return render_template("dashboard_magazzino.html",
        title="Magazzino",
        articoli=articoli,
        unita=UNITA_MAGAZZINO,
        puo_modificare=session.get("user_role") in RUOLI_GESTIONE_MAGAZZINO)


@app.route("/api/magazzino/articoli")
@login_required
def api_magazzino_articoli():
    return jsonify({"ok": True, "articoli": _articoli_magazzino_con_disponibilita()})


@app.route("/magazzino/articolo/salva", methods=["POST"])
@login_required
def salva_articolo_magazzino():
    if session.get("user_role") not in RUOLI_GESTIONE_MAGAZZINO:
        return jsonify({"ok": False, "error": "Non disponi delle autorizzazioni."}), 403
    data = request.get_json(silent=True) or request.form
    descrizione = str(data.get("descrizione", "")).strip()
    if not descrizione:
        return jsonify({"ok": False, "error": "La descrizione e' obbligatoria."}), 400
    unita = str(data.get("unita", "PZ")).strip().upper()
    if unita not in UNITA_MAGAZZINO:
        unita = "PZ"
    costo = _to_num(data.get("costo"))
    giacenza = _to_num(data.get("giacenza"))
    if costo < 0 or giacenza < 0:
        return jsonify({"ok": False, "error": "Costo e quantita' non possono essere negativi."}), 400

    db = _DBSession()
    try:
        articolo_id = str(data.get("id", "")).strip()
        adesso = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        if articolo_id:
            art = db.get(_ArticoloMagazzino, int(articolo_id))
            if not art or art.attivo is False:
                return jsonify({"ok": False, "error": "Articolo non trovato."}), 404
        else:
            art = _ArticoloMagazzino(descrizione=descrizione, giacenza=0.0, attivo=True, creato_il=adesso)
            db.add(art)
            db.flush()
        art.codice = str(data.get("codice", "")).strip()
        art.descrizione = descrizione
        art.unita = unita
        art.costo = round(costo, 2)
        art.note = str(data.get("note", "")).strip()
        art.aggiornato_il = adesso
        delta = round(giacenza - (art.giacenza or 0.0), 3)
        if delta:
            _registra_movimento(db, art, delta, "rettifica" if articolo_id else "creazione",
                                note=str(data.get("nota_movimento", "")).strip())
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[magazzino] Errore salvataggio articolo: {e}")
        return jsonify({"ok": False, "error": "Errore nel salvataggio."}), 500
    finally:
        db.close()
    return jsonify({"ok": True})


def costo_medio_ponderato(giacenza, costo, quantita, prezzo):
    """Costo medio dopo un carico: la merce gia' in magazzino pesa al suo costo, quella arrivata al prezzo pagato."""
    giacenza = max(giacenza or 0.0, 0.0)
    if giacenza + quantita <= 0:
        return prezzo
    return (giacenza * (costo or 0.0) + quantita * prezzo) / (giacenza + quantita)


@app.route("/magazzino/articolo/<int:articolo_id>/carico", methods=["POST"])
@login_required
def carico_articolo_magazzino(articolo_id):
    """Arrivo merce: aumenta la giacenza, registra la spesa al prezzo pagato e porta il costo
    dell'articolo al costo medio ponderato."""
    if session.get("user_role") not in RUOLI_GESTIONE_MAGAZZINO:
        return jsonify({"ok": False, "error": "Non disponi delle autorizzazioni."}), 403
    data = request.get_json(silent=True) or request.form
    quantita = _to_num(data.get("quantita"))
    prezzo = _to_num(data.get("prezzo"))
    if quantita <= 0:
        return jsonify({"ok": False, "error": "Inserisci la quantita' arrivata."}), 400
    if prezzo < 0:
        return jsonify({"ok": False, "error": "Il prezzo non puo' essere negativo."}), 400
    db = _DBSession()
    try:
        art = db.get(_ArticoloMagazzino, articolo_id)
        if not art or art.attivo is False:
            return jsonify({"ok": False, "error": "Articolo non trovato."}), 404
        costo_prima = art.costo or 0.0
        art.costo = round(costo_medio_ponderato(art.giacenza, art.costo, quantita, prezzo), 2)
        mov = _registra_movimento(db, art, quantita, "carico", note=str(data.get("note", "")).strip(),
                                  costo_unitario=round(prezzo, 2))
        mov.costo_precedente = costo_prima
        db.commit()
        nuovo_costo = art.costo
    except Exception as e:
        db.rollback()
        print(f"[magazzino] Errore carico articolo: {e}")
        return jsonify({"ok": False, "error": "Errore nel salvataggio."}), 500
    finally:
        db.close()
    return jsonify({"ok": True, "costo": nuovo_costo})


@app.route("/magazzino/articolo/<int:articolo_id>/elimina", methods=["POST"])
@login_required
def elimina_articolo_magazzino(articolo_id):
    if session.get("user_role") not in RUOLI_GESTIONE_MAGAZZINO:
        return jsonify({"ok": False, "error": "Non disponi delle autorizzazioni."}), 403
    if calcola_prenotazioni_magazzino().get(articolo_id):
        return jsonify({"ok": False, "error": "L'articolo e' prenotato su uno o piu' preventivi: libera prima le prenotazioni."}), 400
    db = _DBSession()
    try:
        art = db.get(_ArticoloMagazzino, articolo_id)
        if not art:
            return jsonify({"ok": False, "error": "Articolo non trovato."}), 404
        # Disattivato e non cancellato: le righe dei preventivi e lo storico continuano a puntarci.
        art.attivo = False
        art.aggiornato_il = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/magazzino/articolo/<int:articolo_id>/movimenti")
@login_required
def api_movimenti_magazzino(articolo_id):
    db = _DBSession()
    try:
        movimenti = db.query(_MovimentoMagazzino).filter_by(articolo_id=articolo_id) \
                      .order_by(_MovimentoMagazzino.id.desc()).limit(100).all()
        ultimo = _ultimo_carico(db, articolo_id)
        lista = []
        for m in movimenti:
            d = m.to_dict()
            d["modificabile"] = bool(ultimo and m.id == ultimo.id)
            lista.append(d)
        return jsonify({"ok": True, "movimenti": lista})
    finally:
        db.close()


def _ultimo_carico(db, articolo_id):
    """L'ultimo ingresso di merce (carico o quantita' iniziale): e' l'unico che si puo' correggere,
    perche' il costo medio dei carichi successivi dipende da quelli precedenti."""
    return db.query(_MovimentoMagazzino) \
             .filter(_MovimentoMagazzino.articolo_id == articolo_id,
                     _MovimentoMagazzino.tipo.in_(["creazione", "carico"])) \
             .order_by(_MovimentoMagazzino.id.desc()).first()


@app.route("/magazzino/movimento/<int:movimento_id>/correggi", methods=["POST"])
@login_required
def correggi_carico_magazzino(movimento_id):
    """Corregge (quantita'/prezzo) o elimina l'ultimo carico di un articolo.
    Giacenza, costo medio e spesa nel cashflow si ricalcolano; le righe dei preventivi no."""
    if session.get("user_role") not in RUOLI_GESTIONE_MAGAZZINO:
        return jsonify({"ok": False, "error": "Non disponi delle autorizzazioni."}), 403
    data = request.get_json(silent=True) or request.form
    elimina = str(data.get("elimina", "")).lower() in ("1", "true")
    db = _DBSession()
    try:
        mov = db.get(_MovimentoMagazzino, movimento_id)
        if not mov or mov.tipo not in ("creazione", "carico"):
            return jsonify({"ok": False, "error": "Carico non trovato."}), 404
        ultimo = _ultimo_carico(db, mov.articolo_id)
        if not ultimo or ultimo.id != mov.id:
            return jsonify({"ok": False, "error": "Si puo' correggere solo l'ultimo carico dell'articolo."}), 400
        if elimina and mov.tipo == "creazione":
            return jsonify({"ok": False, "error": "La quantita' iniziale si corregge, non si elimina."}), 400
        art = db.get(_ArticoloMagazzino, mov.articolo_id)
        quantita = 0.0 if elimina else _to_num(data.get("quantita"))
        prezzo = (mov.costo_unitario or 0.0) if elimina else _to_num(data.get("prezzo"))
        if not elimina and (quantita <= 0 or prezzo < 0):
            return jsonify({"ok": False, "error": "Inserisci quantita' e prezzo validi."}), 400
        delta = round(quantita - (mov.quantita or 0.0), 3)
        if (art.giacenza or 0.0) + delta < -1e-9:
            return jsonify({"ok": False, "error": "Una parte di questo carico e' gia' stata consegnata: "
                                                  "la giacenza andrebbe sotto zero."}), 400

        # Costo medio ricalcolato come se il carico fosse stato registrato giusto
        giacenza_prima = (mov.giacenza_dopo or 0.0) - (mov.quantita or 0.0)
        if mov.tipo == "creazione":
            costo_prima = 0.0
        elif mov.costo_precedente is not None:
            costo_prima = mov.costo_precedente
        else:
            costo_prima = art.costo or 0.0
        art.costo = round(costo_medio_ponderato(giacenza_prima, costo_prima, quantita, prezzo), 2) if quantita else costo_prima
        art.giacenza = (art.giacenza or 0.0) + delta
        art.aggiornato_il = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        # Le giacenze mostrate nello storico dopo questo carico si spostano della differenza
        for m in db.query(_MovimentoMagazzino).filter(_MovimentoMagazzino.articolo_id == art.id,
                                                      _MovimentoMagazzino.id > mov.id).all():
            m.giacenza_dopo = (m.giacenza_dopo or 0.0) + delta
        if elimina:
            db.delete(mov)
        else:
            nota = f"Corretto da {session.get('user_name', '')}: era {_fmt_qt(mov.quantita)} x {money_ui(mov.costo_unitario)}"
            mov.quantita = quantita
            mov.costo_unitario = round(prezzo, 2)
            mov.giacenza_dopo = giacenza_prima + quantita
            mov.note = (f"{mov.note} · " if mov.note else "") + nota
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[magazzino] Errore correzione carico: {e}")
        return jsonify({"ok": False, "error": "Errore nel salvataggio."}), 500
    finally:
        db.close()
    return jsonify({"ok": True})


# ===============================================
# === NUOVE ROUTE PER GESTIONE CONSEGNE/BOLLE ===
# ===============================================

def get_delivery_status(riga):
    """Helper per determinare lo stato di consegna di una riga."""
    status = riga.get("stato_consegna", "Da Consegnare")
    # Aggiunto un controllo per assicurarsi che 'status' sia una stringa
    if isinstance(status, str) and status.startswith("BOLLA-"):
        parts = status.split('-')
        # Controlla che il formato sia corretto (es. BOLLA-2024-123)
        if len(parts) == 3 and parts[2].isdigit():
            return f"Bolla N.{parts[2]}"
        else:
            return status # Restituisce l'ID se il formato non è standard
    return status

def _calculate_profits_from_quote(p):
    """
    Funzione helper che ricalcola l'utile e le fee per un singolo preventivo.
    Replica la logica di calcolo di salva_righe per estrarre i margini.
    """
    # Helper interni per la conversione sicura dei numeri
    def _to_num(x, default=0.0):
        if x is None: return float(default)
        s = re.sub(r"[€%\s]", "", str(x))
        if not s: return float(default)
        if "," in s and "." in s: s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
        s = s.replace(",", ".")
        try: return float(s)
        except ValueError: return float(default)
    
    quote_profit = 0.0
    quote_fee_value = 0.0
    
    fee_pct = _to_num(p.get("fee_pct"))
    fee_effettiva = fee_pct / 100 * 1.166 if fee_pct > 0 else 0

    for r in p.get("righe", []):
        if not r.get("articolo", "").strip(): continue

        # Costo di acquisto netto per l'articolo
        prezzo_scontato = (_to_num(r.get("prezzo_catalogo")) * (1 - _to_num(r.get("s1"))/100) * (1 - _to_num(r.get("s2"))/100) * (1 - _to_num(r.get("s3"))/100))
        
        costo_trasporto = _to_num(r.get("costo_trasporto"))
        ricarico_pct = _to_num(r.get("ricarico_pct")) / 100
        qt = _to_num(r.get("qt"))
        
        # Calcolo del valore della fee
        fee_su_prezzo = prezzo_scontato * fee_effettiva
        fee_su_trasporto = costo_trasporto * fee_effettiva
        quote_fee_value += (fee_su_prezzo + fee_su_trasporto) * qt

        # Calcolo del valore del ricarico
        prezzo_post_fee = prezzo_scontato * (1 + fee_effettiva)
        trasporto_post_fee = costo_trasporto * (1 + fee_effettiva)
        ricarico_su_prezzo = prezzo_post_fee * ricarico_pct
        ricarico_su_trasporto = trasporto_post_fee * ricarico_pct
        quote_profit += (ricarico_su_prezzo + ricarico_su_trasporto) * qt

    return {"profitto": quote_profit, "fee": quote_fee_value}
def _get_ordine_costo_effettivo_netto(ordine):
    """
    Calcola il costo totale effettivo NETTO (imponibile) di un ordine, 
    gestendo sia la nuova logica (campi separati) sia la vecchia (campo unico).
    """
    # Leggiamo i campi effettivi *salvati* (che sono LORDI, IVA INCLUSA)
    importo_articoli_lordo_salvato = _to_num(ordine.get("importo_articoli"))
    importo_trasporto_lordo_salvato = _to_num(ordine.get("importo_trasporto"))
    importo_totale_lordo_salvato = _to_num(ordine.get("importo")) # Vecchio campo
    
    costo_totale_lordo_da_usare = 0.0

    if "importo_articoli" in ordine:
        # CASO 1: Ordine "Nuovo" (o già modificato)
        costo_totale_lordo_da_usare = importo_articoli_lordo_salvato + importo_trasporto_lordo_salvato
    else:
        # CASO 2: Ordine "Legacy" (ha solo 'importo' totale)
        costo_totale_lordo_da_usare = importo_totale_lordo_salvato

    # Scorpora l'IVA (assumendo 22%) per ottenere il costo NETTO
    costo_netto = costo_totale_lordo_da_usare / 1.22
    
    return round(costo_netto, 2)



def _to_float(val):
    """Helper globale per conversione numeri"""
    if val is None or str(val).strip() == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    s = str(val).replace("€", "").replace("%", "").strip()
    if "," in s: s = s.replace(".", "").replace(",", ".")
    try: return float(s)
    except ValueError: return 0.0

def _get_netto_ordine(ordine):
    """
    Calcola il costo NETTO di un ordine.
    Se c'è l'IVA esplicita salvata, la sottrae.
    Altrimenti scorpora il 22% dal totale.
    """
    imp_lordo = _to_float(ordine.get("importo", 0))
    # Se abbiamo salvato l'IVA specifica dell'ordine, usiamo quella per avere il netto esatto.
    # Nel DB V3 la chiave 'iva_ordine' c'e' sempre (0 se mai inserita): conta solo se valorizzata.
    iva = _to_float(ordine.get("iva_ordine", 0))
    if iva:
        return imp_lordo - iva
    # Fallback: scorporo 22% forfettario
    return imp_lordo / 1.22


def _ratio_netto_incassi(p):
    """Quota netta (senza IVA) di ogni euro incassato sul preventivo.
    Esente IVA: il cliente paga solo l'imponibile, quindi tutto l'incasso e' netto."""
    if p.get("no_iva") is True or str(p.get("no_iva")).lower() == "true":
        return 1.0
    imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
    totale = _to_float(p.get("totale", 0))
    return (imponibile / totale) if totale > 0 else 1.0


def _costo_manuale_edile(p):
    """Costi stimati inseriti a mano sulle righe di un preventivo edile (unico costo reale degli edili)."""
    if p.get("tipo_preventivo") != "edile":
        return 0.0
    return sum(_to_float(r.get("costo_stimato")) for r in p.get("righe_edili", []))


def _data_transazione_ordine(ordine, p_date):
    """Data di cassa di un ordine fornitore: caricamento conferma d'ordine, poi data arrivo, poi data preventivo."""
    try:
        return datetime.datetime.strptime(ordine["allegati"][0]["data_upload"], "%Y-%m-%d").date()
    except Exception:
        pass
    try:
        return datetime.datetime.strptime(ordine.get("data_arrivo"), "%Y-%m-%d").date()
    except Exception:
        return p_date

@app.route("/dashboard/ceo")
@login_required
def dashboard_ceo():
    if session.get("user_role") not in ["amministratore", "ceo"]:
        flash("Accesso negato.", "error")
        return redirect(url_for("dashboard"))

    # --- 1. GESTIONE DATE ---
    today = datetime.date.today()
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    MIN_DATE = datetime.date(2025, 9, 1)

    if start_date_str:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        start_date = today.replace(day=1)
    if start_date < MIN_DATE:
        start_date = MIN_DATE

    if end_date_str:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    else:
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        end_date = next_month - datetime.timedelta(days=next_month.day)

    # --- 2. CARICAMENTO DATI: UNICA QUERY CON EAGER LOAD ORDINI ---
    from sqlalchemy.orm import joinedload
    db = _DBSession()
    try:
        all_preventivi = (
            db.query(_Preventivo)
            .options(
                joinedload(_Preventivo.ordini_rel),
                joinedload(_Preventivo.bolle_rel)
            )
            .all()
        )
    finally:
        db.close()

    # --- 3. INIZIALIZZAZIONE STRUTTURE ---
    kpi = {
        "imponibile_totale": 0.0, "costi_preventivati_totali": 0.0, "costi_reali_totali": 0.0,
        "scostamento_totale": 0.0, "fee_versata": 0.0, "utile_netto_finale": 0.0,
        "margine_medio_pct": 0.0, "marginalita_totale_pct": 0.0
    }
    cashflow = {
        "incassato_netto": 0.0, "in_attesa_netto": 0.0, "da_saldare_netto": 0.0,
        "costi_preventivi_in_corso": 0.0,
        "iva_preventivi": 0.0, "iva_ordini": 0.0, "iva_esente": 0.0,
        "fee_versata": 0.0,
        "bilancio": 0.0, "bilancio_iva": 0.0
    }
    funnel = {"creati": 0, "inviati": 0, "confermati": 0, "annullati": 0,
              "valore_in_trattativa": 0.0, "tasso_firma": 0.0}
    venditori_dict = {}
    referenti_dict = {}
    future_payments = []
    daily_stats = {}

    # --- 4. SINGOLO CICLO SU TUTTI I PREVENTIVI ---
    for prev_obj in all_preventivi:
        p = prev_obj.to_dict()  # Converte in dict compatibile col codice esistente

        st = p.get("stato", "")

        # Data di riferimento per la competenza
        raw_date = (
            p.get("data_conferma")
            if st in ["Confermato", "In Lavorazione", "Chiuso"] and p.get("data_conferma")
            else p.get("data")
        )
        try:
            p_date = datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
        except Exception:
            continue

        imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
        tot_lordo = _to_float(p.get("totale", 0))
        fee_pct = _to_float(p.get("fee_pct", 0))
        raw_no_iva = p.get("no_iva")
        is_no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")
        ratio_netto = _ratio_netto_incassi(p)

        # == A. LOGICA COMPETENZA (filtro su data preventivo nel range) ==
        in_periodo = start_date <= p_date <= end_date
        if in_periodo:
            funnel["creati"] += 1
            if st == "Bozza":
                funnel["valore_in_trattativa"] += imponibile
            elif st == "Inviato":
                funnel["inviati"] += 1
                funnel["valore_in_trattativa"] += imponibile
            elif st in ["Confermato", "In Lavorazione", "Chiuso"]:
                funnel["inviati"] += 1
                funnel["confermati"] += 1
            elif st == "Annullato":
                funnel["annullati"] += 1

        # KPI solo per preventivi confermati/lavorazione/chiusi
        if st in ["Confermato", "In Lavorazione", "Chiuso"]:
            if in_periodo:
                c_presunto = _to_float(p.get("tot_imponibile_negozio", 0))
                c_reale = 0.0

                # Costo edile: costo_stimato dalle righe_edili
                if p.get("tipo_preventivo") == "edile":
                    c_reale += sum(
                        _to_float(r.get("costo_stimato"))
                        for r in p.get("righe_edili", [])
                    )

                # Costo delle righe prese dal magazzino (vale come un ordine fornitore)
                c_reale += costo_righe_magazzino(p)

                # Costo da ordini fornitore (usati gli oggetti ORM gia caricati)
                for ordine_obj in prev_obj.ordini_rel:
                    ordine = ordine_obj.to_dict()
                    imp_lordo = _to_float(ordine.get("importo", 0))
                    iva_ord = _to_float(ordine.get("iva_ordine", 0))
                    c_ord_netto = (imp_lordo - iva_ord) if iva_ord else imp_lordo / 1.22
                    c_reale += c_ord_netto

                fee_val = imponibile * (fee_pct / 100.0) if fee_pct > 0 else 0.0
                c_rif = c_reale if c_reale > 0 else c_presunto
                margine = imponibile - c_rif

                kpi["imponibile_totale"] += imponibile
                kpi["costi_preventivati_totali"] += c_presunto
                kpi["costi_reali_totali"] += c_reale
                kpi["fee_versata"] += fee_val
                kpi["utile_netto_finale"] += margine

                # Statistiche per venditore (con tasso conversione)
                vnd = p.get("venditore", "N/D")
                if vnd not in venditori_dict:
                    venditori_dict[vnd] = {
                        "nome": vnd, "count": 0, "imponibile": 0.0,
                        "utile": 0.0, "inviati": 0, "tasso_conv": 0.0
                    }
                venditori_dict[vnd]["count"] += 1
                venditori_dict[vnd]["imponibile"] += imponibile
                venditori_dict[vnd]["utile"] += margine

                # Referenti
                ref = p.get("referente", "")
                if ref:
                    if ref not in referenti_dict:
                        referenti_dict[ref] = {"nome": ref, "preventivo": 0, "imponibile": 0.0, "fee": 0.0}
                    referenti_dict[ref]["preventivo"] += 1
                    referenti_dict[ref]["imponibile"] += imponibile
                    referenti_dict[ref]["fee"] += fee_val

                # Statistiche giornaliere per grafico
                d_str = raw_date
                if d_str not in daily_stats:
                    daily_stats[d_str] = {"imp": 0, "marg": 0, "fee": 0, "c_reale": 0, "c_pres": 0}
                daily_stats[d_str]["imp"] += imponibile
                daily_stats[d_str]["marg"] += margine
                daily_stats[d_str]["fee"] += fee_val
                daily_stats[d_str]["c_reale"] += c_rif
                daily_stats[d_str]["c_pres"] += c_presunto

                # Residuo da saldare
                # (pagamenti programmati compresi: quelli sono gia' "in attesa", non "da saldare")
                inc_tot_quote = sum(_to_float(x.get("importo", 0)) for x in p.get("pagamenti", []))
                dovuto_lordo = imponibile if is_no_iva else tot_lordo
                cashflow["da_saldare_netto"] += (dovuto_lordo - inc_tot_quote) * ratio_netto

            # == B. LOGICA CASSA (data pagamento, senza filtro periodo competenza) ==
            for pag in p.get("pagamenti", []):
                val_lordo = _to_float(pag.get("importo", 0))
                try:
                    d_pag = datetime.datetime.strptime(pag.get("data"), "%Y-%m-%d").date()
                except Exception:
                    d_pag = today

                val_netto = val_lordo * ratio_netto
                quota_iva = val_lordo - val_netto
                fee_su_incasso = val_netto * (fee_pct / 100.0) if fee_pct > 0 else 0.0

                if start_date <= d_pag <= end_date and not pag.get("is_scheduled"):
                    cashflow["incassato_netto"] += val_netto
                    cashflow["fee_versata"] += fee_su_incasso
                    if not is_no_iva:
                        cashflow["iva_preventivi"] += quota_iva
                    elif imponibile > 0:
                        # IVA esente per cassa: quota dell'IVA non applicata corrispondente all'incasso
                        cashflow["iva_esente"] += val_netto * _to_float(p.get("tot_iva", 0)) / imponibile

                if pag.get("is_scheduled"):
                    cashflow["in_attesa_netto"] += val_netto
                    future_payments.append({
                        "data": d_pag,
                        "cliente": p.get("cliente"),
                        "preventivo": p.get("numero"),
                        "importo_netto": val_netto,
                        "note": pag.get("note", "")
                    })

            # Uscite ordini fornitore (logica cassa: data transazione)
            for ordine_obj in prev_obj.ordini_rel:
                ordine = ordine_obj.to_dict()
                d_trans = _data_transazione_ordine(ordine, p_date)
                if start_date <= d_trans <= end_date:
                    cashflow["costi_preventivi_in_corso"] += _get_netto_ordine(ordine)
                    # IVA ordini per cassa: data conferma ordine (allegato) o arrivo, come in V2
                    cashflow["iva_ordini"] += _to_float(ordine.get("iva_ordine", 0))

            # Uscite edili: i costi stimati a mano sono l'unico costo reale degli edili,
            # alla data di conferma (come nell'export cashflow)
            if start_date <= p_date <= end_date:
                cashflow["costi_preventivi_in_corso"] += _costo_manuale_edile(p)

        # Conteggio preventivi inviati per tasso conversione venditore
        elif st == "Inviato" and in_periodo:
            vnd = p.get("venditore", "N/D")
            if vnd in venditori_dict:
                venditori_dict[vnd]["inviati"] += 1

    # Uscite per la merce caricata in magazzino (logica cassa: data del carico, come gli ordini)
    cashflow["acquisti_magazzino"] = sum(a["importo"] for a in acquisti_magazzino(start_date, end_date))
    cashflow["costi_preventivi_in_corso"] += cashflow["acquisti_magazzino"]

    # --- 5. CALCOLI FINALI ---
    # Tasso conversione per venditore
    for v in venditori_dict.values():
        tot = v["count"] + v["inviati"]
        v["tasso_conv"] = round((v["count"] / tot) * 100, 1) if tot > 0 else 0.0

    # Bilancio cassa
    cashflow["bilancio"] = (
        cashflow["incassato_netto"]
        - cashflow["costi_preventivi_in_corso"]
        - cashflow["fee_versata"]
    )
    cashflow["bilancio_iva"] = cashflow["iva_preventivi"] - cashflow["iva_ordini"]

    # Finalizzazione KPI
    kpi["scostamento_totale"] = kpi["costi_preventivati_totali"] - kpi["costi_reali_totali"]
    if kpi["imponibile_totale"] > 0:
        kpi["marginalita_totale_pct"] = (kpi["utile_netto_finale"] / kpi["imponibile_totale"]) * 100
        costi_netti = kpi["imponibile_totale"] - kpi["utile_netto_finale"]
        if costi_netti > 0:
            kpi["margine_medio_pct"] = (kpi["utile_netto_finale"] / costi_netti) * 100
    if funnel["creati"] > 0:
        funnel["tasso_firma"] = (funnel["confermati"] / funnel["creati"]) * 100

    venditori_list = sorted(venditori_dict.values(), key=lambda x: x["imponibile"], reverse=True)
    referenti_list = sorted(referenti_dict.values(), key=lambda x: x["fee"], reverse=True)
    future_payments.sort(key=lambda x: x["data"])
    sorted_dates = sorted(daily_stats.keys())

    grafico_out = {
        "labels": sorted_dates,
        "imponibile": [daily_stats[d]["imp"] for d in sorted_dates],
        "utile": [daily_stats[d]["marg"] for d in sorted_dates],
        "fee": [daily_stats[d]["fee"] for d in sorted_dates],
        "costi_effettivi": [daily_stats[d]["c_reale"] for d in sorted_dates],
        "costi_presunti": [daily_stats[d]["c_pres"] for d in sorted_dates]
    }

    return render_template("dashboard_ceo.html",
        title="Dashboard Direzionale",
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        kpi=kpi, cashflow=cashflow, funnel=funnel,
        venditori=venditori_list, referenti=referenti_list,
        future_payments=future_payments,
        grafico=grafico_out
    )

def _periodo_ceo():
    """Periodo richiesto dalla dashboard CEO (stesse regole e stessa data minima della dashboard)."""
    today = datetime.date.today()
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else today.replace(day=1)
    start_date = max(start_date, datetime.date(2025, 9, 1))
    if end_date_str:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    else:
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        end_date = next_month - datetime.timedelta(days=next_month.day)
    return start_date, end_date, start_date_str, end_date_str


def _preventivi_attivi_ceo():
    """Preventivi confermati / in lavorazione / chiusi, con la data di competenza (conferma, altrimenti data)."""
    db = _DBSession()
    try:
        from sqlalchemy.orm import joinedload
        prevs = db.query(_Preventivo).options(joinedload(_Preventivo.ordini_rel), joinedload(_Preventivo.bolle_rel)).all()
        out = []
        for prev_obj in prevs:
            p = prev_obj.to_dict()
            if p.get("stato") not in ("Confermato", "In Lavorazione", "Chiuso"):
                continue
            p_date = _str_to_date(p.get("data_conferma")) or _str_to_date(p.get("data"))
            if p_date:
                out.append((p, p_date))
        return out
    finally:
        db.close()


def _scrivi_foglio_tabella(ws, righe, formati_colonna=None):
    """Scrive le righe (dict con chiavi = intestazioni del modello) sotto l'intestazione del foglio,
    copiando il formato numerico dell'intestazione, e allarga la Tabella Excel del modello."""
    intestazioni = [c.value for c in ws[1]]
    formati = [c.number_format for c in ws[1]]
    chiavi = [str(h).strip() if h is not None else None for h in intestazioni]
    if ws.max_row > 1:
        ws.delete_rows(2, amount=ws.max_row - 1)
    righe = [{str(k).strip(): v for k, v in riga.items()} for riga in righe]
    for r_idx, riga in enumerate(righe, start=2):
        for c_idx, chiave in enumerate(chiavi, start=1):
            if chiave is None:
                continue
            cell = ws.cell(row=r_idx, column=c_idx, value=riga.get(chiave))
            fmt = (formati_colonna or {}).get(chiave) or formati[c_idx - 1]
            if isinstance(cell.value, (datetime.date, datetime.datetime)):
                fmt = "dd/mm/yyyy"
            if fmt and fmt != "General":
                cell.number_format = fmt
    for table in ws.tables.values():
        table.ref = f"A1:{get_column_letter(len(intestazioni))}{max(len(righe), 1) + 1}"
    ws.freeze_panes = "A2"
    for c_idx, chiave in enumerate(chiavi, start=1):
        valori = [riga.get(chiave) for riga in righe[:500]]
        lung = max([len(str(chiave or ""))] + [len(f"{v:,.2f}") if isinstance(v, float) else len(str(v or "")) for v in valori])
        ws.column_dimensions[get_column_letter(c_idx)].width = min(max(lung + 2, 10), 45)


def _invia_workbook(wb, filename):
    # Le formule del foglio CALCOLI vanno ricalcolate all'apertura (openpyxl non le calcola)
    wb.calculation.fullCalcOnLoad = True
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


_FMT_EURO = '#,##0.00\\ "€"'
_FMT_PCT = '0.0%'
_FMT_INT = '0'


class _FoglioCalcoli:
    """Costruisce il foglio CALCOLI di un export: sezioni con voci e tabelle di formule Excel
    che leggono la tabella dati (Tabella1), cosi' i totali seguono eventuali filtri o modifiche."""

    def __init__(self, wb, titolo, sottotitolo):
        from openpyxl.styles import Font, PatternFill, Alignment
        self.Font, self.PatternFill, self.Alignment = Font, PatternFill, Alignment
        idx = len(wb.sheetnames)
        if "CALCOLI" in wb.sheetnames:
            idx = wb.sheetnames.index("CALCOLI")
            del wb["CALCOLI"]
        self.ws = wb.create_sheet("CALCOLI", idx)
        self.ws.sheet_view.showGridLines = False
        self.ws["A1"] = titolo
        self.ws["A1"].font = Font(bold=True, size=14, color="1F2937")
        self.ws["A2"] = sottotitolo
        self.ws["A2"].font = Font(italic=True, size=10, color="6B7280")
        self.ws.column_dimensions["A"].width = 38
        for col in "BCDEFGHI":
            self.ws.column_dimensions[col].width = 17
        self.row = 4

    @staticmethod
    def col(nome):
        """Riferimento strutturato a una colonna di Tabella1 (doppie parentesi: vale anche con spazi e simboli)."""
        return f"Tabella1[[{nome}]]"

    def sezione(self, titolo, larghezza=2):
        self.row += 1
        for c in range(1, larghezza + 1):
            cell = self.ws.cell(row=self.row, column=c)
            cell.fill = self.PatternFill("solid", fgColor="1F2937")
            cell.font = self.Font(bold=True, color="FFFFFF")
        self.ws.cell(row=self.row, column=1, value=titolo)
        self.row += 1

    def voce(self, etichetta, formula, fmt=_FMT_EURO, nota=None, evidenzia=False):
        a = self.ws.cell(row=self.row, column=1, value=etichetta)
        b = self.ws.cell(row=self.row, column=2, value=formula)
        b.number_format = fmt
        if evidenzia:
            for cell in (a, b):
                cell.font = self.Font(bold=True)
                cell.fill = self.PatternFill("solid", fgColor="DCFCE7")
        if nota:
            n = self.ws.cell(row=self.row, column=3, value=nota)
            n.font = self.Font(italic=True, size=9, color="6B7280")
        ref = f"B{self.row}"
        self.row += 1
        return ref

    def tabella(self, intestazioni, righe, formati):
        """righe: lista di (etichetta, valore_prima_colonna_o_None, funzione(riga_excel, cella_etichetta) -> lista formule)."""
        self.row += 1
        for c, h in enumerate(intestazioni, start=1):
            cell = self.ws.cell(row=self.row, column=c, value=h)
            cell.font = self.Font(bold=True)
            cell.fill = self.PatternFill("solid", fgColor="E5E7EB")
            cell.alignment = self.Alignment(wrap_text=True, vertical="center")
        self.row += 1
        prima = self.row
        for etichetta, fmt_etichetta, formule in righe:
            cell = self.ws.cell(row=self.row, column=1, value=etichetta)
            if fmt_etichetta:
                cell.number_format = fmt_etichetta
                cell.alignment = self.Alignment(horizontal="left")
            for c, (f, fmt) in enumerate(zip(formule(self.row, f"$A{self.row}"), formati), start=2):
                x = self.ws.cell(row=self.row, column=c, value=f)
                x.number_format = fmt
            self.row += 1
        return prima, self.row - 1

    def riga_totale(self, prima, ultima, colonne, formati):
        cell = self.ws.cell(row=self.row, column=1, value="Totale")
        cell.font = self.Font(bold=True)
        for col, fmt in zip(colonne, formati):
            x = self.ws[f"{col}{self.row}"]
            x.value = f"=SUM({col}{prima}:{col}{ultima})"
            x.number_format = fmt
            x.font = self.Font(bold=True)
        self.row += 1


def _mesi_periodo(start_date, end_date, max_mesi=36):
    mesi, d = [], start_date.replace(day=1)
    while d <= end_date and len(mesi) < max_mesi:
        mesi.append(d)
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return mesi


def _calcoli_cashflow(wb, start_date, end_date, righe, n_programmati):
    C = _FoglioCalcoli.col
    f = _FoglioCalcoli(
        wb, "Riepilogo cashflow (per cassa)",
        f"Periodo {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')} | generato il "
        f"{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} | stesse regole della dashboard CEO")
    E, U, FEE, T, ID = C("ENTRATE NETTE (€)"), C("USCITE NETTE (€)"), C("FEE VERSATA "), C("TIPO"), C("ID (Rif.)")
    IVA_O, IVA_P, IVA_E, DT, VEN = C("IVA ORDINE (€)"), C("IVA PREVENTIVO (€)"), C("IVA ESENTE (€)"), C("DATA TRANSAZIONE"), C("VENDITORE")

    f.sezione("BILANCIO DI CASSA")
    entrate = f.voce("Entrate nette (incassi)", f"=SUM({E})", nota="Pagamenti incassati nel periodo, IVA esclusa; rettifiche comprese")
    f.voce("  Uscite ordini fornitore", f'=SUMIFS({U},{ID},"Ord.*")', nota="Alla data di conferma d'ordine o di arrivo")
    f.voce("  Uscite costi edili", f'=SUMIFS({U},{ID},"Costi Stimati*")', nota="Costi manuali dei preventivi edili, alla data di conferma")
    f.voce("  Uscite carichi magazzino", f'=SUMIFS({U},{ID},"Mag.*")', nota="Merce messa in magazzino, alla data del carico")
    uscite = f.voce("Totale uscite nette", f"=SUM({U})")
    fee = f.voce("Fee versata", f"=SUM({FEE})", nota="Calcolata sugli incassi")
    f.voce("BILANCIO (entrate - uscite - fee)", f"={entrate}-{uscite}-{fee}", evidenzia=True, nota="Uguale al riquadro Bilancio della dashboard CEO")

    f.sezione("IVA")
    iva_p = f.voce("IVA incassata sui preventivi", f"=SUM({IVA_P})")
    iva_o = f.voce("IVA pagata sugli ordini", f"=SUM({IVA_O})")
    f.voce("BILANCIO IVA (incassata - pagata)", f"={iva_p}-{iva_o}", evidenzia=True, nota="Positivo = IVA a debito")
    f.voce("IVA esente (non applicata sugli incassi)", f"=SUM({IVA_E})", nota="Solo informativa")

    f.sezione("MOVIMENTI")
    f.voce("Numero incassi", f'=COUNTIFS({T},"INCASSO")', fmt=_FMT_INT)
    f.voce("  di cui rettifiche", f'=COUNTIFS({ID},"Rettifica*")', fmt=_FMT_INT)
    f.voce("Numero uscite", f'=COUNTIFS({T},"USCITA")', fmt=_FMT_INT)

    f.sezione("INCASSI PROGRAMMATI (non ancora incassati, esclusi dal bilancio)")
    ultima = max(n_programmati, 1) + 1
    f.voce("Numero pagamenti programmati", f"=COUNTA(Programmati!A2:A{ultima})", fmt=_FMT_INT, nota="Dettaglio nel foglio Programmati")
    f.voce("Importo programmato (lordo)", f"=SUM(Programmati!F2:F{ultima})")
    f.voce("Importo programmato (netto)", f"=SUM(Programmati!G2:G{ultima})")

    f.sezione("ANDAMENTO MENSILE", larghezza=8)
    def _mese(r, a):
        fine = f"EOMONTH({a},0)"
        crit = f'{DT},">="&{a},{DT},"<="&{fine}'
        return [f"=SUMIFS({E},{crit})", f"=SUMIFS({U},{crit})", f"=SUMIFS({FEE},{crit})",
                f"=B{r}-C{r}-D{r}", f"=SUMIFS({IVA_P},{crit})", f"=SUMIFS({IVA_O},{crit})", f"=F{r}-G{r}"]
    p, u = f.tabella(["Mese", "Entrate nette", "Uscite nette", "Fee", "Bilancio", "IVA incassata", "IVA ordini", "Bilancio IVA"],
                     [(m, "mmmm yyyy", _mese) for m in _mesi_periodo(start_date, end_date)], [_FMT_EURO] * 7)
    f.riga_totale(p, u, "BCDEFGH", [_FMT_EURO] * 7)

    venditori = sorted({(x.get("VENDITORE") or "N/D") for x in righe if x.get("TIPO") == "INCASSO"})
    if venditori:
        f.sezione("ENTRATE PER VENDITORE", larghezza=4)
        f.tabella(["Venditore", "Entrate nette", "Fee", "% sulle entrate"],
                  [(v, None, lambda r, a: [f"=SUMIFS({E},{VEN},{a})", f"=SUMIFS({FEE},{VEN},{a})",
                                           f"=IF({entrate}=0,0,B{r}/{entrate})"]) for v in venditori],
                  [_FMT_EURO, _FMT_EURO, _FMT_PCT])


def _calcoli_analisi(wb, start_date, end_date, righe):
    C = _FoglioCalcoli.col
    f = _FoglioCalcoli(
        wb, "Riepilogo analisi preventivi (per competenza)",
        f"Preventivi confermati dal {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')} | generato il "
        f"{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} | stesse regole dei KPI della dashboard CEO")
    N, TOT, IMP, IVA = C("N. Preventivo"), C("Totale Preventivo (€)"), C("Imponibile Cliente (€)"), C("IVA (€)")
    COS, IVO, PRE, MAR = C("Costi da Ordini (€)"), C("IVA su Ordini (€)"), C("Costo Negozio Stimato (€)"), C("Margine (€)")
    FEE, INC, DAI, PRG = C("FEE (€)"), C("Incassato (€)"), C("Da Incassare (€)"), C("Programmato Futuro (€)")
    ST, STP, VEN, DATA, ES = C("Stato"), C("Stato Pagamento"), C("Venditore"), C("Data"), C("Esente IVA")

    f.sezione("PREVENTIVI")
    f.voce("Numero preventivi", f"=COUNTA({N})", fmt=_FMT_INT)
    f.voce("  di cui esenti IVA", f'=COUNTIFS({ES},"SÌ")', fmt=_FMT_INT)
    f.voce("Totale preventivi (IVA inclusa)", f"=SUM({TOT})")
    imp = f.voce("Imponibile clienti", f"=SUM({IMP})")
    f.voce("IVA sui preventivi", f"=SUM({IVA})")

    f.sezione("COSTI E MARGINE")
    reali = f.voce("Costi reali (ordini netti + costi edili)", f"=SUM({COS})")
    f.voce("IVA sugli ordini", f"=SUM({IVO})")
    presunti = f.voce("Costi presunti (da preventivo)", f"=SUM({PRE})")
    f.voce("Scostamento (presunti - reali)", f"={presunti}-{reali}", nota="Include i preventivi ancora senza ordini")
    marg = f.voce("MARGINE", f"=SUM({MAR})", evidenzia=True, nota="Imponibile meno costi reali (o presunti se non ci sono ordini)")
    f.voce("Margine % sull'imponibile", f"=IF({imp}=0,0,{marg}/{imp})", fmt=_FMT_PCT)
    f.voce("Fee", f"=SUM({FEE})")

    f.sezione("INCASSI")
    inc = f.voce("Incassato", f"=SUM({INC})", nota="Importi lordi, rettifiche comprese")
    dai = f.voce("Da incassare", f"=SUM({DAI})", evidenzia=True)
    prg = f.voce("  di cui gia' programmato", f"=SUM({PRG})")
    f.voce("  di cui da programmare", f"={dai}-{prg}")

    def _gruppo(colonna):
        return lambda r, a: [f"=COUNTIFS({colonna},{a})", f"=SUMIFS({IMP},{colonna},{a})",
                             f"=SUMIFS({MAR},{colonna},{a})", f"=IF(C{r}=0,0,D{r}/C{r})", f"=SUMIFS({DAI},{colonna},{a})"]
    intest = ["", "Preventivi", "Imponibile", "Margine", "Margine %", "Da incassare"]
    formati = [_FMT_INT, _FMT_EURO, _FMT_EURO, _FMT_PCT, _FMT_EURO]

    f.sezione("PER STATO", larghezza=6)
    f.tabella(["Stato"] + intest[1:], [(s, None, _gruppo(ST)) for s in ("Confermato", "In Lavorazione", "Chiuso")], formati)
    f.sezione("PER STATO PAGAMENTO", larghezza=6)
    f.tabella(["Stato pagamento"] + intest[1:], [(s, None, _gruppo(STP)) for s in ("Saldato", "Da Saldare")], formati)

    venditori = sorted({(x.get("Venditore") or "N/D") for x in righe})
    f.sezione("PER VENDITORE", larghezza=6)
    f.tabella(["Venditore"] + intest[1:], [(v, None, _gruppo(VEN)) for v in venditori], formati)

    f.sezione("PER MESE DI CONFERMA", larghezza=6)
    def _mese(r, a):
        crit = f'{DATA},">="&{a},{DATA},"<="&EOMONTH({a},0)'
        return [f"=COUNTIFS({crit})", f"=SUMIFS({IMP},{crit})", f"=SUMIFS({MAR},{crit})",
                f"=IF(C{r}=0,0,D{r}/C{r})", f"=SUMIFS({DAI},{crit})"]
    f.tabella(["Mese"] + intest[1:], [(m, "mmmm yyyy", _mese) for m in _mesi_periodo(start_date, end_date)], formati)


@app.route("/dashboard/ceo/export_cashflow")
@login_required
def export_cashflow_excel():
    """Cashflow per cassa, con le stesse regole della dashboard CEO: incassi alla data del pagamento
    (esclusi i programmati, elencati in un foglio a parte), ordini alla data di conferma ordine/arrivo,
    costi manuali edili alla data di conferma."""
    if session.get("user_role") not in ["amministratore", "ceo"]:
        flash("Accesso negato.", "error")
        return redirect(url_for("dashboard"))

    start_date, end_date, start_date_str, end_date_str = _periodo_ceo()

    template_filename = get_template_path("modello cashflow.xlsx")
    if not os.path.exists(template_filename):
        flash(f"File modello '{template_filename}' non trovato nel server!", "error")
        return redirect(url_for("dashboard_ceo"))

    cashflow_rows = []
    programmati = []
    for p, p_date in _preventivi_attivi_ceo():
        base = {"N. PREVENTIVO": p.get("numero"), "CLIENTE": p.get("cliente"),
                "STATO": p.get("stato"), "VENDITORE": p.get("venditore")}
        is_no_iva = (p.get("no_iva") is True) or (str(p.get("no_iva")).lower() == "true")
        imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
        ratio_netto = _ratio_netto_incassi(p)
        ratio_iva_esente = (_to_float(p.get("tot_iva", 0)) / imponibile) if (is_no_iva and imponibile > 0) else 0.0
        fee_pct = _to_float(p.get("fee_pct", 0))

        # --- A. ENTRATE (data del pagamento) ---
        for pag in p.get("pagamenti", []):
            d_pag = _str_to_date(pag.get("data"))
            lordo = _to_float(pag.get("importo", 0))
            netto = lordo * ratio_netto
            if pag.get("is_scheduled"):
                programmati.append({**base, "DATA PREVISTA": d_pag, "IMPORTO (€)": round(lordo, 2),
                                    "NETTO (€)": round(netto, 2), "NOTE": pag.get("note", "")})
                continue
            if not d_pag or not (start_date <= d_pag <= end_date):
                continue
            tipo_rif = "Rettifica" if pag.get("rectifies_id") else "Pagamento"
            cashflow_rows.append({
                **base,
                "ID (Rif.)": f"{tipo_rif} {pag.get('id', '')} {(pag.get('note') or '')[:30]}".strip(),
                "DATA TRANSAZIONE": d_pag,
                "ENTRATE NETTE (€)": round(netto, 2), "USCITE NETTE (€)": 0.0,
                "FEE VERSATA": round(netto * fee_pct / 100.0, 2) if fee_pct > 0 else 0.0,
                "IVA ORDINE (€)": 0.0,
                "IVA PREVENTIVO (€)": 0.0 if is_no_iva else round(lordo - netto, 2),
                "IVA ESENTE (€)": round(netto * ratio_iva_esente, 2),
                "TIPO": "INCASSO"
            })

        # --- B. USCITE: costi manuali edili (data conferma) ---
        costo_edile = _costo_manuale_edile(p)
        if costo_edile > 0 and start_date <= p_date <= end_date:
            cashflow_rows.append({
                **base, "ID (Rif.)": "Costi Stimati (Manuali Edile)", "DATA TRANSAZIONE": p_date,
                "ENTRATE NETTE (€)": 0.0, "USCITE NETTE (€)": round(costo_edile, 2), "FEE VERSATA": 0.0,
                "IVA ORDINE (€)": 0.0, "IVA PREVENTIVO (€)": 0.0, "IVA ESENTE (€)": 0.0, "TIPO": "USCITA"
            })

        # --- C. USCITE: ordini fornitore (data conferma ordine / arrivo) ---
        for ordine in p.get("ordini_fornitore", []):
            d_trans = _data_transazione_ordine(ordine, p_date)
            if not (start_date <= d_trans <= end_date):
                continue
            rif = f"Ord. {ordine.get('azienda', '')}"
            if ordine.get("numero_conferma"):
                rif += f" (conf. {ordine.get('numero_conferma')})"
            cashflow_rows.append({
                **base, "ID (Rif.)": rif, "DATA TRANSAZIONE": d_trans,
                "ENTRATE NETTE (€)": 0.0, "USCITE NETTE (€)": round(_get_netto_ordine(ordine), 2),
                "FEE VERSATA": 0.0, "IVA ORDINE (€)": round(_to_float(ordine.get("iva_ordine", 0)), 2),
                "IVA PREVENTIVO (€)": 0.0, "IVA ESENTE (€)": 0.0, "TIPO": "USCITA"
            })

    # --- D. USCITE: merce caricata in magazzino (data del carico) ---
    for a in acquisti_magazzino(start_date, end_date):
        cashflow_rows.append({
            "N. PREVENTIVO": "MAGAZZINO", "CLIENTE": "", "STATO": "", "VENDITORE": "",
            "ID (Rif.)": f"Mag. {a['codice'] + ' ' if a['codice'] else ''}{a['articolo']} ({_fmt_qt(a['quantita'])} x {money_ui(a['costo_unitario'])})",
            "DATA TRANSAZIONE": a["data"],
            "ENTRATE NETTE (€)": 0.0, "USCITE NETTE (€)": a["importo"], "FEE VERSATA": 0.0,
            "IVA ORDINE (€)": 0.0, "IVA PREVENTIVO (€)": 0.0, "IVA ESENTE (€)": 0.0, "TIPO": "USCITA"
        })

    if not cashflow_rows:
        flash("Nessuna transazione trovata nel periodo selezionato.", "warning")
        return redirect(url_for("dashboard_ceo", start_date=start_date_str, end_date=end_date_str))

    cashflow_rows.sort(key=lambda r: (r["DATA TRANSAZIONE"], r["TIPO"], r["N. PREVENTIVO"] or ""))
    wb = load_workbook(template_filename)
    _scrivi_foglio_tabella(wb["Cashflow"], cashflow_rows)

    # Foglio aggiuntivo: incassi programmati (entrano nelle entrate solo quando vengono incassati)
    if "Programmati" in wb.sheetnames:
        del wb["Programmati"]
    ws_p = wb.create_sheet("Programmati")
    ws_p.append(["N. PREVENTIVO", "CLIENTE", "STATO", "VENDITORE", "DATA PREVISTA", "IMPORTO (€)", "NETTO (€)", "NOTE"])
    for c in ws_p[1]:
        c.font = c.font.copy(bold=True)
        if "€" in str(c.value):
            c.number_format = '#,##0.00\\ "€"'
    _scrivi_foglio_tabella(ws_p, sorted(programmati, key=lambda r: r["DATA PREVISTA"] or datetime.date.max))
    _calcoli_cashflow(wb, start_date, end_date, cashflow_rows, len(programmati))

    filename = f"Cashflow_Dettagliato_{start_date.strftime('%d-%m')}_{end_date.strftime('%d-%m-%Y')}.xlsx"
    return _invia_workbook(wb, filename)


@app.route("/dashboard/ceo/export_excel")
@login_required
def export_excel_ceo():
    """Analisi per preventivo (competenza: data di conferma nel periodo), con costi e margini
    calcolati come nei KPI della dashboard CEO."""
    if session.get("user_role") not in ["amministratore", "ceo"]:
        flash("Accesso negato.", "error")
        return redirect(url_for("dashboard"))

    start_date, end_date, start_date_str, end_date_str = _periodo_ceo()

    template_filename = get_template_path("template_analisi.xlsx")
    if not os.path.exists(template_filename):
        flash(f"File modello '{template_filename}' non trovato nel server!", "error")
        return redirect(url_for("dashboard_ceo"))

    export_data = []
    for p, p_date in _preventivi_attivi_ceo():
        if not (start_date <= p_date <= end_date):
            continue
        is_no_iva = (p.get("no_iva") is True) or (str(p.get("no_iva")).lower() == "true")

        # Costi reali come nei KPI CEO: ordini al netto IVA + costi manuali edili
        costi_ordini = (sum(_get_netto_ordine(o) for o in p.get("ordini_fornitore", []))
                        + _costo_manuale_edile(p) + costo_righe_magazzino(p))
        iva_ordini = sum(_to_float(o.get("iva_ordine", 0)) for o in p.get("ordini_fornitore", []))
        costo_presunto = _to_float(p.get("tot_imponibile_negozio", 0))
        imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
        totale = _to_float(p.get("totale", 0))
        fee_pct = _to_float(p.get("fee_pct", 0))

        # Incassato = pagamenti registrati (rettifiche comprese, sono importi negativi); programmati a parte
        incassato = sum(_to_float(x.get("importo", 0)) for x in p.get("pagamenti", []) if not x.get("is_scheduled"))
        programmato = sum(_to_float(x.get("importo", 0)) for x in p.get("pagamenti", []) if x.get("is_scheduled"))
        dovuto = imponibile if is_no_iva else totale

        export_data.append({
            "N. Preventivo": p.get("numero"),
            "Data": p_date,
            "Cliente": p.get("cliente"),
            "Stato": p.get("stato"),
            "Totale Preventivo (€)": totale,
            "Imponibile Cliente (€)": imponibile,
            "IVA (€)": _to_float(p.get("tot_iva", 0)),
            "Costi da Ordini (€)": round(costi_ordini, 2),
            "IVA su Ordini (€)": round(iva_ordini, 2),
            "Costo Negozio Stimato (€)": costo_presunto,
            "Margine (€)": round(imponibile - (costi_ordini if costi_ordini > 0 else costo_presunto), 2),
            "FEE %": fee_pct / 100.0,
            "FEE (€)": round(imponibile * fee_pct / 100.0, 2) if fee_pct > 0 else 0.0,
            "Incassato (€)": round(incassato, 2),
            "Da Incassare (€)": round(dovuto - incassato, 2),
            "Programmato Futuro (€)": round(programmato, 2),
            "Esente IVA": "SÌ" if is_no_iva else "NO",
            "Stato Fattura": p.get("stato_fattura") or "N/D",
            "Stato Pagamento": p.get("stato_pagamento_globale") or "N/D",
            "Venditore": p.get("venditore"),
            "Stato Consegna": p.get("stato_consegna_globale") or "N/D"
        })

    if not export_data:
        flash("Nessun dato valido trovato (esclusi Bozze/Inviati/Annullati).", "warning")
        return redirect(url_for("dashboard_ceo", start_date=start_date_str, end_date=end_date_str))

    export_data.sort(key=lambda r: (r["Data"], r["N. Preventivo"]))
    wb = load_workbook(template_filename)
    if "Analisi" not in wb.sheetnames:
        flash("Il file modello non contiene un foglio chiamato 'Analisi'.", "error")
        return redirect(url_for("dashboard_ceo"))
    _scrivi_foglio_tabella(wb["Analisi"], export_data, formati_colonna={"FEE %": "0.0%"})
    _calcoli_analisi(wb, start_date, end_date, export_data)

    filename = f"Analisi_Globale_{start_date.strftime('%d-%m')}_{end_date.strftime('%d-%m-%Y')}.xlsx"
    return _invia_workbook(wb, filename)


@app.route("/preventivo/analisi/<quote_id>")
@login_required
@role_required('amministratore', 'ceo') 
def analisi_preventivo(quote_id):
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard"))

    # 1. Calcola Ricavi
    imponibile_cliente = _to_num(p.get("tot_imponibile_cliente"))
    iva_cliente = _to_num(p.get("tot_iva"))
    totale_cliente = _to_num(p.get("totale"))

    # 2. Calcola Costi
    costi_preventivati = _to_num(p.get("tot_imponibile_negozio"))
    
    costi_effettivi_netti = sum(
        _get_ordine_costo_effettivo_netto(o)
        for o in p.get("ordini_fornitore", [])
    )
    costi_effettivi_netti += costo_righe_magazzino(p)

    # Se è edile, integriamo il costo stimato manuale nei costi effettivi
    if p.get("tipo_preventivo") == "edile":
        costi_effettivi_netti += sum(_to_num(r.get("costo_stimato")) for r in p.get("righe_edili", []))
    
    # Recuperiamo i profitti stimati dal calcolo riga per riga
    profitti = _calculate_profits_from_quote(p)

    # --- NUOVO CALCOLO FEE SEMPLIFICATO ---
    # La fee è calcolata semplicemente come % sull'imponibile cliente totale
    fee_pct = _to_num(p.get("fee_pct"))
    fee_semplice_valore = imponibile_cliente * (fee_pct / 100)
    # --------------------------------------

    # Calcolo Utile Effettivo
    utile_netto_effettivo = imponibile_cliente - costi_effettivi_netti

    # 4. Assembla i dati di analisi
    analisi = {
        'imponibile_cliente': imponibile_cliente,
        'iva_cliente': iva_cliente,
        'totale_cliente': totale_cliente,
        'costi_preventivati': costi_preventivati,
        'costi_effettivi_netti': costi_effettivi_netti if costi_effettivi_netti > 0 else 0.0,
        
        'utile_netto_stimato': profitti.get('profitto', 0.0), 
        'utile_netto_effettivo': utile_netto_effettivo,
        
        # Usiamo il valore calcolato semplicemente
        'fee_versata': fee_semplice_valore, 
        
        'scostamento_costi': 0.0,
        'margine_lordo_pct': 0.0, 
        'utile_netto_effettivo_pct': 0.0, 
        'giorni_per_chiusura': 'N/D'
    }

    # 5. Calcola Redditività e Scostamento
    # Scostamento = Costi Preventivati - Costi Effettivi Netti
    if analisi['costi_effettivi_netti'] > 0: 
        analisi['scostamento_costi'] = analisi['costi_preventivati'] - analisi['costi_effettivi_netti']

    if imponibile_cliente > 0:
        # Margine Lordo % (basato su costo preventivato)
        margine_lordo = imponibile_cliente - costi_preventivati
        analisi['margine_lordo_pct'] = (margine_lordo / imponibile_cliente) * 100

    # Utile Effettivo %
    if imponibile_cliente > 0:
        analisi['utile_netto_effettivo_pct'] = (analisi['utile_netto_effettivo'] / imponibile_cliente) * 100

    # 6. Calcola Tempo Chiusura
    data_conferma_str = p.get("data_conferma")
    data_chiusura_str = p.get("data_chiusura")
    if p.get("stato") == "Chiuso" and data_conferma_str and data_chiusura_str:
        try:
            data_conferma_dt = datetime.datetime.strptime(data_conferma_str, '%Y-%m-%d').date()
            data_chiusura_dt = datetime.datetime.strptime(data_chiusura_str, '%Y-%m-%d').date()
            giorni = (data_chiusura_dt - data_conferma_dt).days
            if giorni >= 0:
                 analisi['giorni_per_chiusura'] = giorni
        except (ValueError, TypeError): pass

    return render_template("analisi_preventivo.html",
        title=f"Analisi Preventivo {p.get('numero')}",
        p=p,
        analisi=analisi
    )
@app.route("/cliente/analisi/<client_id>")
@login_required
@role_required('amministratore', 'ceo')
def analisi_cliente(client_id):
    client = load_client(client_id)
    if not client:
        flash("Cliente non trovato.", "error")
        return redirect(url_for("dashboard_clienti"))

    today = datetime.date.today()

    # 1. Inizializzazione Totali
    analisi = {
        'imponibile_cliente': 0.0,      # Totale Ricavi
        'costi_preventivati': 0.0,      # Totale Costi Presunti (Negozio)
        'costi_effettivi_netti': 0.0,   # Totale Costi Reali (Ordini)
        'utile_netto_stimato': 0.0,     # Utile basato sul preventivo
        'utile_netto_effettivo': 0.0,   # Utile basato sul reale
        'fee_versata': 0.0,             # Totale Fee (Calcolo Semplificato)
        'scostamento_costi': 0.0,       # Risparmio o Spesa extra
        
        'incassato': 0.0,
        'da_incassare': 0.0,
        
        # Percentuali medie
        'margine_lordo_pct': 0.0,
        'utile_netto_effettivo_pct': 0.0
    }
    
    funnel = {'creati': 0, 'inviati': 0, 'confermati': 0, 'annullati': 0}
    tempi_chiusura_list = []
    preventivi_analizzati = [] 

    # 2. Iterazione e Aggregazione
    for summary in get_all_quotes():
        p = load_quote(summary["numero"])
        if not p or p.get("id_cliente") != client_id:
            continue

        stato = p.get("stato")
        
        # Funnel Counters
        funnel['creati'] += 1
        if stato != "Bozza": funnel['inviati'] += 1
        if stato in ["Confermato", "In Lavorazione", "Chiuso"]: funnel['confermati'] += 1
        if stato == "Annullato": funnel['annullati'] += 1

        # --- CALCOLI FINANZIARI (Solo su preventivi attivi/chiusi) ---
        if stato in ["Confermato", "In Lavorazione", "Chiuso"]:
            
            # A. Valori Base
            imp_cliente = _to_num(p.get("tot_imponibile_cliente"))
            costo_prev = _to_num(p.get("tot_imponibile_negozio"))
            
            # B. Costi Effettivi (Somma ordini netti)
            costo_eff = sum(_get_ordine_costo_effettivo_netto(o) for o in p.get("ordini_fornitore", []))
            costo_eff += costo_righe_magazzino(p)
            
            # Se è edile, integriamo il costo stimato manuale nei costi effettivi
            if p.get("tipo_preventivo") == "edile":
                costo_eff += sum(_to_num(r.get("costo_stimato")) for r in p.get("righe_edili", []))
            
            # C. Fee Semplificata (Imponibile * Fee%)
            fee_pct = _to_num(p.get("fee_pct"))
            fee_val = imp_cliente * (fee_pct / 100)
            
            # D. Utili
            # Utile Stimato = Imponibile - Costo Previsto (fee esclusa dal calcolo utile puro qui, la mostriamo a parte)
            # Nota: per coerenza con l'analisi singola, usiamo la logica dei profitti stimati
            profitti_dettaglio = _calculate_profits_from_quote(p) 
            utile_stimato = profitti_dettaglio.get('profitto', 0.0)

            utile_effettivo = imp_cliente - costo_eff

            # E. Scostamento
            scostamento = costo_prev - costo_eff if costo_eff > 0 else 0.0

            # AGGREGAZIONE TOTALI
            analisi['imponibile_cliente'] += imp_cliente
            analisi['costi_preventivati'] += costo_prev
            analisi['costi_effettivi_netti'] += costo_eff
            analisi['utile_netto_stimato'] += utile_stimato
            analisi['utile_netto_effettivo'] += utile_effettivo
            analisi['fee_versata'] += fee_val
            if costo_eff > 0:
                analisi['scostamento_costi'] += scostamento

            # Dati per Tabella Dettaglio
            preventivi_analizzati.append({
                'numero': p.get('numero'),
                'data': p.get('data'),
                'stato': stato,
                'imponibile': imp_cliente,
                'costo_eff': costo_eff,
                'utile_eff': utile_effettivo,
                'scostamento': scostamento
            })

            # Tempo Chiusura
            data_conf = p.get("data_conferma")
            data_chius = p.get("data_chiusura")
            if stato == "Chiuso" and data_conf and data_chius:
                try:
                    d1 = datetime.datetime.strptime(data_conf, '%Y-%m-%d').date()
                    d2 = datetime.datetime.strptime(data_chius, '%Y-%m-%d').date()
                    giorni = (d2 - d1).days
                    if giorni >= 0: tempi_chiusura_list.append(giorni)
                except: pass

        # Cash Flow (incassi - distingue tra incassato e da incassare via flag)
        for pag in p.get("pagamenti", []):
            imp_pag = _to_num(pag.get("importo"))
            if pag.get("is_scheduled"):
                if imp_pag > 0:
                    analisi['da_incassare'] += imp_pag
            else:
                # Le rettifiche sono importi negativi che stornano un pagamento: vanno sommate,
                # altrimenti il pagamento stornato resterebbe contato come incassato
                analisi['incassato'] += imp_pag

    # 3. Calcolo Percentuali Medie Finali
    if analisi['imponibile_cliente'] > 0:
        margine_lordo = analisi['imponibile_cliente'] - analisi['costi_preventivati']
        analisi['margine_lordo_pct'] = (margine_lordo / analisi['imponibile_cliente']) * 100
        analisi['utile_netto_effettivo_pct'] = (analisi['utile_netto_effettivo'] / analisi['imponibile_cliente']) * 100

    # Tempo medio
    analisi['tempo_medio_chiusura'] = round(sum(tempi_chiusura_list) / len(tempi_chiusura_list), 1) if tempi_chiusura_list else "N/D"
    
    if funnel['inviati'] > 0:
        funnel['tasso_firma_num'] = (funnel['confermati'] / funnel['inviati']) * 100
    else:
        funnel['tasso_firma_num'] = 0.0

    preventivi_analizzati.sort(key=lambda x: x['data'], reverse=True)

    return render_template("analisi_cliente.html", 
        title=f"Analisi Cliente {client.get('cliente')}", 
        client=client, 
        analisi=analisi,
        funnel=funnel,
        preventivi=preventivi_analizzati
    )
@app.route("/ordini")
@login_required
def dashboard_ordini():
    """Pagina che elenca i preventivi con ordini fornitore da gestire."""
    preventivi_con_ordini = []
    today = datetime.date.today()
    
    tutti_i_preventivi = get_all_quotes()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p: continue

        if p.get("stato") in ["Bozza", "Inviato", "Chiuso", "Annullato"]:
            continue
            
        # --- INIZIO NUOVA LOGICA ---

        # 1. Troviamo tutti gli indici delle righe valide (con un articolo)
        indici_righe_valide = {
            i for i, r in enumerate(p.get("righe", [])) 
            if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"
        }
        
        # 2. Troviamo tutti gli indici degli articoli già assegnati a un ordine
        indici_gia_ordinati = set()
        ordini_fornitore = p.get("ordini_fornitore", [])
        for ordine in ordini_fornitore:
            indici_gia_ordinati.update(ordine.get("indici_righe", []))
        # Le righe prese dal magazzino non vanno ordinate al fornitore
        indici_gia_ordinati.update(_indici_righe_magazzino(p))

        # 3. Calcoliamo gli articoli ancora da ordinare
        articoli_da_ordinare_count = len(indici_righe_valide - indici_gia_ordinati)
        p["articoli_da_ordinare_count"] = articoli_da_ordinare_count

        # 4. Calcoliamo (come prima) gli articoli in ordini in attesa di conferma
        articoli_in_attesa_conferma = 0
        ordini_in_attesa = [o for o in ordini_fornitore if not o.get("numero_conferma", "").strip()]
        for ordine in ordini_in_attesa:
            articoli_in_attesa_conferma += len(ordine.get("indici_righe", []))
        p["articoli_in_attesa_conferma"] = articoli_in_attesa_conferma

        # 5. Dettagli per la dashboard (avanzamento, fornitori, giorni dalla conferma)
        p["articoli_totali"] = len(indici_righe_valide)
        p["articoli_ordinati"] = len(indici_righe_valide & indici_gia_ordinati)
        p["pct_ordinato"] = round(p["articoli_ordinati"] / p["articoli_totali"] * 100) if p["articoli_totali"] else 0
        p["ordini_count"] = len(ordini_fornitore)
        p["ordini_attesa_count"] = len(ordini_in_attesa)
        p["ordini_confermati_count"] = len(ordini_fornitore) - len(ordini_in_attesa)
        p["fornitori"] = sorted({o.get("azienda", "").strip() for o in ordini_fornitore if o.get("azienda", "").strip()})
        rif = _str_to_date(p.get("data_conferma")) or _str_to_date(p.get("data"))
        p["giorni_da_conferma"] = (today - rif).days if rif else None
        p["totale_num"] = _to_float(p.get("totale"))

        # 6. Aggiungiamo il preventivo alla dashboard SOLO se c'è qualcosa da fare
        if articoli_da_ordinare_count > 0 or articoli_in_attesa_conferma > 0:
            preventivi_con_ordini.append(p)
            
        # --- FINE NUOVA LOGICA ---

    return render_template("dashboard_ordini.html", 
        title="Dashboard Ordini Fornitore",
        preventivi=preventivi_con_ordini
    )
# --- File: gestionale.py (intorno alla riga 1970) ---

@app.route("/consegne")
@login_required
def dashboard_consegne():
    """Pagina che elenca i preventivi con ordini confermati da consegnare."""
    preventivi_da_consegnare = []
    today = datetime.date.today()

    def _conta_stati(righe):
        conteggio = {"da_consegnare": 0, "pronti": 0, "in_bolla": 0, "consegnati": 0}
        for r in righe:
            stato = r.get("stato_consegna") or "Da Consegnare"
            if stato == "Consegnato": conteggio["consegnati"] += 1
            elif stato == "In Bolla": conteggio["in_bolla"] += 1
            elif stato == "Pronto per Consegna": conteggio["pronti"] += 1
            else: conteggio["da_consegnare"] += 1
        conteggio["totale"] = len(righe)
        conteggio["pct_consegnato"] = round(conteggio["consegnati"] / len(righe) * 100) if righe else 0
        return conteggio
    
    tutti_i_preventivi = get_all_quotes()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p: continue

        if p.get("stato") in ["Bozza", "Inviato", "Chiuso", "Annullato"]:
            continue

        # Gestione Preventivi Edili
        if p.get("tipo_preventivo") == "edile":
            if p.get("stato") in ["Confermato", "In Lavorazione"]:
                non_consegnati_count = 0
                for sezione in p.get("sezioni_edili", []):
                    for r in sezione.get("righe", []):
                        if r.get("stato_consegna") != "Consegnato":
                            non_consegnati_count += 1
                
                if non_consegnati_count > 0:
                    p["articoli_da_consegnare_count"] = non_consegnati_count
                    righe_edili = [r for s in p.get("sezioni_edili", []) for r in s.get("righe", [])]
                    p["consegna"] = _conta_stati(righe_edili)
                    p["articoli_non_confermati"] = 0
                    p["fornitori"] = []
                    p["prossimo_arrivo"] = None
                    p["arrivo_in_ritardo"] = False
                    p["totale_num"] = _to_float(p.get("totale"))
                    preventivi_da_consegnare.append(p)
            continue

        ordini_confermati = [o for o in _ordini_con_magazzino(p) if o.get("numero_conferma", "").strip()]
        if not ordini_confermati: continue

        # --- RECUPERO INDICI CONFERMATI ---
        indici_confermati = set()
        for o in ordini_confermati:
            indici_confermati.update(o.get("indici_righe", []))

        # --- NUOVA LOGICA CORRETTA ---
        # Trova tutti gli articoli degli ordini confermati che NON sono ancora stati "Consegnati"
        articoli_non_consegnati = []
        for index in indici_confermati:
            if 0 <= index < len(p["righe"]):
                riga = p["righe"][index]
                if riga.get("stato_consegna") != "Consegnato":
                    articoli_non_consegnati.append(riga)

        # Aggiungi il preventivo alla lista SOLO se c'è almeno un articolo non consegnato
        if articoli_non_consegnati:
            # Il conteggio ora riflette TUTTI gli articoli in attesa (inclusi quelli in bolla)
            p["articoli_da_consegnare_count"] = len(articoli_non_consegnati)

            righe_confermate = [p["righe"][i] for i in indici_confermati if 0 <= i < len(p["righe"])]
            p["consegna"] = _conta_stati(righe_confermate)
            righe_valide = [r for r in p.get("righe", []) if r.get("articolo", "").strip() and r.get("unt", "").strip().upper() != "S"]
            p["articoli_non_confermati"] = max(len(righe_valide) - len(righe_confermate), 0)
            p["fornitori"] = sorted({o.get("azienda", "").strip() for o in ordini_confermati if o.get("azienda", "").strip()})

            # Prossimo arrivo previsto tra gli ordini che hanno ancora merce non arrivata
            date_arrivo = []
            for o in ordini_confermati:
                in_attesa = any(
                    0 <= i < len(p["righe"]) and (p["righe"][i].get("stato_consegna") or "Da Consegnare") == "Da Consegnare"
                    for i in o.get("indici_righe", [])
                )
                d = _str_to_date(o.get("data_arrivo"))
                if in_attesa and d: date_arrivo.append(d)
            prossimo = min(date_arrivo) if date_arrivo else None
            p["prossimo_arrivo"] = prossimo.strftime('%Y-%m-%d') if prossimo else None
            p["arrivo_in_ritardo"] = bool(prossimo and prossimo < today)
            p["totale_num"] = _to_float(p.get("totale"))
            preventivi_da_consegnare.append(p)
        # --- FINE NUOVA LOGICA ---

    return render_template("dashboard_consegne.html", 
        title="Ordini da Consegnare",
        preventivi=preventivi_da_consegnare
    )

@app.route("/consegna/<quote_id>")
@login_required
def gestione_consegna(quote_id):
    p = load_quote(quote_id)
    if not p: return redirect(url_for("dashboard_consegne"))

    if p.get("tipo_preventivo") == "edile":
        # Usiamo l'appiattimento centralizzato
        items = get_flat_righe_edili(p)
            
        ordini_confermati = [{
            "numero_conferma": "LAVORAZIONI EDILI",
            "azienda": "Gestione Interna",
            "data_arrivo": p.get("data"),
            "articoli": items
        }]
    else:
        ordini_confermati = [o for o in _ordini_con_magazzino(p) if o.get("numero_conferma", "").strip()]
        
        for ordine in ordini_confermati:
            items_in_ordine = []
            for item_index in ordine.get("indici_righe", []):
                if 0 <= item_index < len(p["righe"]):
                    riga = p["righe"][item_index]
                    riga["original_index"] = item_index
                    items_in_ordine.append(riga)
            ordine["articoli"] = items_in_ordine

   
    # Funzione che controlla se un ordine è completato (tutti gli articoli 'Consegnato')
    def is_ordine_completato(ordine):
        if not ordine.get("articoli"):
            return True # Un ordine senza articoli è considerato "completato"
        return all(item.get("stato_consegna") == "Consegnato" for item in ordine["articoli"])

    # Ordina la lista: gli ordini NON completati (False) verranno prima di quelli completati (True)
    ordini_confermati.sort(key=is_ordine_completato)
    # --- FINE LOGICA DI ORDINAMENTO ---

    return render_template("gestione_consegna.html",
        title=f"Gestione Consegna {quote_id}",
        p=p,
        ordini_confermati=ordini_confermati,
        geo_data=GEO_DATA
    )
# --- File: gestionale.py (intorno alla riga 2043) ---

@app.route("/consegna/<quote_id>/marca-pronto", methods=["POST"])
@login_required
def marca_pronto(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici_da_marcare = [int(i) for i in request.form.getlist("selected_items[]")]
    if not indici_da_marcare:
        return jsonify({"success": False, "error": "Nessun articolo selezionato"})

    # Seleziona la lista corretta in base al tipo
    target_list = "righe_edili" if p.get("tipo_preventivo") == "edile" else "righe"

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    if p.get("tipo_preventivo") == "edile":
        for idx_assoluto in indici_da_marcare:
            curr_idx = 0
            for sezione in p.get("sezioni_edili", []):
                for riga in sezione.get("righe", []):
                    if curr_idx == idx_assoluto:
                        riga["stato_consegna"] = "Pronto per Consegna"
                        riga["data_arrivo_in_house"] = today_str
                    curr_idx += 1

    else:
        for index in indici_da_marcare:
            if 0 <= index < len(p["righe"]):
                p["righe"][index]["stato_consegna"] = "Pronto per Consegna"
                p["righe"][index]["data_arrivo_in_house"] = today_str

    aggiorna_stato_consegna_globale(p) 


    save_quote(quote_id, p)
    return jsonify({"success": True})


@app.route("/consegna/<quote_id>/marca-consegnato", methods=["POST"])
@login_required
def marca_consegnato(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        return jsonify({"success": False, "error": "Non disponi delle autorizzazioni."})
    
    p = load_quote(quote_id)
    file = request.files.get('file')
    if not file:
        return jsonify({"success": False, "error": "Documento firmato obbligatorio."})

    indici_da_marcare = [int(i) for i in request.form.getlist("selected_items[]")]
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    # Salvataggio File
    quote_dir = ALLEGATI_DIR / quote_id
    quote_dir.mkdir(parents=True, exist_ok=True)
    filename = secure_filename(f"BOLLA_FIRMATA_{datetime.datetime.now().strftime('%H%M%S')}_{file.filename}")
    file.save(quote_dir / filename)

    # Aggiunta agli allegati del preventivo
    if "allegati" not in p: 
        p["allegati"] = []
    
    p["allegati"].append({
        "filename": filename,
        "descrizione": "Bolla di consegna firmata (Upload automatico)",
        "data_upload": today_str
    })

    if p.get("tipo_preventivo") == "edile":
        for idx_assoluto in indici_da_marcare:
            curr_idx = 0
            for sezione in p.get("sezioni_edili", []):
                for riga in sezione.get("righe", []):
                    if curr_idx == idx_assoluto:
                        riga["stato_consegna"] = "Consegnato"
                        riga["data_consegna"] = today_str
                    curr_idx += 1
    else:
        for index in indici_da_marcare:
            if 0 <= index < len(p["righe"]):
                p["righe"][index]["stato_consegna"] = "Consegnato"
                p["righe"][index]["data_consegna"] = today_str
        # Gli articoli presi dal magazzino escono dalla giacenza alla consegna
        scarica_righe_magazzino(p, indici_da_marcare)

    aggiorna_stato_consegna_globale(p)
    aggiorna_stato_avanzamento(p)
    save_quote(quote_id, p)
    return jsonify({"success": True})


@app.route("/consegna/<quote_id>/annulla-stato", methods=["POST"])
@login_required
def annulla_stato_consegna(quote_id):
    """
    Riporta uno o più articoli a uno stato di consegna precedente.
    Può opzionalmente scollegarli da una bolla esistente.
    """
    p = load_quote(quote_id)
    if not p:
        return jsonify({"success": False, "error": "Preventivo non trovato"})

    form = request.form
    target_status = form.get("target_status")
    keep_bolla = form.get("keep_bolla") == "true"
    item_indices = [int(i) for i in form.getlist("indices[]")]

    # --- File: gestionale.py (intorno alla riga 2091) ---

    if not item_indices or not target_status:
        return jsonify({"success": False, "error": "Dati mancanti per l'operazione."})

    is_edile = p.get("tipo_preventivo") == "edile"

    if is_edile:
        for idx_assoluto in item_indices:
            curr_idx = 0
            for sezione in p.get("sezioni_edili", []):
                for riga in sezione.get("righe", []):
                    if curr_idx == idx_assoluto:
                        original_bolla_id = riga.get("bolla_id")
                        riga["stato_consegna"] = target_status
                        riga.pop("data_consegna", None)

                        if target_status == "Da Consegnare":
                            riga.pop("data_arrivo_in_house", None)

                        if original_bolla_id and not keep_bolla:
                            riga.pop("bolla_id", None)
                            for bolla in p.get("bolle", []):
                                if bolla.get("id") == original_bolla_id:
                                    if idx_assoluto in bolla.get("indici_righe", []):
                                        bolla["indici_righe"].remove(idx_assoluto)
                                    break
                    curr_idx += 1
    else:
        target_list = "righe"
        for index in item_indices:
            if 0 <= index < len(p[target_list]):
                riga = p[target_list][index]
                original_bolla_id = riga.get("bolla_id")

                riga["stato_consegna"] = target_status
                riga.pop("data_consegna", None) 

                if target_status == "Da Consegnare":
                    riga.pop("data_arrivo_in_house", None) 

                if original_bolla_id and not keep_bolla:
                    riga.pop("bolla_id", None)
                    for bolla in p.get("bolle", []):
                        if bolla.get("id") == original_bolla_id:
                            if index in bolla.get("indici_righe", []):
                                bolla["indici_righe"].remove(index)
                            break
        # Consegna annullata: quanto era stato scaricato dal magazzino torna in giacenza
        if target_status != "Consegnato":
            storna_righe_magazzino(p, item_indices)
    
    # Ricalcola lo stato globale e salva
    aggiorna_stato_consegna_globale(p)
    aggiorna_stato_avanzamento(p)
    save_quote(quote_id, p)

    return jsonify({"success": True, "message": "Stato degli articoli aggiornato."})

def get_new_bolla_id(preventivo_data):
    """Genera un ID progressivo per la bolla, specifico per il preventivo."""
    now = datetime.datetime.now()
    year = now.strftime('%Y')
    
    bolle_esistenti = preventivo_data.get("bolle", [])
    if not bolle_esistenti:
        return f"BOLLA-{year}-1"

    max_num = 0
    for bolla in bolle_esistenti:
        try:
            # Estrae il numero progressivo dall'ID della bolla (es. da "BOLLA-2025-3" prende 3)
            num = int(bolla.get("id", "").split('-')[2])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            continue
    
    return f"BOLLA-{year}-{max_num + 1}"


@app.route("/consegna/<quote_id>/crea-bolla", methods=["POST"])
@login_or_local_required
def crea_bolla(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        return jsonify({"success": False, "error": "Non disponi delle autorizzazioni per eseguire questa azione."})
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici_righe_bolla = [int(i) for i in request.form.getlist("selected_items[]")]
    indirizzo_cantiere_id = request.form.get("indirizzo_cantiere_id")

    if not indici_righe_bolla:
        return jsonify({"success": False, "error": "Nessun articolo selezionato per la bolla"})

    bolla_id = get_new_bolla_id(p)
    
    if "bolle" not in p: p["bolle"] = []
    
    nuova_bolla = {
        "id": bolla_id,
        "data": datetime.date.today().strftime('%Y-%m-%d'),
        "indici_righe": indici_righe_bolla
    }
    
    if indirizzo_cantiere_id:
        nuova_bolla["indirizzo_cantiere_id"] = indirizzo_cantiere_id

    p["bolle"].append(nuova_bolla)

    # --- AGGIORNAMENTO STATO IMMEDIATO ---
    # Impostiamo "In Bolla" GIÀ QUI, così anche se il PDF fallisce
    # le righe risultano correttamente associate alla bolla.
    # Il PDF può essere rigenerato in seguito senza creare bolle duplicate.
    is_edile = p.get("tipo_preventivo") == "edile"
    if is_edile:
        for idx_assoluto in indici_righe_bolla:
            curr_idx = 0
            for sezione in p.get("sezioni_edili", []):
                for riga in sezione.get("righe", []):
                    if curr_idx == idx_assoluto:
                        riga["stato_consegna"] = "In Bolla"
                        riga["bolla_id"] = bolla_id
                    curr_idx += 1
    else:
        target_list = "righe"
        for index in indici_righe_bolla:
            if 0 <= index < len(p[target_list]):
                p[target_list][index]["stato_consegna"] = "In Bolla"
                p[target_list][index]["bolla_id"] = bolla_id

    aggiorna_stato_consegna_globale(p)
    aggiorna_stato_avanzamento(p)
    save_quote(quote_id, p)

    return jsonify({
        "success": True, 
        "next_url": url_for('export_bolla_pdf', quote_id=quote_id, bolla_id=bolla_id)
    })

@app.route("/pagamenti")
@login_required
def dashboard_pagamenti():
    """Pagina che elenca i preventivi confermati con il loro stato di pagamento."""
    preventivi_da_saldare = []
    tutti_i_preventivi = get_all_quotes()
    today = datetime.date.today()

    def _str_to_float(s):
        try: return round(float(str(s).replace("€", "").replace(".", "").replace(",", ".").strip()), 2)
        except: return 0.0

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        
        if not p or p.get("stato") not in ["Confermato", "In Lavorazione", "Chiuso"]:
            continue

        pagamenti = p.get("pagamenti", [])
        totale_preventivo = round(_str_to_float(p.get("totale", "0")), 2)
        
        totale_pagato_effettivo = 0.0
        totale_da_incassare = 0.0
        
        # 1. Calcolo Pagamenti Fisici (rispettando il flag programmato)
        for pag in pagamenti:
            importo_float = _str_to_float(pag.get("importo"))
            
            if pag.get("is_scheduled") and importo_float > 0:
                totale_da_incassare += importo_float
            else:
                totale_pagato_effettivo += importo_float
        
        # 2. GESTIONE ESENZIONE IVA
        if p.get("no_iva"):
            valore_iva = _str_to_float(p.get("tot_iva", "0"))
            totale_pagato_effettivo += valore_iva

        # Arrotondamenti finali
        totale_pagato_effettivo = round(totale_pagato_effettivo, 2)
        totale_da_incassare = round(totale_da_incassare, 2)
        
        p["totale_pagato"] = totale_pagato_effettivo
        p["totale_da_incassare"] = totale_da_incassare 
        p["totale_da_saldare"] = round(totale_preventivo - totale_pagato_effettivo, 2)
        
        p["stato_pagamento"] = "Saldato" if p["totale_da_saldare"] <= 0.01 else "Da Saldare"

        if p["stato_pagamento"] == "Saldato":
            continue

        # Dettagli per la dashboard
        p["totale_num"] = totale_preventivo
        p["pct_pagato"] = max(0, min(100, round(totale_pagato_effettivo / totale_preventivo * 100))) if totale_preventivo > 0 else 0
        p["pct_programmato"] = max(0, min(100 - p["pct_pagato"], round(totale_da_incassare / totale_preventivo * 100))) if totale_preventivo > 0 else 0
        p["num_pagamenti"] = len([x for x in pagamenti if not x.get("is_scheduled")])
        programmati = sorted(x.get("data", "") for x in pagamenti if x.get("is_scheduled") and x.get("data"))
        p["prossimo_incasso"] = programmati[0] if programmati else None

        # Calcolo allerta giorni (Invariato)
        p["ultimo_pagamento_data"] = None
        p["allerta_giorni"] = None
        if pagamenti:
            pagamenti.sort(key=lambda x: x.get("data", "1900-01-01"), reverse=True)
            p["ultimo_pagamento_data"] = pagamenti[0].get("data")
            if p["stato_pagamento"] == "Da Saldare":
                try:
                    last_payment_date = datetime.datetime.strptime(p["ultimo_pagamento_data"], '%Y-%m-%d').date()
                    days_diff = (today - last_payment_date).days
                    p["giorni_da_ultimo"] = days_diff
                    if days_diff > 22: p["allerta_giorni"] = "rosso"
                    elif days_diff >= 16: p["allerta_giorni"] = "arancio"
                    elif days_diff >= 15: p["allerta_giorni"] = "giallo"
                except: pass

        preventivi_da_saldare.append(p)

    return render_template("dashboard_pagamenti.html", 
        title="Saldo e Acconto Preventivi",
        preventivi=preventivi_da_saldare
    )
@app.route("/pagamenti/<quote_id>")
@login_required
def gestione_pagamenti(quote_id):
    """Pagina per visualizzare e aggiungere pagamenti per un singolo preventivo."""
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard_pagamenti"))

    # --- AGGIUNTA: Forza ricalcolo all'apertura per aggiornare i campi a 0 ---
    aggiorna_stato_pagamento_globale(p)
    # -----------------------------------------------------------------------

    pagamenti_raw = p.get("pagamenti", [])
    today = datetime.date.today()
    
    # --- MIGRAZIONE RETROCOMPATIBILITÀ (Invariata) ---
    made_changes_to_save = False
    for pag in pagamenti_raw:
        if "id" not in pag:
            pag["id"] = f"PAY-{uuid.uuid4().hex[:8].upper()}"
            made_changes_to_save = True
    if made_changes_to_save: save_quote(quote_id, p)
    # -----------------------------------------------

    def _str_to_float(s):
        try: return round(float(str(s).replace("€", "").replace(".", "").replace(",", ".").strip()), 2)
        except: return 0.0

    ids_rettificati = set(pag.get("rectifies_id") for pag in pagamenti_raw if pag.get("rectifies_id"))
    pagamenti_elaborati = []
    totale_da_incassare = 0.0
    totale_pagato_effettivo = 0.0

    # 1. Elabora pagamenti REALI
    for pag in pagamenti_raw:
        new_pag = pag.copy()
        importo_float = _str_to_float(new_pag.get("importo"))
        is_future = new_pag.get("is_scheduled", False)

        if is_future and importo_float > 0:
            totale_da_incassare += importo_float
        else:
            totale_pagato_effettivo += importo_float
        
        is_rettificabile = (importo_float > 0 and not is_future and new_pag.get("id") not in ids_rettificati)
        
        new_pag["is_future"] = is_future
        new_pag["is_rectifiable"] = is_rettificabile
        new_pag["type"] = "standard" # Tipologia standard
        pagamenti_elaborati.append(new_pag)

    # 2. GESTIONE RIGA VIRTUALE "NO IVA"
    if p.get("no_iva"):
        valore_iva = _str_to_float(p.get("tot_iva", "0"))
        
        if valore_iva > 0:
            # Creiamo un pagamento "fittizio" solo per la visualizzazione
            pagamento_virtuale = {
                "id": "VIRTUAL-NO-IVA",
                "data": p.get("data_conferma", today.strftime('%Y-%m-%d')), # Data preventivo o oggi
                "importo": p.get("tot_iva", "0,00"),
                "note": "Saldo automatico",
                "is_future": False,
                "type": "auto_iva" # Tipologia speciale per il template
            }
            # Aggiungiamo alla lista visuale
            pagamenti_elaborati.append(pagamento_virtuale)
            
            # Aggiorniamo i totali matematici
            totale_pagato_effettivo += valore_iva

    # Ordina per data
    pagamenti_elaborati.sort(key=lambda x: x.get("data", ""), reverse=True)

    # Totali Finali
    totale_da_incassare = round(totale_da_incassare, 2)
    totale_pagato_effettivo = round(totale_pagato_effettivo, 2)
    totale_preventivo = _str_to_float(p.get("totale", "0")) 
    totale_da_saldare = round(totale_preventivo - totale_pagato_effettivo, 2)
    
    p["totale_pagato"] = totale_pagato_effettivo
    p["totale_da_incassare"] = totale_da_incassare
    p["totale_da_saldare"] = totale_da_saldare
    p["pagamenti_elaborati"] = pagamenti_elaborati

    return render_template("gestione_pagamenti.html",
        title=f"Gestione Pagamenti {quote_id}",
        p=p
    )

@app.route("/pagamenti/<quote_id>/aggiungi", methods=["POST"])
@login_required
def aggiungi_pagamento(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non disponi delle autorizzazioni per gestire i pagamenti.", "error")
        return redirect(request.referrer or url_for('dashboard'))
    """Salva un nuovo pagamento per un preventivo."""
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard_pagamenti"))

    if "pagamenti" not in p:
        p["pagamenti"] = []

    # Recupera il nome dell'utente dalla sessione e la nota dal form
    user_name = session.get("user_name", "sconosciuto")
    nota_originale = request.form.get("note", "").strip()

    nota_finale = f"(Inserito da: {user_name})"
    if nota_originale:
        nota_finale = f"{nota_originale} {nota_finale}"
    
    # Crea la nota finale combinando la nota dell'utente e il suo nome
    nota_finale = f"(Inserito da: {user_name})"
    if nota_originale:
        nota_finale = f"{nota_originale} {nota_finale}"    

    nuovo_pagamento = {
        "id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
        "data": request.form.get("data", datetime.date.today().strftime('%Y-%m-%d')),
        "importo": request.form.get("importo"),
        "note": nota_finale,
        "is_scheduled": (request.form.get("data") > datetime.date.today().strftime('%Y-%m-%d'))
    }


    # Validazione semplice
    if not nuovo_pagamento["importo"] or float(nuovo_pagamento["importo"].replace(",", ".")) <= 0:
        flash("L'importo del pagamento non è valido.", "error")
        return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

    p["pagamenti"].append(nuovo_pagamento)
    aggiorna_stato_pagamento_globale(p)
    aggiorna_stato_avanzamento(p) 
    save_quote(quote_id, p)
    
    flash("Nuovo pagamento aggiunto con successo.", "success")
    return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

@app.route("/pagamenti/<quote_id>/rettifica", methods=["POST"])
@login_required
def rettifica_pagamento(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non disponi delle autorizzazioni per gestire i pagamenti.", "error")
        return redirect(request.referrer)

    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard_pagamenti"))

    payment_id_to_rectify = request.form.get("payment_id")
    original_payment = next((pag for pag in p.get("pagamenti", []) if pag.get("id") == payment_id_to_rectify), None)
    
    if original_payment is None:
        flash("Errore: Pagamento da rettificare non trovato.", "error")
        return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

    user_name = session.get("user_name", "sconosciuto")
    try:
        original_amount_float = float(str(original_payment["importo"]).replace(",", "."))
        rectified_amount_float = -original_amount_float
        rectified_amount_str = f"{rectified_amount_float:.2f}".replace(".", ",")
    except (ValueError, TypeError, KeyError):
        flash("Errore nel formato dell'importo originale.", "error")
        return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

    rectified_payment = {
        "id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
        "data": datetime.date.today().strftime('%Y-%m-%d'),
        "importo": rectified_amount_str,
        # Aggiorniamo la nota per includere l'ID, più chiaro
        "note": f"Rettifica pag. {original_payment.get('id')} (da {user_name})",
        # QUESTA E' LA RIGA CHIAVE:
        "rectifies_id": original_payment.get("id") 
    }

    if "pagamenti" not in p: p["pagamenti"] = []
    
    p["pagamenti"].append(rectified_payment)
    
    aggiorna_stato_pagamento_globale(p)
    aggiorna_stato_avanzamento(p) 
    save_quote(quote_id, p)
    
    flash("Pagamento rettificato con successo.", "success")
    return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

@app.route("/pagamenti/<quote_id>/conferma_incasso", methods=["POST"])
@login_required
def conferma_incasso(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non disponi delle autorizzazioni per gestire i pagamenti.", "error")
        return redirect(request.referrer)
    
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard_pagamenti"))

    payment_id_to_confirm = request.form.get("payment_id")
    payment_found = False

    for pag in p.get("pagamenti", []):
        if pag.get("id") == payment_id_to_confirm:
            pag["data"] = datetime.date.today().strftime('%Y-%m-%d')
            pag["is_scheduled"] = False
            payment_found = True
            break
    
    if payment_found:
        aggiorna_stato_pagamento_globale(p)
        aggiorna_stato_avanzamento(p)
        save_quote(quote_id, p)
        flash("Pagamento futuro confermato e incassato oggi.", "success")
    else:
        flash("Errore: Pagamento da confermare non trovato.", "error")

    return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

@app.route("/pagamenti/<quote_id>/modifica-data", methods=["POST"])
@login_required
def modifica_data_pagamento(quote_id):
    """Aggiorna la data di un pagamento programmato (futuro)."""
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non autorizzato.", "error")
        return redirect(request.referrer)

    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard_pagamenti"))

    payment_id = request.form.get("payment_id")
    nuova_data = request.form.get("nuova_data")

    if not nuova_data:
        flash("Inserire una data valida.", "error")
        return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

    payment_found = False
    for pag in p.get("pagamenti", []):
        if pag.get("id") == payment_id:
            pag["data"] = nuova_data
            payment_found = True
            break

    if payment_found:
        save_quote(quote_id, p)
        flash("Data del pagamento aggiornata con successo.", "success")
    else:
        flash("Errore: Pagamento non trovato.", "error")

    return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

@app.route("/pagamenti/<quote_id>/modifica-programmato", methods=["POST"])
@login_required
def modifica_pagamento_programmato(quote_id):
    """Modifica data e importo di un pagamento futuro tramite modale."""
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non autorizzato.", "error")
        return redirect(request.referrer)

    p = load_quote(quote_id)
    if not p: return redirect(url_for("dashboard"))

    payment_id = request.form.get("payment_id")
    nuova_data = request.form.get("nuova_data")
    nuovo_importo = request.form.get("nuovo_importo")

    payment_found = False
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    for pag in p.get("pagamenti", []):
        if pag.get("id") == payment_id:
            pag["data"] = nuova_data
            pag["importo"] = nuovo_importo
            pag["is_scheduled"] = (nuova_data > today_str)
            payment_found = True
            break
    
    if payment_found:
        # Ricalcola i totali globali perché l'importo potrebbe essere cambiato
        aggiorna_stato_pagamento_globale(p)
        aggiorna_stato_avanzamento(p)
        save_quote(quote_id, p)
        flash("Pagamento aggiornato con successo.", "success")
    else:
        flash("Errore: Pagamento non trovato.", "error")

    return redirect(url_for("gestione_pagamenti", quote_id=quote_id))

@app.route("/export-bolla-pdf/<quote_id>/<bolla_id>")
@login_or_local_required
def export_bolla_pdf(quote_id, bolla_id):
    """Apre il PDF della bolla se è già stato generato; altrimenti mostra la pagina di generazione.
    (La rigenerazione forzata resta disponibile da /rigenera-bolla-pdf.)"""
    p = load_quote(quote_id)
    bolla = next((b for b in (p or {}).get("bolle", []) if b.get("id") == bolla_id), None)
    if bolla and not bolla.get("pdf_fallito"):
        # Le bolle più vecchie non hanno 'pdf_filename': si prova anche il nome standard del file
        nome_standard = f"{bolla_id.replace('-', '_')}_{p['numero'].replace('-', '_')}.pdf"
        for pdf_name in (bolla.get("pdf_filename"), nome_standard):
            if pdf_name and (QUOTES_DIR / pdf_name).is_file() and (QUOTES_DIR / pdf_name).stat().st_size > 1000:
                return redirect(url_for("pdf_inline", filename=pdf_name))
    return render_template("loading_bolla.html", quote_id=quote_id, bolla_id=bolla_id)

@app.route("/generate-bolla-task/<quote_id>/<bolla_id>")
@login_or_local_required
def generate_bolla_task(quote_id, bolla_id):
    """Genera il PDF della bolla con gestione robusta di timeout e retry."""
    import subprocess, shutil
    log_id = f"{quote_id}/{bolla_id}"
    log_pdf_event(log_id, "INFO", "Inizio generazione PDF bolla.")

    p = load_quote(quote_id)
    if not p:
        log_pdf_event(log_id, "ERRORE", "Preventivo non trovato.")
        return jsonify({"error": "Preventivo non trovato"}), 404

    bolla = next((b for b in p.get("bolle", []) if b.get("id") == bolla_id), None)
    if not bolla:
        log_pdf_event(log_id, "ERRORE", "Bolla non trovata.")
        return jsonify({"error": "Bolla non trovata"}), 404

    # Determina sorgente righe e template in base al tipo
    is_edile = p.get("tipo_preventivo") == "edile"
    template_name = "stampa_consegna_lavori.html" if is_edile else "stampa_bolla.html"
    righe_sorgente = get_flat_righe_edili(p) if is_edile else p.get("righe", [])
    
    righe_bolla = [righe_sorgente[i] for i in bolla.get("indici_righe", []) if 0 <= i < len(righe_sorgente)]
    
    indirizzo_consegna = None
    indirizzo_id = bolla.get("indirizzo_cantiere_id")
    if indirizzo_id:
        client = load_client(p.get("id_cliente"))
        if client:
            indirizzo_consegna = next((addr for addr in client.get("indirizzi_cantiere", []) if addr.get("id") == indirizzo_id), None)

    quote_num_safe = p['numero'].replace('-', '_')
    bolla_id_safe = bolla_id.replace('-', '_')
    pdf_name = f"{bolla_id_safe}_{quote_num_safe}.pdf"
    out_path = (QUOTES_DIR / pdf_name).resolve()

    url = _local_print_url("stampa_bolla_html", quote_id=quote_id, bolla_id=bolla_id)

    # --- 1. Browser headless (Chrome, poi Edge), con profilo dedicato e più tentativi ---
    ok = print_url_to_pdf(log_id, url, out_path)

    # --- 2. Fallback WeasyPrint (solo se installato) ---
    if not ok:
        log_pdf_event(log_id, "INFO", "Browser non riuscito. Tentativo con WeasyPrint.")
        html_string = render_template(template_name, p=p, bolla=bolla, righe_bolla=righe_bolla, indirizzo_consegna=indirizzo_consegna)
        ok = _weasyprint_to_pdf(log_id, html_string, out_path)

    # --- 3. ESITO FINALE ---
    if not ok:
        log_pdf_event(log_id, "FALLIMENTO", "Tutti i metodi di generazione PDF hanno fallito.")
        # Salva flag nel JSON per segnalare che il PDF non è stato generato
        bolla["pdf_fallito"] = True
        save_quote(quote_id, p)
        annuncia(f"❌ PDF NON generato: bolla {bolla_id} del preventivo {quote_id} ({_chi()}).", "pdf_errore")
        return jsonify({"error": "Impossibile generare il PDF della bolla. Potrai rigenerarlo dalla pagina consegna."}), 500

    # PDF generato con successo: rimuovi eventuali flag di fallimento precedente
    bolla.pop("pdf_fallito", None)
    bolla["pdf_filename"] = pdf_name
    save_quote(quote_id, p)

    log_pdf_event(log_id, "COMPLETATO", f"Processo terminato. File: {pdf_name}")
    annuncia(f"✅ PDF generato: bolla {bolla_id} del preventivo {quote_id} ({_chi()})", "pdf", url_for("pdf_inline", filename=pdf_name))
    pdf_url = url_for("pdf_inline", filename=pdf_name)
    return jsonify({"pdf_url": pdf_url})

@app.route("/rigenera-bolla-pdf/<quote_id>/<bolla_id>")
@login_or_local_required
def rigenera_bolla_pdf(quote_id, bolla_id):
    """Rigenera il PDF di una bolla esistente senza creare una bolla duplicata."""
    return render_template("loading_bolla.html", quote_id=quote_id, bolla_id=bolla_id)

@app.route("/fatture")
@login_required
def dashboard_fatture():
    """Pagina che elenca i preventivi confermati pronti per la fatturazione."""
    tutti_i_preventivi = get_all_quotes()
    preventivi_confermati = []
    stati_validi = ["Confermato", "In Lavorazione", "Chiuso"]

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p or p.get("stato") not in stati_validi:
            continue
        
        # Salta i preventivi che sono già stati fatturati completamente
        if p.get("stato_fattura") == "Fatturato":
            continue

        # Dettagli per la dashboard
        p["totale_num"] = _to_float(p.get("totale"))
        p["imponibile_num"] = _to_float(p.get("tot_imponibile_cliente"))
        p["iva_num"] = _to_float(p.get("tot_iva"))
        stati_iva = p.get("stati_fattura_iva") or {}
        imponibili_iva = p.get("imponibili_iva") or {}
        p["aliquote"] = [
            {"aliquota": k, "imponibile": _to_float(v), "fatturato": bool(stati_iva.get(k))}
            for k, v in sorted(imponibili_iva.items(), key=lambda kv: _to_float(kv[0]))
        ] if isinstance(imponibili_iva, dict) else []
        fatture_iva = p.get("fatture_per_iva") or {}
        p["num_fatture"] = len(p.get("fatture_allegate") or []) + (
            sum(len(v) for v in fatture_iva.values()) if isinstance(fatture_iva, dict) else 0)
        p["pronto_fattura"] = p.get("stato_consegna_globale") == "Completato"
        rif = _str_to_date(p.get("data_conferma")) or _str_to_date(p.get("data"))
        p["giorni_da_conferma"] = (datetime.date.today() - rif).days if rif else None
        preventivi_confermati.append(p)

    return render_template("dashboard_fatture.html", 
        title="Dashboard Fatture",
        preventivi=preventivi_confermati
    )

@app.route("/fattura/<quote_id>")
@login_required
def editor_fattura(quote_id):
    """Pagina di visualizzazione snellita di un preventivo per la fatturazione."""
    p = load_quote(quote_id)
    # ... (migrazione esistente) ...

    # --- INIZIO LOGICA EDILI / STANDARD ---
    is_edile = p.get("tipo_preventivo") == "edile"
    righe_sorgente = get_flat_righe_edili(p) if is_edile else p.get("righe", [])
    
    dati_fattura = {}
    
    def _clean_num(val_str):
        try:
            return float(str(val_str).replace("€", "").replace(".", "").replace(",", ".").strip())
        except (ValueError, TypeError):
            return 0.0

    # 1. Raggruppa le righe per aliquota IVA
    for riga in righe_sorgente:
        if not riga.get("articolo"): continue
        
        iva_key = str(riga.get("iva_pct", "22 %")).replace("%", "").strip()
        
        if iva_key not in dati_fattura:
            dati_fattura[iva_key] = {
                "righe": [],
                "imponibile_val": 0.0,
                "iva_val": 0.0,
                "fatture_allegate": p.get("fatture_per_iva", {}).get(iva_key, []),
                "is_fatturato": p.get("stati_fattura_iva", {}).get(iva_key, False)
            }
        
        # Mapping campi per compatibilità template HTML
        r_view = riga.copy()
        if is_edile:
            val_prezzo = _clean_num(riga.get("prezzo_vendita"))
            r_view["tot_prezzo_unitario"] = riga.get("prezzo_vendita")
            r_view["tot_prezzo"] = riga.get("prezzo_vendita")
            r_view["qt"] = "1"
            r_view["unt"] = "Lav."
            dati_fattura[iva_key]["imponibile_val"] += val_prezzo
            dati_fattura[iva_key]["iva_val"] += val_prezzo * (_clean_num(iva_key) / 100)
        else:
            dati_fattura[iva_key]["imponibile_val"] += _clean_num(riga.get("tot_prezzo"))
            dati_fattura[iva_key]["iva_val"] += _clean_num(riga.get("tot_iva_riga"))

        dati_fattura[iva_key]["righe"].append(r_view)

    # 2. Finalizzazione stringhe per il template
    for key, data in dati_fattura.items():
        data["imponibile_str"] = f"{data['imponibile_val']:.2f}".replace(".", ",")
        data["iva_str"] = f"{data['iva_val']:.2f}".replace(".", ",")
        data["totale"] = data["imponibile_val"] + data["iva_val"]
    # --- FINE LOGICA EDILI ---

    dati_fattura_ordinati = dict(sorted(dati_fattura.items(), key=lambda item: item[0], reverse=True))

    return render_template("editor_fattura.html", 
        title=f"Dettaglio Fattura da Preventivo {quote_id}",
        p=p,
        dati_fattura=dati_fattura_ordinati
    )

@app.route("/fattura/<quote_id>/allega", methods=["POST"])
@login_required
def allega_fattura(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non disponi delle autorizzazioni per gestire i pagamenti.", "error")
        return redirect(request.referrer or url_for('dashboard'))
    
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("editor_fattura", quote_id=quote_id))

    file = request.files.get('file')
    iva_rate_key = request.form.get("iva_rate_key") # <-- NUOVO CAMPO DAL FORM

    if not all([file, file.filename, iva_rate_key]):
        flash("Dati mancanti: file o aliquota IVA non specificati.", "error")
        return redirect(url_for("editor_fattura", quote_id=quote_id))

    # Logica di salvataggio del file (invariata)
    quote_allegati_dir = ALLEGATI_DIR / quote_id
    quote_allegati_dir.mkdir(exist_ok=True)
    filename = secure_filename(file.filename)
    file.save(quote_allegati_dir / filename)

    # --- NUOVA LOGICA DI SALVATAGGIO PER IVA ---
    if "fatture_per_iva" not in p:
        p["fatture_per_iva"] = {}
    if iva_rate_key not in p["fatture_per_iva"]:
        p["fatture_per_iva"][iva_rate_key] = []

    p["fatture_per_iva"][iva_rate_key].append({
        "filename": filename,
        "descrizione": request.form.get("descrizione", f"Fattura IVA {iva_rate_key}%"),
        "data_upload": datetime.date.today().strftime('%Y-%m-%d')
    })
    
    # --- VECCHIO MODELLO DATI (per retrocompatibilità, opzionale ma consigliato) ---
    # Manteniamo la vecchia lista per non rompere la visualizzazione in 'dettaglio_cliente'
    if "fatture_allegate" not in p:
        p["fatture_allegate"] = []
    p["fatture_allegate"].append({
        "filename": filename,
        "descrizione": request.form.get("descrizione", f"Fattura IVA {iva_rate_key}%"),
        "data_upload": datetime.date.today().strftime('%Y-%m-%d')
    })
    # --- FINE BLOCCO RETROCOMPATIBILITÀ ---

    aggiorna_stato_avanzamento(p) # Richiama l'aggiornamento stato globale
    save_quote(quote_id, p)
    
    flash(f"Fattura per IVA {iva_rate_key}% allegata con successo!", "success")
    return redirect(url_for("editor_fattura", quote_id=quote_id))
def get_flat_righe_edili(p):
    """
    Versione con retrocompatibilità: gestisce sia la nuova struttura a sezioni 
    che la vecchia lista piatta 'righe_edili'.
    """
    flat_list = []
    if p.get("tipo_preventivo") != "edile":
        return p.get("righe", [])
    
    indice_assoluto = 0
    
    # --- 1. TENTATIVO NUOVA STRUTTURA (Sezioni) ---
    if "sezioni_edili" in p and p["sezioni_edili"]:
        for sezione in p["sezioni_edili"]:
            for riga in sezione.get("righe", []):
                r_copy = riga.copy()
                r_copy["original_index"] = indice_assoluto
                # Campi virtuali per compatibilità
                r_copy["qt"] = "1"
                r_copy["unt"] = "Lav."
                r_copy["tot_prezzo"] = riga.get("prezzo_vendita", "0")
                
                # Calcolo IVA per fatturazione
                prezzo = _to_num(riga.get("prezzo_vendita", 0))
                iva_pct = _to_num(riga.get("iva_pct", 10))
                r_copy["tot_iva_riga"] = f"{(prezzo * iva_pct / 100):.2f}".replace(".", ",")
                
                flat_list.append(r_copy)
                indice_assoluto += 1
                
    # --- 2. TENTATIVO VECCHIA STRUTTURA (Fallback retrocompatibilità) ---
    elif "righe_edili" in p and p["righe_edili"]:
        for riga in p["righe_edili"]:
            r_copy = riga.copy()
            r_copy["original_index"] = indice_assoluto
            r_copy["qt"] = "1"
            r_copy["unt"] = "Lav."
            r_copy["tot_prezzo"] = riga.get("prezzo_vendita", "0")
            
            prezzo = _to_num(riga.get("prezzo_vendita", 0))
            iva_pct = _to_num(riga.get("iva_pct", 10))
            r_copy["tot_iva_riga"] = f"{(prezzo * iva_pct / 100):.2f}".replace(".", ",")
            
            flat_list.append(r_copy)
            indice_assoluto += 1
            
    return flat_list
def migra_vecchie_fatture_a_iva(p):
    """
    Funzione di migrazione una tantum. 
    Sposta le fatture da p['fatture_allegate'] a p['fatture_per_iva'].
    Attribuisce tutte le vecchie fatture all'aliquota IVA più alta (di solito 22%).
    """
    if p.get("fatture_per_iva") or not p.get("fatture_allegate"):
        return False # Migrazione già fatta o non necessaria

    print(f"MIGRAZIONE: Trovate fatture legacy per {p['numero']}.")
    p["fatture_per_iva"] = {}

    # Trova l'aliquota IVA più alta (presumibilmente il "totale" fatturato)
    # Se non ci sono imponibili, usa "22" come default
    aliquota_principale = "22" 
    if p.get("imponibili_iva"):
        aliquote = [int(k) for k in p.get("imponibili_iva", {}).keys() if _to_num(k) > 0]
        if aliquote:
            aliquota_principale = str(max(aliquote))

    # Assegna tutte le vecchie fatture a quell'aliquota
    p["fatture_per_iva"][aliquota_principale] = p["fatture_allegate"]

    # Aggiorna lo stato globale
    p["stato_fattura"] = "Fatturato"

    return True # Ritorna True se abbiamo modificato 'p'
@app.route("/fattura/<quote_id>/toggle-stato", methods=["POST"])
@login_required
def toggle_stato_fattura_iva(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        flash("Non autorizzato.", "error")
        return redirect(request.referrer)

    p = load_quote(quote_id)
    if not p: return redirect(url_for("dashboard"))

    iva_key = request.form.get("iva_key")
    # "1" per Fatturato, "0" per Da Fatturare
    nuovo_stato = request.form.get("set_stato") == "1"

    if "stati_fattura_iva" not in p:
        p["stati_fattura_iva"] = {}

    # Imposta lo stato per quella specifica aliquota
    p["stati_fattura_iva"][iva_key] = nuovo_stato

    # --- Ricalcolo Stato Globale Preventivo ---
    # Controlliamo se TUTTE le aliquote presenti (con importi > 0) sono segnate come fatturate
    def _to_num_local(x):
        try: return float(str(x).replace("€", "").replace(".", "").replace(",", ".").strip())
        except: return 0.0

    aliquote_presenti = [k for k in p.get("imponibili_iva", {}).keys() if _to_num_local(p["imponibili_iva"][k]) > 0]
    
    tutto_fatturato = True
    almeno_uno_fatturato = False

    for k in aliquote_presenti:
        if p["stati_fattura_iva"].get(k, False):
            almeno_uno_fatturato = True
        else:
            tutto_fatturato = False
    
    if tutto_fatturato and aliquote_presenti:
        p["stato_fattura"] = "Fatturato"
    elif almeno_uno_fatturato:
        p["stato_fattura"] = "Fatturato Parziale"
    else:
        p["stato_fattura"] = "In Attesa"

    aggiorna_stato_avanzamento(p)
    save_quote(quote_id, p)
    
    flash(f"Stato fatturazione aggiornato.", "success")
    return redirect(url_for("editor_fattura", quote_id=quote_id))


@app.route("/stampa-bolla-html/<quote_id>/<bolla_id>")
@login_or_local_required
def stampa_bolla_html(quote_id, bolla_id):
    """Renderizza il template HTML per la stampa della bolla o consegna lavori."""
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    
    bolla = next((b for b in p.get("bolle", []) if b.get("id") == bolla_id), None)
    if not bolla: return "Bolla non trovata", 404

    # Determina sorgente righe e template in base al tipo
    is_edile = p.get("tipo_preventivo") == "edile"
    template_name = "stampa_consegna_lavori.html" if is_edile else "stampa_bolla.html"
    righe_sorgente = get_flat_righe_edili(p) if is_edile else p.get("righe", [])

    righe_bolla = [righe_sorgente[i] for i in bolla.get("indici_righe", []) if 0 <= i < len(righe_sorgente)]

    indirizzo_consegna = None
    indirizzo_id = bolla.get("indirizzo_cantiere_id")
    if indirizzo_id:
        client = load_client(p.get("id_cliente"))
        if client:
            indirizzo_consegna = next((addr for addr in client.get("indirizzi_cantiere", []) if addr.get("id") == indirizzo_id), None)

    return render_template(template_name, p=p, bolla=bolla, righe_bolla=righe_bolla, indirizzo_consegna=indirizzo_consegna)
@app.route("/stampa-html/<quote_id>")
@login_or_local_required
def stampa_html(quote_id):
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    
    if p.get("tipo_preventivo") == "edile":
        return render_template("stampa_edile.html", p=p)
        
    return render_template("stampa.html", p=p)

@app.route("/stampa-semplice-html/<quote_id>")
@login_or_local_required
def stampa_semplice_html(quote_id):
    """Renderizza il template HTML per la stampa SEMPLICE (senza totali di riga)."""
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    # Fai attenzione al nome del nuovo template che creeremo tra poco:
    return render_template("stampa_semplice.html", p=p)
@app.route("/export-pdf/<quote_id>")
@login_or_local_required
def export_pdf(quote_id):
    """Pagina di attesa per la generazione del PDF del preventivo."""
    template_choice = request.args.get('template', 'standard')
    p = load_quote(quote_id)
    is_edile = p.get("tipo_preventivo") == "edile" if p else False
    back_url = url_for("editor_preventivo_edile" if is_edile else "editor_preventivo", quote_id=quote_id)
    return render_template("loading.html", quote_id=quote_id, template_choice=template_choice, back_url=back_url)

def get_new_revisione_id(preventivo_data):
    """Calcola il prossimo numero di revisione per un preventivo."""
    if "storico_pdf" not in preventivo_data or not preventivo_data["storico_pdf"]:
        return 1
    return len(preventivo_data["storico_pdf"]) + 1

_PDF_LOCKS = {}
_PDF_LOCKS_GUARD = threading.Lock()

def _get_pdf_lock(key):
    """Un lock per preventivo: evita due generazioni contemporanee (doppio click, due utenti)."""
    with _PDF_LOCKS_GUARD:
        if key not in _PDF_LOCKS:
            _PDF_LOCKS[key] = threading.Lock()
        return _PDF_LOCKS[key]

def get_browser_executables():
    """Tutti i browser Chromium disponibili (Chrome, Edge...), senza duplicati, nell'ordine di preferenza."""
    found = []
    first = get_browser_executable()
    candidates = [first] if first else []
    for name in ["chrome", "msedge", "google-chrome", "chromium", "brave"]:
        candidates.append(shutil.which(name))
    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    seen = set()
    for c in candidates:
        if c and os.path.isfile(c):
            key = os.path.normcase(os.path.abspath(c))
            if key not in seen:
                seen.add(key)
                found.append(c)
    return found

def _local_print_url(endpoint, **values):
    """URL della pagina di stampa raggiungibile dal browser headless sulla stessa macchina del server.
    Si usa 127.0.0.1 invece dell'IP di rete: non dipende da firewall, proxy o cambi di IP della LAN."""
    port = request.environ.get("SERVER_PORT") or PORT
    return f"http://127.0.0.1:{port}{url_for(endpoint, **values)}"

def print_url_to_pdf(log_id, url, out_path, attempts_per_browser=2):
    """Stampa una pagina in PDF con Chrome/Edge headless.

    Scrive prima su un file temporaneo e lo rinomina solo se valido, così non restano mai PDF a metà.
    Ogni tentativo usa un profilo browser temporaneo dedicato: senza, se Chrome è già aperto sul PC,
    il comando si 'aggancia' alla finestra esistente e termina subito senza creare il file
    (era la causa principale degli errori 'file assente' nel log)."""
    import tempfile
    out_path = Path(out_path)
    tmp_path = out_path.with_name(out_path.stem + f".tmp-{uuid.uuid4().hex[:6]}.pdf")
    browsers = get_browser_executables()
    if not browsers:
        log_pdf_event(log_id, "ERRORE", "Nessun browser Chrome/Edge trovato sul PC.")
        return False

    for browser_exe in browsers:
        for attempt in range(1, attempts_per_browser + 1):
            profile_dir = tempfile.mkdtemp(prefix="gest_pdf_")
            timeout_secs = 60 if attempt == 1 else 45
            cmd = [browser_exe, "--headless=new", "--disable-gpu", "--no-sandbox",
                   "--disable-extensions", "--disable-dev-shm-usage",
                   "--no-first-run", "--no-default-browser-check", "--disable-sync",
                   "--disable-background-networking", "--disable-component-update",
                   "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
                   # Se il gestionale gira come amministratore (es. avviato dall'installer), Chrome/Edge
                   # si "de-elevano" rilanciandosi in un altro processo: quello avviato da qui esce
                   # subito con codice 0 senza creare il PDF. Questo flag lo impedisce.
                   "--do-not-de-elevate",
                   f"--user-data-dir={profile_dir}",
                   f"--print-to-pdf={tmp_path}", url]
            label = f"{os.path.basename(browser_exe)} tentativo {attempt}/{attempts_per_browser}"
            try:
                log_pdf_event(log_id, "DEBUG", f"{label} - avvio")
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                try:
                    _, stderr = proc.communicate(timeout=timeout_secs)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    log_pdf_event(log_id, "ERRORE", f"{label} - timeout dopo {timeout_secs}s.")
                    continue

                # Il file a volte compare con un leggero ritardo dopo la chiusura del processo
                # (più a lungo se il browser ha passato il lavoro a un altro processo: nessun output)
                attese = 10 if (stderr or b"").strip() else 40
                for _ in range(attese):
                    if tmp_path.exists() and tmp_path.stat().st_size > 1000:
                        break
                    time.sleep(0.3)

                if tmp_path.exists() and tmp_path.stat().st_size > 1000:
                    os.replace(tmp_path, out_path)
                    log_pdf_event(log_id, "SUCCESSO", f"PDF generato con {label}. Dimensione: {out_path.stat().st_size} bytes.")
                    return True

                size_info = tmp_path.stat().st_size if tmp_path.exists() else "file assente"
                err = (stderr or b"").decode("utf-8", errors="ignore").strip().replace("\n", " | ")[:400]
                log_pdf_event(log_id, "ERRORE", f"{label} - nessun PDF valido ({size_info}), codice uscita {proc.returncode}. {err}")
            except Exception as e:
                log_pdf_event(log_id, "ERRORE", f"{label} - errore imprevisto: {e}")
            finally:
                shutil.rmtree(profile_dir, ignore_errors=True)
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
            time.sleep(1)
    return False

def _weasyprint_to_pdf(log_id, html_string, out_path):
    """Fallback WeasyPrint, solo se la libreria è installata (nell'eseguibile di solito non lo è)."""
    import importlib.util
    if importlib.util.find_spec("weasyprint") is None:
        log_pdf_event(log_id, "INFO", "WeasyPrint non installato: fallback non disponibile.")
        return False
    try:
        from weasyprint import HTML
        HTML(string=html_string, base_url=request.url_root).write_pdf(out_path)
        ok = Path(out_path).exists() and Path(out_path).stat().st_size > 1000
        log_pdf_event(log_id, "SUCCESSO" if ok else "ERRORE",
                      f"PDF generato con WeasyPrint. Dimensione: {Path(out_path).stat().st_size} bytes." if ok else "WeasyPrint ha prodotto un file troppo piccolo.")
        return ok
    except Exception as e:
        log_pdf_event(log_id, "ERRORE", f"Errore WeasyPrint: {e}")
        return False

@app.route("/generate-pdf-task/<quote_id>")
@login_or_local_required
def generate_pdf_task(quote_id):
    """Genera il PDF ufficiale del preventivo.

    Con ?invia=1 (usato dal pulsante "Inviato") il preventivo passa a Inviato SOLO se il PDF
    è stato creato: se la generazione fallisce resta in Bozza e si può riprovare, invece di
    rimanere bloccato in Inviato senza PDF."""
    lock = _get_pdf_lock(quote_id)
    if not lock.acquire(blocking=False):
        log_pdf_event(quote_id, "INFO", "Generazione già in corso: richiesta duplicata ignorata.")
        return jsonify({"error": "La generazione del PDF di questo preventivo è già in corso. Attendi qualche secondo."}), 409
    try:
        return _generate_pdf_task_locked(quote_id)
    finally:
        lock.release()

def _generate_pdf_task_locked(quote_id):
    log_pdf_event(quote_id, "INFO", "Inizio generazione PDF preventivo.")
    invia = request.args.get("invia") == "1"

    p = load_quote(quote_id)
    if not p:
        log_pdf_event(quote_id, "ERRORE", "Preventivo non trovato.")
        return jsonify({"error": "Preventivo non trovato"}), 404

    if p.get("stato") == "Bozza" and not invia:
        log_pdf_event(quote_id, "ERRORE", "Tentativo di generare PDF per preventivo in Bozza.")
        return jsonify({"error": "Non è possibile generare un PDF per un preventivo in stato di Bozza."}), 400
    if invia and p.get("stato") not in ("Bozza", "Inviato"):
        invia = False  # già confermato/in lavorazione: si genera solo la nuova revisione

    # Scelta del Template (supporto Standard, Semplice, Edile)
    template_choice = request.args.get('template', 'standard')
    is_edile = p.get("tipo_preventivo") == "edile"

    if is_edile:
        html_endpoint = 'stampa_html'
        html_template_file = 'stampa_edile.html'
        log_pdf_event(quote_id, "INFO", "Scelto template PDF: EDILE.")
    elif template_choice == 'semplice':
        html_endpoint = 'stampa_semplice_html'
        html_template_file = 'stampa_semplice.html'
        log_pdf_event(quote_id, "INFO", "Scelto template PDF: SEMPLICE (senza totali riga).")
    else:
        html_endpoint = 'stampa_html'
        html_template_file = 'stampa.html'
        log_pdf_event(quote_id, "INFO", "Scelto template PDF: STANDARD (con totali riga).")

    rev_num = get_new_revisione_id(p)
    pdf_name = f"Preventivo_{p.get('numero', 'file')}_REV{rev_num}.pdf"
    out_path = (QUOTES_DIR / pdf_name).resolve()
    log_pdf_event(quote_id, "INFO", f"Percorso output PDF: {out_path}")

    # Token firmato che autorizza il browser headless a leggere la pagina di stampa
    pdf_token = generate_pdf_token(quote_id)
    url = _local_print_url(html_endpoint, quote_id=quote_id, _pdf_token=pdf_token)

    ok = print_url_to_pdf(quote_id, url, out_path)
    if not ok:
        log_pdf_event(quote_id, "INFO", "Browser non riuscito. Tentativo con WeasyPrint.")
        ok = _weasyprint_to_pdf(quote_id, render_template(html_template_file, p=p), out_path)

    if not ok:
        log_pdf_event(quote_id, "FALLIMENTO", "Tutti i metodi di generazione PDF hanno fallito. Nessuna revisione salvata"
                      + (", il preventivo resta in Bozza." if invia and p.get("stato") == "Bozza" else "."))
        annuncia(f"❌ PDF NON generato: preventivo {quote_id} ({_chi()}). Dettagli nel log PDF.", "pdf_errore")
        return jsonify({"error": "Impossibile generare il PDF del preventivo. Riprova tra qualche secondo; "
                                 "se il problema persiste, chiudi e riapri Chrome sul PC del gestionale."}), 500

    # Il PDF esiste ed è valido: solo ora si salva la revisione (e l'eventuale passaggio a Inviato).
    # Si ricarica il preventivo per non sovrascrivere modifiche fatte nel frattempo.
    p = load_quote(quote_id) or p
    log_pdf_event(quote_id, "INFO", f"PDF valido. Aggiornamento preventivo con REV-{rev_num}.")
    if "storico_pdf" not in p: p["storico_pdf"] = []
    p["storico_pdf"].append({
        "id": f"REV-{rev_num}",
        "data": datetime.date.today().strftime('%Y-%m-%d'),
        "filename": pdf_name,
        "totale": p.get("totale", "0,00")
    })
    p["pdf_attivo"] = pdf_name
    if invia and p.get("stato") == "Bozza":
        p["stato"] = "Inviato"
        p["is_locked"] = True
        log_pdf_event(quote_id, "INFO", "Preventivo impostato come Inviato.")
    save_quote(quote_id, p)

    pdf_url = url_for("pdf_inline", filename=pdf_name)
    log_pdf_event(quote_id, "COMPLETATO", f"Processo terminato. URL PDF: {pdf_url}")
    annuncia(f"✅ PDF generato: preventivo {quote_id} REV-{rev_num} ({_chi()})"
             + (" - segnato come Inviato" if invia else ""), "pdf", url_for("pdf_inline", filename=pdf_name))
    return jsonify({"pdf_url": pdf_url})

@app.route("/loading-static")
def loading_static(): return render_template("loading_static.html")
@app.route("/pdf/<path:filename>")
@login_required
def pdf_inline(filename):
    """Serve un PDF dalla cartella preventivi. Richiede login."""
    pdf_directory = QUOTES_DIR.resolve()
    return send_from_directory(directory=pdf_directory, path=filename)

def get_lan_ip():
    """Trova l'IP locale del PC sulla LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def is_admin():
    """Controlla se lo script ha i privilegi di amministratore su Windows."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def manage_firewall_rule(port, rule_name="Gestionale Flask"):
    """Controlla e aggiunge una regola al firewall di Windows se eseguito come admin."""
    if sys.platform != 'win32' or not is_admin():
        if sys.platform == 'win32':
            print("INFO: Esegui come amministratore la prima volta per configurare il firewall automaticamente.")
        return
    try:
        check_cmd = f'netsh advfirewall firewall show rule name="{rule_name}"'
        result = subprocess.run(check_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if "Nessuna regola corrispondente ai criteri specificati" in result.stdout:
            print(f"INFO: Regola firewall '{rule_name}' non trovata. Tentativo di creazione...")
            add_cmd = (f'netsh advfirewall firewall add rule name="{rule_name}" '
                       f'dir=in action=allow protocol=TCP localport={port}')
            subprocess.run(add_cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"SUCCESS: Regola firewall per la porta {port} creata con successo.")
        else:
            print(f"INFO: Regola firewall '{rule_name}' già presente.")
    except Exception as e:
        print(f"ERRORE FIREWALL: Impossibile creare/verificare la regola. Errore: {e}")

# --- Costanti di Configurazione Dinamiche ---
HOST_BIND = "0.0.0.0"       # L'indirizzo a cui il server si lega (sempre questo per la LAN)
LAN_IP = get_lan_ip()       # L'indirizzo IP da mostrare agli utenti
PORT = 5001
DISPLAY_URL = f"http://{LAN_IP}:{PORT}/"
APP_TITLE = f"Gestionale Preventivi v{APP_VERSION}"
SERVER_ADDRESS_INFO = f"Server attivo su {DISPLAY_URL}"

def run_server():
    """Funzione che avvia il server web e controlla gli annunci."""
    # Esegui l'annuncio prima di far partire il server
    verifica_e_annuncia_aggiornamento()
    
    is_debug_mode = "--debug" in sys.argv
    if not is_debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=sincronizza_stati_tutti_preventivi, daemon=True).start()
    
    print(SERVER_ADDRESS_INFO)
    if is_debug_mode:
        app.run(host=HOST_BIND, port=PORT, debug=True)
    else:
        # Avvia Waitress con configurazione ottimizzata (12 thread)
        serve(
            app, 
            host=HOST_BIND, 
            port=PORT, 
            threads=12, 
            connection_limit=200, 
            channel_timeout=60
        )

def open_app(icon, menu_item):
    """Apre il gestionale nel browser."""
    webbrowser.open(DISPLAY_URL)

def quit_app(icon, menu_item):
    """Ferma l'icona e chiude l'applicazione."""
    icon.stop()
    os._exit(0)

def load_messages():
    """Carica tutti i messaggi dalla tabella SQLite."""
    db = _DBSession()
    try:
        return [m.to_dict() for m in db.query(_Message).order_by(_Message.timestamp).all()]
    except Exception:
        return []
    finally:
        db.close()

def save_messages(msgs):
    """Sostituisce tutti i messaggi nel DB (reset completo + reinserimento)."""
    db = _DBSession()
    try:
        db.query(_Message).delete()
        for m in msgs:
            db.add(_Message(
                from_user=m.get("from", ""),
                from_name=m.get("from_name", ""),
                to_user=m.get("to", ""),
                text=m.get("text", ""),
                attachment=m.get("attachment", ""),
                original_filename=m.get("original_filename", ""),
                timestamp=m.get("timestamp", ""),
                read=m.get("read", False)
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_messages] Errore: {e}")
    finally:
        db.close()

@app.route("/api/messages/users")
@login_required
def api_get_chat_users():
    """Elenco colleghi per la chat con non letti, ultimo messaggio (anteprima) e ordinamento per attività."""
    all_users = load_users()
    me = session["user_id"]
    db = _DBSession()
    try:
        mine = db.query(_Message).filter(
            (_Message.from_user == me) | (_Message.to_user == me)
        ).order_by(_Message.timestamp, _Message.id).all()
    finally:
        db.close()

    last_by_user, unread_by_user = {}, {}
    for m in mine:
        other = m.to_user if m.from_user == me else m.from_user
        last_by_user[other] = m  # ordinati per timestamp: resta l'ultimo
        if m.to_user == me and not m.read:
            unread_by_user[other] = unread_by_user.get(other, 0) + 1

    users_with_stats = []
    for u in all_users:
        if u["username"] == me or u["role"] == 'amministratore': continue
        last = last_by_user.get(u["username"])
        preview = ""
        if last:
            preview = (last.text or "").strip() or (f"📎 {last.original_filename}" if last.attachment else "")
        users_with_stats.append({
            "username": u["username"],
            "full_name": u["full_name"],
            "role": u["role"],
            "unread_count": unread_by_user.get(u["username"], 0),
            "last_message_timestamp": last.timestamp if last else "0000-00-00 00:00:00",
            "last_message_preview": preview[:80],
            "last_message_mine": bool(last and last.from_user == me),
        })

    # Prima chi ha messaggi non letti, poi per data ultimo messaggio (desc)
    users_with_stats.sort(key=lambda x: (x["unread_count"] > 0, x["last_message_timestamp"]), reverse=True)
    return jsonify(users_with_stats)

@app.route("/api/messages/history/<other_user>")
@login_required
def api_get_chat_history(other_user):
    me = session["user_id"]
    db = _DBSession()
    try:
        # Marca come letti i messaggi che l'altro utente mi ha inviato (UPDATE mirato, senza riscrivere la tabella)
        db.query(_Message).filter(
            _Message.to_user == me, _Message.from_user == other_user, _Message.read == False  # noqa: E712
        ).update({_Message.read: True}, synchronize_session=False)
        db.commit()
        history = db.query(_Message).filter(
            ((_Message.from_user == me) & (_Message.to_user == other_user)) |
            ((_Message.from_user == other_user) & (_Message.to_user == me))
        ).order_by(_Message.timestamp, _Message.id).all()
        return jsonify([dict(m.to_dict(), id=m.id) for m in history])
    except Exception as e:
        db.rollback()
        print(f"[chat] Errore history: {e}")
        return jsonify([])
    finally:
        db.close()

@app.route("/api/cliente/<client_id>/note", methods=["GET", "POST"])
@login_required
def api_note_cliente(client_id):
    """Legge (GET) o salva (POST {note: "..."}) le note interne di un cliente."""
    db = _DBSession()
    try:
        cli = db.query(_Cliente).filter_by(id_cliente=client_id).first()
        if not cli:
            return jsonify({"ok": False, "error": "Cliente non trovato"}), 404
        if request.method == "GET":
            return jsonify({"ok": True, "note": cli.note_interne or "",
                            "cliente": cli.cliente or cli.rag_sociale or client_id})
        data = request.get_json(silent=True) or {}
        cli.note_interne = str(data.get("note", ""))
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        print(f"[note_cliente] Errore: {e}")
        return jsonify({"ok": False, "error": "Errore nel salvataggio delle note"}), 500
    finally:
        db.close()

@app.route("/api/messages/send", methods=["POST"])
@login_required
def api_send_message():
    text = request.form.get("text", "").strip()
    to_user = request.form.get("to", "")
    file = request.files.get("file")

    if not to_user:
        return jsonify({"success": False, "error": "Destinatario mancante"}), 400
    if not text and not (file and file.filename):
        return jsonify({"success": False, "error": "Messaggio vuoto"}), 400

    filename = None
    if file and file.filename != '':
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        file.save(CHAT_ATTACHMENTS_DIR / filename)

    nuovo_msg = {
        "from": session["user_id"],
        "from_name": session["user_name"],
        "to": to_user,
        "text": text,
        "attachment": filename,
        "original_filename": file.filename if filename else None,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False
    }
    # Inserimento del solo nuovo messaggio (prima veniva riscritta l'intera tabella:
    # lento e con rischio di perdere messaggi inviati in contemporanea)
    db = _DBSession()
    try:
        row = _Message(from_user=nuovo_msg["from"], from_name=nuovo_msg["from_name"], to_user=to_user,
                       text=text, attachment=filename or "", original_filename=nuovo_msg["original_filename"] or "",
                       timestamp=nuovo_msg["timestamp"], read=False)
        db.add(row)
        db.commit()
        nuovo_msg["id"] = row.id
    except Exception as e:
        db.rollback()
        print(f"[chat] Errore invio: {e}")
        return jsonify({"success": False, "error": "Errore durante l'invio"}), 500
    finally:
        db.close()
    return jsonify({"success": True, "msg": nuovo_msg})

@app.route("/api/messages/unread_total")
@login_required
def api_unread_total():
    me = session["user_id"]
    db = _DBSession()
    try:
        count = db.query(_Message).filter(_Message.to_user == me, _Message.read == False).count()  # noqa: E712
    finally:
        db.close()
    return jsonify({"unread_count": count})

def load_tagbox():
    """Carica le voci della tagbox dal DB SQLite (pinned prima, poi per timestamp)."""
    db = _DBSession()
    try:
        entries = db.query(_TagboxEntry).order_by(
            _TagboxEntry.pinned.desc(), _TagboxEntry.timestamp.desc()
        ).all()
        return [e.to_dict() for e in entries]
    except Exception:
        return []
    finally:
        db.close()

def save_tagbox(shouts):
    """Salva la tagbox nel DB (upsert per id, elimina voci non presenti)."""
    db = _DBSession()
    try:
        incoming_ids = set()
        for s in shouts:
            sid = s.get("id")
            if not sid:
                continue
            incoming_ids.add(sid)
            existing = db.query(_TagboxEntry).filter_by(id=sid).first()
            if existing:
                existing.pinned = s.get("pinned", False)
                existing.text = s.get("text", "")
            else:
                db.add(_TagboxEntry(
                    id=sid,
                    user=s.get("user", ""),
                    user_id=s.get("user_id", ""),
                    text=s.get("text", ""),
                    timestamp=s.get("timestamp", ""),
                    pinned=s.get("pinned", False)
                ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_tagbox] Errore: {e}")
    finally:
        db.close()

@app.route("/api/tagbox", methods=["GET", "POST"])
@login_required
def api_tagbox():
    if request.method == "POST":
        data = request.json
        shouts = load_tagbox()
        nuovo_shout = {
            "id": uuid.uuid4().hex[:6],
            "user": session["user_name"],
            "user_id": session["user_id"],
            "text": data.get("text"),
            "timestamp": datetime.datetime.now().strftime("%H:%M"),
            "pinned": False
        }
        shouts.insert(0, nuovo_shout) # I più nuovi in alto
        save_tagbox(shouts[:50]) # Teniamo solo gli ultimi 50
        
        # Notifica tutti gli altri utenti dell'attività sulla Tagbox
        users = load_users()
        for u in users:
            if u["username"] != session["user_id"]:
                add_notification(u["username"], f"{session['user_name']} ha scritto sulla Tag Board", link="/")
                
        return jsonify({"success": True})
    
    return jsonify(load_tagbox())

@app.route("/api/tagbox/pin/<shout_id>", methods=["POST"])
@login_required
@role_required('amministratore', 'ceo', 'segreteria') # Solo ruoli gestionali possono pinnare
def api_pin_shout(shout_id):
    shouts = load_tagbox()
    for s in shouts:
        if s["id"] == shout_id:
            s["pinned"] = not s["pinned"] # Toggle pin
    save_tagbox(shouts)
    return jsonify({"success": True})

@app.route("/api/suggestions/links")
@login_required
def api_suggestions_links():
    term = request.args.get("q", "").lower().strip()
    quotes = get_all_quotes() # Recupera tutti i preventivi
    
    suggestions = []
    
    # 1. Ricerca Preventivi
    for q in quotes:
        # Se non c'è termine mostra i recenti, altrimenti cerca nel numero o nel cliente
        if not term or term in q["numero"].lower() or term in q["cliente"].lower():
            suggestions.append({"id": q["numero"], "label": f"Prev. {q['numero']} ({q['cliente']})", "type": "quote"})
        if len(suggestions) >= 5: break # Limite per i preventivi

    # 2. Ricerca Clienti (usando i dati dei preventivi per velocità)
    recent_clients_seen = set()
    count_clients = 0
    for q in quotes:
        client_name = q.get("cliente", "")
        # Filtriamo per termine se presente
        if (not term or term in client_name.lower()) and client_name not in recent_clients_seen:
            # Recuperiamo l'ID reale dal file del preventivo
            p_data = load_quote(q["numero"])
            if p_data:
                suggestions.append({
                    "id": p_data["id_cliente"], 
                    "label": f"Cartella: {client_name}", 
                    "type": "client"
                })
                recent_clients_seen.add(client_name)
                count_clients += 1
        if count_clients >= 5: break # Limite per i clienti

    return jsonify(suggestions)

def load_tasks():
    """Carica i tasks pubblici dalla tabella SQLite 'tasks'."""
    db = _DBSession()
    try:
        return [t.to_dict() for t in db.query(_Task).all()]
    except Exception:
        return []
    finally:
        db.close()

def save_tasks(tasks):
    """Salva la lista tasks nel DB (upsert per id)."""
    db = _DBSession()
    try:
        incoming_ids = set()
        for t in tasks:
            tid = t.get("id")
            if not tid:
                continue
            incoming_ids.add(tid)
            existing = db.query(_Task).filter_by(id=tid).first()
            if existing:
                existing.status = t.get("status", "open")
                existing.comments = t.get("comments", [])
                existing.assigned_to = t.get("assigned_to", [])
                if t.get("concluded_at"):
                    existing.timestamp = t.get("concluded_at", existing.timestamp)
            else:
                db.add(_Task(
                    id=tid,
                    created_by=t.get("created_by", ""),
                    created_by_name=t.get("created_by_name", ""),
                    description=t.get("description", ""),
                    assigned_to=t.get("assigned_to", []),
                    status=t.get("status", "open"),
                    is_private_admin=t.get("is_private_admin", False),
                    timestamp=t.get("timestamp", ""),
                    comments=t.get("comments", [])
                ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_tasks] Errore: {e}")
    finally:
        db.close()

@app.route("/tasks")
@login_required
def tasks_page():
    return render_template("tasks.html", title="Task & Report Team")


@app.route("/api/tasks", methods=["GET", "POST"])
@login_required
def api_tasks():
    if request.method == "POST":
        data = request.json
        desc = data.get("description", "").strip()
        if not desc:
            return jsonify({"error": "Descrizione mancante"}), 400

        task_id = str(uuid.uuid4())[:8].upper()
        mentions = re.findall(r"@(\w+)", desc)

        # Salva il nuovo task direttamente nel DB
        db = _DBSession()
        try:
            db.add(_Task(
                id=task_id,
                created_by=session["user_id"],
                created_by_name=session["user_name"],
                description=desc,
                assigned_to=[f"@{m}" for m in mentions] if mentions else ["@tutti"],
                status="open",
                timestamp=datetime.datetime.now().strftime("%d/%m %H:%M"),
                comments=[]
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[api_tasks] Errore salvataggio DB: {e}")
            return jsonify({"error": "Errore interno durante il salvataggio del task."}), 500
        finally:
            db.close()

        # --- GESTIONE NOTIFICHE E TAGBOX ---
        mittente = session["user_name"]
         # Logica standard per task pubbliche (Tagbox e notifiche a tutti)
        link_task = f"[VEDI TASK #TASK-{task_id}]"
        
        # Carichiamo gli utenti per risolvere i nomi reali (case-sensitive)
        all_users = load_users()
        user_resolver = {u['username'].lower(): u['username'] for u in all_users}
        unique_mentions = set(m.lower() for m in mentions)

        # 1. Post su Tagbox (per i Gruppi)
        for m_lower in unique_mentions:
            if m_lower in ['tutti', 'venditori', 'segreteria', 'produzione']:
                tagbox = load_tagbox()
                tagbox.insert(0, {
                    "id": uuid.uuid4().hex[:6],
                    "user": f"{mittente} [TASK]",
                    "user_id": session["user_id"],
                    "text": f"@{m_lower} Nuova task creata: {link_task}",
                    "timestamp": datetime.datetime.now().strftime("%H:%M"),
                    "pinned": False
                })
                save_tagbox(tagbox[:50])
                break

        # 2. Notifiche Campanella (Per tutti i menzionati)
        notified_ids = {session["user_id"]} # Non notificare se stessi
        for m_lower in unique_mentions:
            # Caso Gruppi
            if m_lower in ['tutti', 'venditori', 'segreteria', 'produzione']:
                for u in all_users:
                    u_real_id = u["username"]
                    if u_real_id not in notified_ids:
                        add_notification(u_real_id, f"{mittente} ha creato una task per @{m_lower}", link=f"/tasks#{task_id}")
                        notified_ids.add(u_real_id)
            
            # Caso Utente Singolo (Risoluzione case-insensitive dello username)
            elif m_lower in user_resolver:
                u_real_id = user_resolver[m_lower]
                if u_real_id not in notified_ids:
                    add_notification(u_real_id, f"{mittente} ti ha assegnato una nuova task", link=f"/tasks#{task_id}")
                    notified_ids.add(u_real_id)

        return jsonify({"success": True})
    
    # GET: Visualizzazione filtrata con unione file
    standard_tasks = load_tasks()
            
    me = session["user_id"]
    my_role = session["user_role"]
    
    # Task standard visibili secondo regole attuali
    visible_standard = [t for t in standard_tasks if 
        t.get("created_by") == me or 
        f"@{me}" in t.get("assigned_to", []) or 
        "@tutti" in t.get("assigned_to", []) or 
        f"@{my_role}" in t.get("assigned_to", []) or
        (my_role in ['amministratore', 'ceo'])
    ]
    
    
    return jsonify(visible_standard)


@app.route("/api/admin-support", methods=["POST"])
@login_required
def api_admin_support():
    """Salva una richiesta di assistenza direttamente nel file JSON admin."""
    data = request.json
    desc = data.get("description", "").strip()
    if not desc:
        return jsonify({"error": "Descrizione vuota"}), 400

    tasks = []
    if ADMIN_TASKS_FILE.exists():
        # Nota: eventuali task precedenti in admin_tasks.json sono stati migrati nel DB.
        # Il file JSON non viene più scritto; questa lettura serve solo come fallback legacy.
        pass

    new_support_request = {
        "id": f"SOS-{uuid.uuid4().hex[:6].upper()}",
        "user_id": session["user_id"],
        "user_name": session["user_name"],
        "description": desc,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "LOGGED_ONLY"
    }
    # Salva direttamente nel DB
    db = _DBSession()
    try:
        db.add(_AdminTask(
            id=new_support_request["id"],
            user_id=new_support_request["user_id"],
            user_name=new_support_request["user_name"],
            description=new_support_request["description"],
            timestamp=new_support_request["timestamp"],
            status=new_support_request["status"]
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[api_admin_support] Errore: {e}")
    finally:
        db.close()

    return jsonify({"success": True})


@app.route("/api/tasks/update", methods=["POST"])
@login_required
def api_update_task():
    data = request.json
    task_id, new_status, comment_text = data.get("id"), data.get("status"), data.get("comment", "").strip()
    status_change = data.get("status_change")
    
    # --- File: gestionale.py (Intorno alla riga 1554) ---
    tasks = load_tasks()
    notification_sent = False # <--- Flag per evitare notifiche doppie
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = new_status
            if new_status in ['resolved', 'failed'] and status_change:
                t["concluded_at"] = datetime.datetime.now().strftime("%Y-%m-%d")

            # --- NOTIFICHE SPECIFICHE CAMBIO STATO ---
            if status_change:
                all_users = load_users()
                user_resolver = {u['username'].lower(): u['username'] for u in all_users}
                mittente = session["user_name"]
                
                if status_change == 'support':
                    for u in all_users:
                        if u['role'] in ['amministratore', 'ceo'] or u['username'] == t.get('created_by'):
                            if u['username'] != session['user_id']:
                                add_notification(u['username'], f"⚠️ {mittente} richiede SUPPORTO per la task #{t['id']}", link=f"/tasks#{task_id}")
                                notification_sent = True

                if status_change in ['resolved', 'failed']:
                    notified_assigned = {session['user_id']}
                    assigned_list = t.get("assigned_to", [])
                    label = "COMPLETATA" if status_change == 'resolved' else "FALLITA"
                    emoji = "✅" if status_change == 'resolved' else "❌"
                    
                    for target in assigned_list:
                        m_lower = target.replace("@", "").lower()
                        if m_lower in ['tutti', 'venditori', 'segreteria', 'produzione']:
                            for u in all_users:
                                if (m_lower == 'tutti' or u['role'] == m_lower) and u['username'] not in notified_assigned:
                                    add_notification(u['username'], f"{emoji} Task {label}: #{task_id}", link=f"/tasks#{task_id}")
                                    notified_assigned.add(u['username'])
                                    notification_sent = True
                        elif m_lower in user_resolver:
                            u_real_id = user_resolver[m_lower]
                            if u_real_id not in notified_assigned:
                                add_notification(u_real_id, f"{emoji} Task {label}: #{task_id}", link=f"/tasks#{task_id}")
                                notified_assigned.add(u_real_id)
                                notification_sent = True
            
            if comment_text:
                if "comments" not in t: t["comments"] = []
                t["comments"].append({
                    "user": session["user_name"], "text": comment_text,
                    "timestamp": datetime.datetime.now().strftime("%d/%m %H:%M"),
                    "status_change": status_change
                })
                
                # Invia notifica commento solo se non è già stato notificato un cambio stato
                if not notification_sent:
                    all_users = load_users()
                    user_resolver = {u['username'].lower(): u['username'] for u in all_users}
                    notified = {session["user_id"]}
                    if t.get("created_by") and t["created_by"] not in notified:
                        add_notification(t["created_by"], f"{session['user_name']} ha commentato la task #{task_id}", link=f"/tasks#{task_id}")
                        notified.add(t["created_by"])
                    c_mentions = re.findall(r"@(\w+)", comment_text)
                    for cm_lower in set(m.lower() for m in c_mentions):
                        if cm_lower in user_resolver:
                            u_real_id = user_resolver[cm_lower]
                            if u_real_id not in notified:
                                add_notification(u_real_id, f"{session['user_name']} ti ha menzionato nella task #{task_id}", link=f"/tasks#{task_id}")
                                notified.add(u_real_id)
            break
    save_tasks(tasks)
    return jsonify({"success": True})

def load_notifications():
    """Carica le notifiche dal DB SQLite."""
    db = _DBSession()
    try:
        return [n.to_dict() for n in db.query(_Notification).order_by(_Notification.timestamp.desc()).all()]
    except Exception:
        return []
    finally:
        db.close()

def save_notifications(notifs):
    """Salva le notifiche nel DB (upsert per id)."""
    db = _DBSession()
    try:
        for n in notifs:
            nid = n.get("id")
            if not nid:
                continue
            existing = db.query(_Notification).filter_by(id=nid).first()
            if existing:
                existing.read = n.get("read", existing.read)
            else:
                db.add(_Notification(
                    id=nid,
                    target_user=n.get("user_id", n.get("target_user", "")),
                    text=n.get("text", ""),
                    link=n.get("link", ""),
                    timestamp=n.get("timestamp", ""),
                    read=n.get("read", False),
                    notif_type=n.get("type", "info")
                ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[save_notifications] Errore: {e}")
    finally:
        db.close()

def add_notification(user_id, text, link="/tasks"):
    """Aggiunge una notifica al DB per un utente specifico."""
    db = _DBSession()
    try:
        new_id = uuid.uuid4().hex[:6]
        db.add(_Notification(
            id=new_id,
            target_user=user_id,
            text=text,
            link=link,
            timestamp=datetime.datetime.now().strftime("%d/%m %H:%M"),
            read=False,
            notif_type="info"
        ))
        # Mantieni solo le ultime 100 notifiche per utente
        all_user_notifs = db.query(_Notification).filter_by(
            target_user=user_id
        ).order_by(_Notification.timestamp.desc()).all()
        if len(all_user_notifs) > 100:
            for old in all_user_notifs[100:]:
                db.delete(old)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[add_notification] Errore: {e}")
    finally:
        db.close()

def verifica_e_annuncia_aggiornamento():
    """Controlla se la versione attuale è stata già annunciata. Se no, avvisa tutti via Tagbox e Notifica."""
    ANNOUNCED_FILE = DATA_DIR / "last_announced_version.txt"
    last_announced = ""
    
    if ANNOUNCED_FILE.exists():
        last_announced = ANNOUNCED_FILE.read_text().strip()
    
    if last_announced != APP_VERSION:
        print(f"INFO: Annuncio nuova versione {APP_VERSION} in corso...")
        
        # 1. Post sulla Tagbox a nome ADMIN
        shouts = load_tagbox()
        nuovo_annuncio = {
            "id": uuid.uuid4().hex[:6],
            "user": "ADMIN",
            "user_id": "system_admin",
            # --- MODIFICA: Inserito il link HTML al changelog all'interno del testo ---
            "text": f"🚀 Rilasciata Versione {APP_VERSION}! <a href='/changelog' style='color: #0d6efd; text-decoration: underline; font-weight: 600;'>Clicca qui per scoprire le novità</a>",
            "timestamp": datetime.datetime.now().strftime("%H:%M"),
            "pinned": True
        }
        shouts.insert(0, nuovo_annuncio)
        save_tagbox(shouts[:50])
        
        # 2. Notifica campanella a tutti gli utenti
        all_users = load_users()
        for u in all_users:
            add_notification(
                user_id=u["username"], 
                text=f"ADMIN: È disponibile la nuova v{APP_VERSION}.", 
                link="/changelog"
            )
        
        # 3. Salva l'avvenuto annuncio
        ANNOUNCED_FILE.write_text(APP_VERSION)


@app.route("/api/notifications")
@login_required
def get_notifications():
    all_n = load_notifications()
    # Filtra per l'utente corrente
    my_n = [n for n in all_n if (n.get("target_user") or n.get("user_id")) == session["user_id"]]
    unread = sum(1 for n in my_n if not n["read"])
    return jsonify({"notifications": my_n[:20], "unread_count": unread})

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def mark_notifications_read():
    all_n = load_notifications()
    for n in all_n:
        if (n.get("target_user") or n.get("user_id")) == session["user_id"]:
            n["read"] = True
    save_notifications(all_n)
    return jsonify({"success": True})    


if __name__ == "__main__":

    # ─────────────────────────────────────────────────────────────────────
    # MODALITA' INSTALLER: Esegue script di setup e termina immediatamente.
    # Questi flag sono lanciati da Inno Setup [Run] in modo silenzioso.
    # ─────────────────────────────────────────────────────────────────────

    if "--run-migration" in sys.argv:
        """
        Esegue la migrazione dati V2 -> V3 e termina.
        Chiamato dall'installer Inno Setup post-install (Step 1).
        """
        import traceback
        log_path = DATA_DIR / "migration_installer.log"
        def _log(msg):
            print(msg)
            try:
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(msg + "\n")
            except Exception:
                pass
        _log(f"[--run-migration] Avvio alle {__import__('datetime').datetime.now()}")
        try:
            from migrate_v3_installer import main as _run_mig
            _original_argv = sys.argv[:]
            sys.argv = ["migrate_v3_installer.py", str(DATA_DIR)]
            try:
                # L'installer gira nascosto: il riepilogo della migrazione va nel log
                import contextlib
                with open(log_path, "a", encoding="utf-8") as _f, contextlib.redirect_stdout(_f):
                    _esito = _run_mig()
                _log("[--run-migration] Completata con successo." if not _esito
                     else "[--run-migration] INCOMPLETA: verra' ritentata al prossimo avvio.")
            finally:
                sys.argv = _original_argv
        except Exception as _e:
            _log(f"[--run-migration] ERRORE: {_e}")
            _log(traceback.format_exc())
        sys.exit(0)

    if "--fix-pagamenti" in sys.argv:
        """
        Esegue il fix retrocompatibilita' pagamenti V2 e termina.
        Chiamato dall'installer Inno Setup post-install (Step 2).
        """
        import traceback
        log_path = DATA_DIR / "fix_pagamenti.log"
        def _log(msg):
            print(msg)
            try:
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(msg + "\n")
            except Exception:
                pass
        _log(f"[--fix-pagamenti] Avvio alle {__import__('datetime').datetime.now()}")
        try:
            # One-shot: va eseguito solo subito dopo la migrazione, non a ogni aggiornamento
            _fix_flag = DATA_DIR / "fix_pagamenti_v2_done.flag"
            if _fix_flag.exists():
                _log("[--fix-pagamenti] Gia' eseguito in precedenza, skip.")
            elif not (DATA_DIR / "migration_v3_done.flag").exists():
                _log("[--fix-pagamenti] Migrazione non completata, skip (verra' ritentato).")
            else:
                # Importa ed esegue il fix inline (senza subprocess)
                from fix_pagamenti_v2 import main as _run_fix
                import contextlib
                with open(log_path, "a", encoding="utf-8") as _f, contextlib.redirect_stdout(_f):
                    _run_fix()
                _fix_flag.write_text("ok", encoding="utf-8")
                _log("[--fix-pagamenti] Completato con successo.")
        except Exception as _e:
            _log(f"[--fix-pagamenti] ERRORE: {_e}")
            _log(traceback.format_exc())
        sys.exit(0)

    # --- MODALITA' DEBUG ---
    if "--debug" in sys.argv:
        print(">>> AVVIATO IN MODALITA' DEBUG DIRETTA")

        # In modalità debug, il server Flask con il reloader DEVE girare nel thread principale.
        # Spostiamo quindi l'icona della tray in un thread in background.

        # 1. Eseguiamo le operazioni di setup iniziali
        setup_first_run()
        print("INFO: Avvio servizi principali dell'applicazione...")
        manage_firewall_rule(PORT)

        # 2. Avviamo l'icona della tray in un thread separato (daemon)
        tray_thread = threading.Thread(target=run_tray_icon_loop, daemon=True)
        tray_thread.start()
        print("INFO: Icona nella tray avviata in background.")

        # 3. Apriamo il browser
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            webbrowser.open(DISPLAY_URL)    

        # 4. Avviamo il server Flask nel thread principale (questo bloccherà lo script qui)
        #    Ora l'auto-reloader funzionerà correttamente.
        run_server()

    # --- MODALITÀ PRODUZIONE (INVARIATA) ---
    else:
        # 1. Avvia il launcher e attende la sua chiusura
        launcher_app = AppLauncher()
        launcher_app.mainloop()

        # 2. Dopo che il launcher si è chiuso, il codice prosegue qui
        if launcher_app.should_start_server:
            # 3. Il thread principale esegue il loop bloccante dell'icona,
            #    mantenendo l'applicazione e il thread del server (con Waitress) attivi.
            run_tray_icon_loop()
        else:
            # Se non dobbiamo avviare il server (es. durante un update), lo script termina.
            print("--- Chiusura richiesta dal launcher. ---")