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
from flask import send_file
import pandas as pd
import io
from flask import send_file
from openpyxl import load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.utils import get_column_letter


APP_VERSION = "2.4.1"  

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

def run_tray_icon_loop():
    """Crea e avvia il loop bloccante dell'icona nella tray."""
    try:
        image = Image.open(resource_path("static/favicon.ico"))
        menu_items = (item(f"Versione: {APP_VERSION}", None, enabled=False),item('Apri Gestionale', open_app, default=True), item('Riavvia', restart_app), item('Esci', quit_app))
        icon = pystray.Icon("Gestionale", image, SERVER_ADDRESS_INFO, menu_items)
        
        print("--- Il Launcher ha passato il testimone. Il programma ora attende la chiusura dal tray. ---")
        # Questa è la chiamata BLOKCCANTE che tiene vivo il programma
        icon.run()
    except Exception as e:
        print(f"ERRORE: Impossibile creare l'icona nella tray. Dettagli: {e}")

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

@app.context_processor
def inject_debug_mode():
    """Rende la variabile 'debug_mode' disponibile in tutti i template."""
    return dict(debug_mode=app.config['DEBUG'])

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

def load_margini_config():
    """Carica la configurazione dei margini da file, unendo i default per sicurezza."""
    config = DEFAULT_MARGINI
    if MARGINI_FILE.exists():
        try:
            with MARGINI_FILE.open("r", encoding="utf-8") as f:
                saved_config = json.load(f)
            # Logica di unione per garantire che tutte le chiavi esistano
            if "fasce" in saved_config:
                for i, fascia in enumerate(config["fasce"]):
                    saved_fascia = next((sf for sf in saved_config["fasce"] if sf.get("key") == fascia["key"]), None)
                    if saved_fascia:
                        fascia["max_costo"] = saved_fascia.get("max_costo", fascia["max_costo"])
                        fascia["pallini"] = saved_fascia.get("pallini", fascia["pallini"])
        except (json.JSONDecodeError, IOError):
            return DEFAULT_MARGINI # In caso di errore, torna ai default
    return config
# --- FINE BLOCCO GESTIONE MARGINI ---
def setup_first_run():
    """
    Controlla se i file di base (es. comuni.json) esistono nella cartella
    dati permanente. Se no, li copia dalla versione impacchettata.
    """
    dest_comuni_file = DATA_DIR / "comuni.json"
    if not dest_comuni_file.exists():
        print("INFO: Primo avvio, configurazione dati iniziali...")
        try:
            # Usa la funzione resource_path per trovare il file dentro l'EXE
            source_comuni_file = resource_path("data/comuni.json")
            shutil.copy2(source_comuni_file, dest_comuni_file)
            print(f"INFO: 'comuni.json' copiato in {dest_comuni_file}")
        except Exception as e:
            print(f"ERRORE CRITICO: Impossibile copiare i dati iniziali. Dettagli: {e}")
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
def load_users():
    """Carica gli utenti da AppData, creandolo se manca."""
    if not os.path.exists(USERS_FILE):
        # Se non esiste in AppData, prova a copiarlo dalla cartella 'data' del programma
        legacy_path = resource_path("data/users.json")
        if os.path.exists(legacy_path):
            shutil.copy(legacy_path, USERS_FILE)
        else:
            return []
    
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

# Carichiamo il changelog (Sola lettura, resta nella cartella app)
try:
    with open(resource_path("data/changelog.json"), "r", encoding="utf-8") as f:
        CHANGELOG_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    CHANGELOG_DATA = []

# Carichiamo il changelog (Sola lettura, resta nella cartella app)
try:
    with open(resource_path("data/changelog.json"), "r", encoding="utf-8") as f:
        CHANGELOG_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    CHANGELOG_DATA = []

    CHANGELOG_DATA = []
    print("ATTENZIONE: File 'data/changelog.json' non trovato o corrotto.")
def save_users(users_data):
    with USERS_FILE.open("w", encoding="utf-8") as f: json.dump(users_data, f, ensure_ascii=False, indent=2)
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

def get_all_quotes(user_role=None, full_name=None): # Rinominato user_name -> username
    """Restituisce un elenco di preventivi, filtrato per venditore se richiesto."""
    quotes = []
    # Cambiato da "P*.json" a "*.json" per includere anche EDIL-
    for quote_file in QUOTES_DIR.glob("*.json"):
        try:
            with quote_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if user_role == 'venditore' and data.get('venditore') != full_name:
                    continue
                
                quotes.append({
                    "numero": data.get("numero"), "data": data.get("data"),
                    "cliente": data.get("cliente"), "totale": data.get("totale"),
                    "stato": data.get("stato", "Bozza")
                })
        except Exception as e:
            print(f"Errore nel caricare il preventivo {quote_file.name}: {e}")
    
    quotes.sort(key=lambda x: x.get("numero", ""), reverse=True)
    return quotes
def get_new_quote_id(venditore_sigla):
    if not venditore_sigla: venditore_sigla = "XX"
    now = datetime.datetime.now()
    mesi_map = {1: "GN", 2: "FB", 3: "MR", 4: "AP", 5: "MG", 6: "GU", 7: "LU", 8: "AG", 9: "ST", 10: "OT", 11: "NV", 12: "DC"}
    prefix = "PREV-"; giorno = now.strftime('%d'); mese = mesi_map[now.month]; anno = now.strftime('%y'); ora = now.strftime('%I'); ampm = 'A' if now.strftime('%p') == 'AM' else 'P'; minuti = now.strftime('%M')
    return f"{prefix}{venditore_sigla.upper()}-{giorno}{mese}{anno}{ora}{ampm}{minuti}"
def load_quote(quote_id):
    quote_file = QUOTES_DIR / f"{quote_id}.json";
    if quote_file.exists():
        with quote_file.open("r", encoding="utf-8") as f: return json.load(f)
    return None
def save_quote(quote_id, data):
    data = aggiorna_stato_pagamento_globale(data)
    quote_file = QUOTES_DIR / f"{quote_id}.json";
    with quote_file.open("w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)



def aggiorna_stato_consegna_globale(preventivo_data):
    """
    Ricalcola lo stato di consegna globale.
    """
    stato_preventivo = preventivo_data.get("stato")
    is_edile = preventivo_data.get("tipo_preventivo") == "edile"
    
    if is_edile:
        righe = preventivo_data.get("righe_edili", [])
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
        o for o in preventivo_data.get("ordini_fornitore", []) 
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
    ordini_fornitore = preventivo_data.get("ordini_fornitore", [])
    
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
    client_file = CLIENTS_DIR / f"{client_id}.json"
    if client_file.exists():
        with client_file.open("r", encoding="utf-8") as f: return json.load(f)
    return None
def save_client(client_id, data):
    client_file = CLIENTS_DIR / f"{client_id}.json"
    with client_file.open("w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
def find_clients_by_term(search_term):
    found_clients = []
    if not search_term: return found_clients
    term = search_term.lower()
    for client_file in CLIENTS_DIR.glob("*.json"):
        try:
            with client_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if term in data.get("cliente", "").lower() or term in data.get("rag_sociale", "").lower(): found_clients.append(data)
        except Exception: continue
    return found_clients
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
            # Cancella la vecchia sessione, inclusi i nostri "segnali"
            session.clear() 
            session["user_id"] = user_found["username"]
            session["user_name"] = user_found["full_name"]
            session["user_role"] = user_found["role"]
            session["user_sigla"] = user_found.get("sigla", "XX")
            session["force_password_reset"] = user_found.get("force_password_reset", False)

            flash(f"Benvenuto, {user_found['full_name']}!", "success")
            
            # Vai direttamente alla dashboard senza controllare il changelog
            return redirect(url_for("dashboard"))
        else:
            flash("Credenziali non valide. Riprova.", "error")
# --------------------------------------------------

    return render_template("login.html", app_version=APP_VERSION)

@app.route("/logout", methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for("login"))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session: return redirect(url_for("login"))
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

@app.route("/")
@login_required
def dashboard():
    user_role = session.get("user_role")
    full_name = session.get("user_name")
    
    # 1. Carichiamo TUTTI i preventivi, senza filtri
    all_quotes_summary = get_all_quotes()
    
    my_active_quotes = []
    grouped_active_quotes = {}
    today = datetime.date.today()
    stati_ordine_validi = ["Confermato", "In Lavorazione"]

    # 2. Iteriamo e filtriamo
    for summary in all_quotes_summary:
        p = load_quote(summary["numero"])
        if not p: continue

        # Filtro universale: Salta chiusi e annullati
        if p.get("stato") in ["Chiuso", "Annullato"]:
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
            
            ordini_fornitore = p.get("ordini_fornitore", [])
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

    return render_template("dashboard.html", 
        title="Dashboard",
        app_name=APP_NAME,
        my_quotes=my_active_quotes, # Per 'venditore' e 'admin'/'ceo'
        grouped_quotes=grouped_active_quotes # Per 'segreteria' e 'admin'/'ceo'
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

    # 1. Scansione Preventivi per Pagamenti Scaduti, Merce e Identificazione Clienti Attivi
    for quote_file in QUOTES_DIR.glob("P*.json"):
        try:
            with quote_file.open("r", encoding="utf-8") as f:
                p = json.load(f)
                
                # Segnamo il cliente come attivo se il preventivo è in uno stato operativo
                if p.get("stato") in active_statuses:
                    active_client_ids.add(p.get("id_cliente"))
                
                if p.get("stato") in ["Annullato", "Chiuso"]: 
                    continue
                
                # --- ALERT PAGAMENTI ---
                for pag in p.get("pagamenti", []):
                    if pag.get("is_scheduled") and pag.get("data") <= today_str:
                        alerts.append({
                            "tipo": "PAGAMENTO",
                            "oggetto_id": p.get("numero"),
                            "oggetto_nome": p.get("cliente"),
                            "dettaglio": f"Pagamento da {money_ui(pag.get('importo'))} scaduto il {pag.get('data')}",
                            "link_risoluzione": url_for('gestione_pagamenti', quote_id=p.get("numero")),
                            "icona": "fas fa-hand-holding-usd",
                            "colore": "text-danger"
                        })

                # --- ALERT PAGAMENTI ---
                for pag in p.get("pagamenti", []):
                    if pag.get("is_scheduled") and pag.get("data") <= today_str:
                        alerts.append({
                            "tipo": "PAGAMENTO",
                            "oggetto_id": p.get("numero"),
                            "oggetto_nome": p.get("cliente"),
                            "dettaglio": f"Pagamento da {money_ui(pag.get('importo'))} scaduto il {pag.get('data')}",
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
                                    "dettaglio": f"Manca data arrivo prevista per ordine {ordine.get('azienda')} (Creato il {data_creazione_ordine})",
                                    "link_risoluzione": url_for('conferma_ordine', quote_id=p.get("numero")),
                                    "icona": "fas fa-calendar-exclamation",
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
                                        "dettaglio": f"Ritardo da {ordine.get('azienda')} (Previsto: {data_prevista}). {len(mancanti_in_ordine)} articoli mancanti.",
                                        "link_risoluzione": url_for('gestione_consegna', quote_id=p.get("numero")),
                                        "icona": "fas fa-truck-loading",
                                        "colore": "text-blue"
                                    })
                        except (ValueError, TypeError): continue
        except: continue

    # 2. Scansione Clienti per Documenti Mancanti (Solo se il cliente è attivo)
    for client_file in CLIENTS_DIR.glob("*.json"):
        try:
            with client_file.open("r", encoding="utf-8") as f:
                c = json.load(f)
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

    return render_template("allert.html", title="Centro Notifiche & Alert", alerts=alerts)


@app.route("/admin/refresh-all-quotes")
@login_required
@role_required('amministratore', 'ceo')
def refresh_all_quotes():
    """
    Cicla tutti i preventivi e ricalcola i loro stati globali (pagamento, consegna, avanzamento).
    Questo corregge i dati "stale" (non aggiornati) nei vecchi file JSON.
    """
    print("--- INIZIO: Aggiornamento stati globali di tutti i preventivi ---")
    all_quote_files = list(QUOTES_DIR.glob("P*.json"))
    processed_count = 0
    updated_count = 0
    
    for quote_file in all_quote_files:
        try:
            p = load_quote(quote_file.stem)
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
            print(f"ERRORE: Impossibile aggiornare il file {quote_file.name}. Dettagli: {e}")

    print(f"--- FINE: Elaborati {processed_count}. Aggiornati {updated_count}. ---")
    flash(f"Aggiornamento completato. Elaborati {processed_count}/{len(all_quote_files)} preventivi. Aggiornati {updated_count} file.", "success")
    return redirect(url_for("dashboard"))

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

            # 5. Salva l'intero oggetto 'config' aggiornato, preservando
            #    tutte le chiavi (incluse 'key', 'descrizione' e 'regole_colore')
            with MARGINI_FILE.open("w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
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
    clients = []
    active_statuses = ["Bozza", "Inviato", "In Lavorazione"]
    active_client_ids = set()

    # 1. Scansiona i preventivi per trovare i clienti con pratiche attive
    for quote_file in QUOTES_DIR.glob("P*.json"):
        try:
            with quote_file.open("r", encoding="utf-8") as f:
                q_data = json.load(f)
                if q_data.get("stato") in active_statuses:
                    active_client_ids.add(q_data.get("id_cliente"))
        except:
            continue

    # 2. Carica i dati anagrafici dei clienti
    for client_file in CLIENTS_DIR.glob("*.json"):
        try:
            with client_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Segna se il cliente ha almeno un preventivo attivo
                data["has_active_quote"] = data.get("id_cliente") in active_client_ids
                clients.append(data)
        except Exception:
            continue
    
    clients.sort(key=lambda x: x.get("cliente", "").lower())
    
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
        righe_preventivo = p.get("righe_edili", []) if is_edile else p.get("righe", [])
        
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
            
            ordini_fornitore = p.get("ordini_fornitore", [])
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
                righe_lavorazione = p.get("righe_edili", [])
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
    
    quote_dirs = ["preventivi", os.path.join("data", "preventivi")]
    has_active_quotes = False
    
    for q_dir in quote_dirs:
        if os.path.exists(q_dir):
            for fname in os.listdir(q_dir):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(q_dir, fname), "r", encoding="utf-8") as f:
                            q_data = json.load(f)
                            if q_data.get("id_cliente") == client_id:
                                if q_data.get("stato") not in ["Annullato", "annullato"]:
                                    has_active_quotes = True
                                    break
                    except Exception:
                        pass
            if has_active_quotes:
                break
                
    if has_active_quotes:
        return jsonify({"success": False, "error": "Preventivi presenti per questo cliente, annullare tutti i preventivi o contattare l'amministratore di sistema."})
        
    client_dirs = ["clienti", os.path.join("data", "clienti")]
    deleted = False
    for c_dir in client_dirs:
        filepath = os.path.join(c_dir, f"{client_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted = True
            break
            
    if deleted:
        return jsonify({"success": True, "message": "Cliente eliminato con successo."})
    else:
        return jsonify({"success": False, "error": "Impossibile trovare il file del cliente per l'eliminazione."})

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
        "fatture_allegate", "ordini_fornitore", "data_conferma", "data_chiusura"
    ]
    for campo in campi_da_rimuovere:
        p_clonato.pop(campo, None)
    
    # Resetta stato consegna righe (sia standard che edili)
    if "righe" in p_clonato:
        for r in p_clonato["righe"]:
            r.pop("stato_consegna", None); r.pop("bolla_id", None); r.pop("data_consegna", None)
            
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
    p["data_conferma"] = datetime.date.today().strftime('%Y-%m-%d')

    # Se Edile, marca tutto come Pronto per Consegna automaticamente
    if p.get("tipo_preventivo") == "edile":
        for riga in p.get("righe_edili", []):
            if riga.get("stato_consegna") != "Consegnato":
                riga["stato_consegna"] = "Pronto per Consegna"
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
    # Se abbiamo salvato l'IVA specifica dell'ordine, usiamo quella per avere il netto esatto
    if "iva_ordine" in ordine:
        return imp_lordo - _to_float(ordine["iva_ordine"])
    # Fallback: scorporo 22% forfettario
    return imp_lordo / 1.22

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
    if start_date < MIN_DATE: start_date = MIN_DATE

    if end_date_str:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    else:
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        end_date = next_month - datetime.timedelta(days=next_month.day)

    # --- INIZIALIZZAZIONE ---
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

    funnel = { "creati": 0, "inviati": 0, "confermati": 0, "annullati": 0, "valore_in_trattativa": 0.0, "tasso_firma": 0.0 }
    
    venditori_dict = {}
    referenti_dict = {}
    future_payments = []
    daily_stats = {} 

    all_quotes = get_all_quotes()

    for summary in all_quotes:
        p = load_quote(summary["numero"])
        if not p: continue

        # Determiniamo la data di riferimento: data_conferma per i confermati/chiusi, data creazione per gli altri
        st_competenza = p.get("stato")
        raw_date = p.get("data_conferma") if st_competenza in ["Confermato", "In Lavorazione", "Chiuso"] and p.get("data_conferma") else p.get("data")
        
        try: 
            p_date = datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
        except: 
            continue

        imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
        tot_lordo = _to_float(p.get("totale", 0))
        fee_pct = _to_float(p.get("fee_pct", 0))

        raw_no_iva = p.get("no_iva")
        is_no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")
        
        ratio_netto = 1.0
        if tot_lordo > 0: ratio_netto = imponibile / tot_lordo

        # === 1. LOGICA COMPETENZA (FILTRO DATA PREVENTIVO) ===
        if start_date <= p_date <= end_date:
            st = p.get("stato")
            funnel["creati"] += 1
            if st == "Bozza": funnel["valore_in_trattativa"] += imponibile
            elif st == "Inviato": 
                funnel["inviati"] += 1
                funnel["valore_in_trattativa"] += imponibile
            elif st in ["Confermato", "In Lavorazione", "Chiuso"]:
                funnel["inviati"] += 1
                funnel["confermati"] += 1
            elif st == "Annullato": funnel["annullati"] += 1

            if st in ["Confermato", "In Lavorazione", "Chiuso"]:
                # Costi Presunti (Negozio)
                c_presunto = _to_float(p.get("tot_imponibile_negozio", 0))

                # Costi Reali (Ordini - NETTO)
                c_reale = 0.0
                
                # Se è edile, il costo stimato manuale viene considerato costo reale (effettivo)
                if p.get("tipo_preventivo") == "edile":
                    c_reale += sum(_to_float(r.get("costo_stimato")) for r in p.get("righe_edili", []))

                for ordine in p.get("ordini_fornitore", []):
                    # Usiamo il helper per il netto
                    c_reale += _get_netto_ordine(ordine)
                    # Accumulo IVA ordini per KPI cashflow (anche se qui è competenza, serve per totale)
                    cashflow["iva_ordini"] += _to_float(ordine.get("iva_ordine", 0))
                
                fee_val = 0.0 if fee_pct <= 0 else imponibile * (fee_pct / 100.0)
                c_rif = c_reale if c_reale > 0 else c_presunto
                margine = imponibile - c_rif

                kpi["imponibile_totale"] += imponibile
                kpi["costi_preventivati_totali"] += c_presunto
                kpi["costi_reali_totali"] += c_reale
                kpi["fee_versata"] += fee_val
                kpi["utile_netto_finale"] += margine

                vnd = p.get("venditore", "N/D")
                if vnd not in venditori_dict: venditori_dict[vnd] = {"nome": vnd, "count": 0, "imponibile": 0.0, "utile": 0.0}
                venditori_dict[vnd]["count"] += 1
                venditori_dict[vnd]["imponibile"] += imponibile
                venditori_dict[vnd]["utile"] += margine

                ref = p.get("referente", "") 
                if ref:
                    if ref not in referenti_dict: referenti_dict[ref] = {"nome": ref, "preventivo": 0, "imponibile": 0.0, "fee": 0.0}
                    referenti_dict[ref]["preventivo"] += 1
                    referenti_dict[ref]["imponibile"] += imponibile
                    referenti_dict[ref]["fee"] += fee_val

                d_str = raw_date
                if d_str not in daily_stats: daily_stats[d_str] = {"imp": 0, "marg": 0, "fee": 0, "c_reale": 0, "c_pres": 0}
                daily_stats[d_str]["imp"] += imponibile
                daily_stats[d_str]["marg"] += margine
                daily_stats[d_str]["fee"] += fee_val
                daily_stats[d_str]["c_reale"] += c_rif
                daily_stats[d_str]["c_pres"] += c_presunto

                # Residuo da Saldare (Stock)
                inc_tot_quote = sum(_to_float(x.get("importo", 0)) for x in p.get("pagamenti", []))
                residuo = tot_lordo - inc_tot_quote
                cashflow["da_saldare_netto"] += residuo * ratio_netto
        
        # === 2. LOGICA CASSA (DATA PAGAMENTO) ===
        if p.get("stato") in ["Confermato", "In Lavorazione", "Chiuso"]:
            
            # --- INCASSI ---
            for pag in p.get("pagamenti", []):
                val_lordo = _to_float(pag.get("importo", 0))
                try: d_pag = datetime.datetime.strptime(pag.get("data"), "%Y-%m-%d").date()
                except: d_pag = today 
                
                val_netto = val_lordo * ratio_netto
                quota_iva = val_lordo - val_netto
                fee_su_incasso = val_netto * (fee_pct / 100.0) if fee_pct > 0 else 0.0

                # A. PAGAMENTI GIÀ INCASSATI (Solo se NON programmati/scheduled)
                if start_date <= d_pag <= end_date and not pag.get("is_scheduled"):
                    cashflow["incassato_netto"] += val_netto
                    cashflow["fee_versata"] += fee_su_incasso
                    if not is_no_iva: cashflow["iva_preventivi"] += quota_iva

                # B. PAGAMENTI PROGRAMMATI / IN ATTESA (Riconosciuti dal flag is_scheduled)
                if pag.get("is_scheduled"):
                    cashflow["in_attesa_netto"] += val_netto
                    future_payments.append({
                        "data": d_pag, 
                        "cliente": p.get("cliente"), 
                        "preventivo": p.get("numero"),
                        "importo_netto": val_netto, 
                        "note": pag.get("note", "")
                    })
            
            # --- USCITE (ORDINI) ---
            # Nota: Qui usiamo il filtro data transazione per il Cashflow
            for ordine in p.get("ordini_fornitore", []):
                d_trans = None
                if ordine.get("allegati"): 
                    try: d_trans = datetime.datetime.strptime(ordine["allegati"][0]["data_upload"], "%Y-%m-%d").date()
                    except: pass
                if not d_trans and ordine.get("data_arrivo"):
                    try: d_trans = datetime.datetime.strptime(ordine.get("data_arrivo"), "%Y-%m-%d").date()
                    except: pass
                if not d_trans:
                    # Fallback alla data di conferma (già calcolata e salvata in p_date)
                    try: d_trans = p_date
                    except: continue

                if start_date <= d_trans <= end_date:
                    # ORA USIAMO IL NETTO ANCHE QUI!
                    imp_ord_netto = _get_netto_ordine(ordine)
                    cashflow["costi_preventivi_in_corso"] += imp_ord_netto
                    # L'IVA ordini è già stata sommata sopra per il KPI totale, ma qui serve per il bilancio IVA di periodo
                    # Attenzione: sopra era nel ciclo competenza. Qui dobbiamo sommarla se cade nel periodo cassa.
                    # Ma nel ciclo competenza l'abbiamo sommata solo se il PREVENTIVO è nel periodo.
                    # Qui la sommiamo se l'ORDINE è nel periodo.
                    # Per il bilancio IVA usiamo questo valore qui.
                    # Resetto iva_ordini calcolata nel ciclo competenza perché mescolava le logiche?
                    # No, cashflow["iva_ordini"] è usata solo nel box IVA. Usiamo la somma di periodo cassa.
                    pass 

            if start_date <= p_date <= end_date and is_no_iva:
                cashflow["iva_esente"] += _to_float(p.get("tot_iva", 0))

    # --- CALCOLO BILANCI ---
    # Ricalcolo IVA ordini basato strettamente sul periodo cassa per correttezza
    iva_ordini_cassa = 0.0
    for summary in all_quotes:
        p = load_quote(summary["numero"])
        if not p or p.get("stato") not in ["Confermato", "In Lavorazione", "Chiuso"]: continue
        for o in p.get("ordini_fornitore", []):
             d_trans = None
             if o.get("allegati"): 
                try: d_trans = datetime.datetime.strptime(o["allegati"][0]["data_upload"], "%Y-%m-%d").date()
                except: pass
             if not d_trans and o.get("data_arrivo"):
                try: d_trans = datetime.datetime.strptime(o.get("data_arrivo"), "%Y-%m-%d").date()
                except: pass
             if not d_trans: d_trans = _str_to_date(p.get("data_conferma") if p.get("data_conferma") else p.get("data")) # Fallback
             
             if d_trans and start_date <= d_trans <= end_date:
                 iva_ordini_cassa += _to_float(o.get("iva_ordine", 0))
    
    cashflow["iva_ordini"] = iva_ordini_cassa

    # Bilancio = Incassi Netti - Costi Netti - Fee
    cashflow["bilancio"] = cashflow["incassato_netto"] - cashflow["costi_preventivi_in_corso"] - cashflow["fee_versata"]
    cashflow["bilancio_iva"] = cashflow["iva_preventivi"] - cashflow["iva_ordini"]

    # Finalizzazione KPI
    kpi["scostamento_totale"] = kpi["costi_preventivati_totali"] - kpi["costi_reali_totali"]
    if kpi["imponibile_totale"] > 0:
        kpi["marginalita_totale_pct"] = (kpi["utile_netto_finale"] / kpi["imponibile_totale"]) * 100
        if (kpi["imponibile_totale"] - kpi["utile_netto_finale"]) > 0:
             kpi["margine_medio_pct"] = (kpi["utile_netto_finale"] / (kpi["imponibile_totale"] - kpi["utile_netto_finale"])) * 100
    if funnel["creati"] > 0: funnel["tasso_firma"] = (funnel["confermati"] / funnel["creati"]) * 100

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
        start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d"),
        kpi=kpi, cashflow=cashflow, funnel=funnel,
        venditori=venditori_list, referenti=referenti_list, 
        future_payments=future_payments,
        grafico=grafico_out
    )

@app.route("/dashboard/ceo/export_cashflow")
@login_required
def export_cashflow_excel():
    if session.get("user_role") not in ["amministratore", "ceo"]:
        flash("Accesso negato.", "error")
        return redirect(url_for("dashboard"))

    try:
        import pandas as pd
        import io
        from flask import send_file
        from openpyxl import load_workbook
        from openpyxl.utils.dataframe import dataframe_to_rows
        from openpyxl.utils import get_column_letter
    except ImportError:
        flash("Libreria 'pandas' o 'openpyxl' non installata.", "error")
        return redirect(url_for("dashboard_ceo"))

    # Recupero Date
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    today = datetime.date.today()
    
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else today.replace(day=1)
    
    if end_date_str:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
    else:
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        end_date = next_month - datetime.timedelta(days=next_month.day)

    # Caricamento Template dal percorso AppData
    template_filename = get_template_path("modello cashflow.xlsx")
    if not os.path.exists(template_filename):
        flash(f"File modello '{template_filename}' non trovato nel server!", "error")
        return redirect(url_for("dashboard_ceo"))

    all_quotes = get_all_quotes() 
    cashflow_rows = []

    for summary in all_quotes:
        p = load_quote(summary["numero"])
        if not p: continue
        
        if p.get("stato") in ["Annullato", "Bozza", "Inviato"]: 
            continue

        # --- MODIFICA: Assicuriamo che i totali siano popolati (Edile usa campi standard per i totali) ---
        imponibile = _to_float(p.get("tot_imponibile_cliente", 0))
        totale_lordo = _to_float(p.get("totale", 0))
        tot_iva = _to_float(p.get("tot_iva", 0))
        fee_pct = _to_float(p.get("fee_pct", 0))
        
        raw_no_iva = p.get("no_iva")
        is_no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")

        ratio_netto = 1.0
        ratio_iva_virtuale = 0.0

        if is_no_iva:
            ratio_netto = 1.0 
            if imponibile > 0: ratio_iva_virtuale = tot_iva / imponibile
        else:
            if totale_lordo > 0: ratio_netto = imponibile / totale_lordo

        # --- A. ENTRATE ---
        for pag in p.get("pagamenti", []):
            try: d_pag = datetime.datetime.strptime(pag.get("data"), "%Y-%m-%d").date()
            except: continue 
            
            if start_date <= d_pag <= end_date:
                lordo = _to_float(pag.get("importo", 0))
                val_netto = 0.0
                val_iva_prev = 0.0
                val_iva_esente = 0.0
                
                if is_no_iva:
                    val_netto = lordo
                    val_iva_esente = val_netto * ratio_iva_virtuale
                else:
                    val_netto = lordo * ratio_netto
                    val_iva_prev = lordo - val_netto
                
                fee_val = val_netto * (fee_pct / 100.0) if fee_pct > 0 else 0.0

                cashflow_rows.append({
                    "N. PREVENTIVO": p.get("numero"), "CLIENTE": p.get("cliente"), "STATO": p.get("stato"),
                    "VENDITORE": p.get("venditore"), "ID (Rif.)": f"Pagamento ({pag.get('note', '')[:20]})",
                    "DATA TRANSAZIONE": d_pag,
                    "ENTRATE NETTE (€)": val_netto, "USCITE NETTE (€)": 0.0,
                    "FEE VERSATA ": fee_val, 
                    "IVA ORDINE (€)": 0.0, "IVA PREVENTIVO (€)": val_iva_prev, "IVA ESENTE (€)": val_iva_esente,   
                    "TIPO": "INCASSO"
            })

        # --- B. USCITE (ORDINI) ---
        # Aggiunta: Gestione costi manuali per preventivi Edili
        if p.get("tipo_preventivo") == "edile":
            costo_manuale_tot = sum(_to_num(r.get("costo_stimato", 0)) for r in p.get("righe_edili", []))
            if costo_manuale_tot > 0:
                # Usiamo la data di conferma o quella del preventivo come data transazione
                d_trans = _str_to_date(p.get("data_conferma")) or _str_to_date(p.get("data"))
                if d_trans and start_date <= d_trans <= end_date:
                    cashflow_rows.append({
                        "N. PREVENTIVO": p.get("numero"), "CLIENTE": p.get("cliente"), "STATO": p.get("stato"),
                        "VENDITORE": p.get("venditore"), "ID (Rif.)": "Costi Stimati (Manuali Edile)",
                        "DATA TRANSAZIONE": d_trans,
                        "ENTRATE NETTE (€)": 0.0, "USCITE NETTE (€)": costo_manuale_tot,
                        "FEE VERSATA ": 0.0, 
                        "IVA ORDINE (€)": 0.0, "IVA PREVENTIVO (€)": 0.0, "IVA ESENTE (€)": 0.0,   
                        "TIPO": "USCITA"
                    })

        for ordine in p.get("ordini_fornitore", []):
            d_transazione = None
            if ordine.get("allegati"):
                try: d_transazione = datetime.datetime.strptime(ordine["allegati"][0]["data_upload"], "%Y-%m-%d").date()
                except: pass
            if not d_transazione and ordine.get("data_arrivo"):
                try: d_transazione = datetime.datetime.strptime(ordine.get("data_arrivo"), "%Y-%m-%d").date()
                except: pass
            if not d_transazione:
                try: d_transazione = datetime.datetime.strptime(p.get("data_conferma") if p.get("data_conferma") else p.get("data"), "%Y-%m-%d").date()
                except: continue

            if start_date <= d_transazione <= end_date:
                # ORA USIAMO IL NETTO ANCHE QUI!
                importo_netto = _get_netto_ordine(ordine)
                iva_ordine = _to_float(ordine.get("iva_ordine", 0))
                
                cashflow_rows.append({
                    "N. PREVENTIVO": p.get("numero"), "CLIENTE": p.get("cliente"), "STATO": p.get("stato"),
                    "VENDITORE": p.get("venditore"), "ID (Rif.)": f"Ord. {ordine.get('azienda')}",
                    "DATA TRANSAZIONE": d_transazione,
                    "ENTRATE NETTE (€)": 0.0, "USCITE NETTE (€)": importo_netto,
                    "FEE VERSATA ": 0.0,
                    "IVA ORDINE (€)": iva_ordine, "IVA PREVENTIVO (€)": 0.0, "IVA ESENTE (€)": 0.0,
                    "TIPO": "USCITA"
                })

    if not cashflow_rows:
        flash("Nessuna transazione trovata nel periodo selezionato.", "warning")
        return redirect(url_for("dashboard_ceo", start_date=start_date_str, end_date=end_date_str))

    df = pd.DataFrame(cashflow_rows)
    df = df.sort_values(by="DATA TRANSAZIONE")

    cols = ["N. PREVENTIVO", "CLIENTE", "STATO", "VENDITORE", "ID (Rif.)", "DATA TRANSAZIONE", 
            "ENTRATE NETTE (€)", "USCITE NETTE (€)", "FEE VERSATA ", 
            "IVA ORDINE (€)", "IVA PREVENTIVO (€)", "IVA ESENTE (€)", "TIPO"]
    
    for c in cols:
        if c not in df.columns: df[c] = ""
    df = df[cols]

    wb = load_workbook(template_filename)
    ws = wb["Cashflow"]

    max_row = ws.max_row
    if max_row > 1:
        ws.delete_rows(2, amount=max_row-1)

    rows = dataframe_to_rows(df, index=False, header=False)
    for r_idx, row in enumerate(rows, 1):
        for c_idx, value in enumerate(row, 1):
            ws.cell(row=r_idx+1, column=c_idx, value=value)

    if ws.tables:
        total_rows = len(df) + 1
        last_col_letter = get_column_letter(len(cols))
        new_ref = f"A1:{last_col_letter}{total_rows}"
        for table in ws.tables.values():
            table.ref = new_ref

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Cashflow_Dettagliato_{start_date.strftime('%d-%m')}_{end_date.strftime('%d-%m-%Y')}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route("/dashboard/ceo/export_excel")
@login_required
def export_excel_ceo():
    # 1. Controllo Permessi
    if session.get("user_role") not in ["amministratore", "ceo"]:
        flash("Accesso negato.", "error")
        return redirect(url_for("dashboard"))

    try:
        # Verifica dipendenze
        import pandas as pd
    except ImportError:
        flash("Libreria 'pandas' non installata.", "error")
        return redirect(url_for("dashboard_ceo"))

    # 2. Recupero Date
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    today = datetime.date.today()
    
    if not start_date_str:
        start_date = today.replace(day=1)
    else:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()

    if not end_date_str:
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        end_date = next_month - datetime.timedelta(days=next_month.day)
    else:
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    # --- CARICAMENTO TEMPLATE DAL PERCORSO APPDATA ---
    template_filename = get_template_path("template_analisi.xlsx")
    if not os.path.exists(template_filename):
        flash(f"File modello '{template_filename}' non trovato nel server!", "error")
        return redirect(url_for("dashboard_ceo"))

    # Helper pulizia numeri
    def _to_float(val):
        if val is None or str(val).strip() == "": return 0.0
        if isinstance(val, (int, float)): return float(val)
        s = str(val).replace("€", "").replace("%", "").strip()
        if "," in s: s = s.replace(".", "").replace(",", ".")
        try: return float(s)
        except ValueError: return 0.0

    all_quotes = get_all_quotes() 
    export_data = []

    for summary in all_quotes:
        p = load_quote(summary["numero"])
        if not p: continue

        # --- FILTRO STATI ---
        # Escludiamo Annullato, Bozza e Inviato
        stato_attuale = p.get("stato")
        if stato_attuale in ["Annullato", "Bozza", "Inviato"]:
            continue

        # Usiamo la data di conferma per i preventivi confermati/lavorazione/chiusi
        raw_date = p.get("data_conferma") if stato_attuale in ["Confermato", "In Lavorazione", "Chiuso"] and p.get("data_conferma") else p.get("data")

        try:
            p_date = datetime.datetime.strptime(raw_date, "%Y-%m-%d").date()
        except:
            continue
            
        if start_date <= p_date <= end_date:
            
            # --- CALCOLI ---
            somma_importi_ordini = 0.0
            somma_iva_ordini = 0.0

            # Se è edile, aggiungiamo il costo stimato manuale ai costi da ordini (effettivi)
            if p.get("tipo_preventivo") == "edile":
                somma_importi_ordini += sum(_to_float(r.get("costo_stimato")) for r in p.get("righe_edili", []))

            for ordine in p.get("ordini_fornitore", []):
                imp = _to_float(ordine.get("importo", 0))
                iva = _to_float(ordine.get("iva_ordine", 0)) 
                somma_importi_ordini += imp

            # --- MODIFICA: Calcolo Costo Negozio differenziato ---
            costo_negozio_totale = 0.0
            is_edile = p.get("tipo_preventivo") == "edile"
            
            if is_edile:
                # Per l'edile sommiamo semplicemente il costo stimato di ogni riga
                for r in p.get("righe_edili", []):
                    costo_negozio_totale += _to_float(r.get("costo_stimato", 0))
            else:
                # Logica standard per articoli da listino
                for r in p.get("righe", []):
                    qt = _to_float(r.get("qt", 0))
                    cat = _to_float(r.get("prezzo_catalogo", 0))
                    s1 = _to_float(r.get("s1", 0))
                    s2 = _to_float(r.get("s2", 0))
                    s3 = _to_float(r.get("s3", 0))
                    price_netto = cat * (1 - s1/100) * (1 - s2/100) * (1 - s3/100)
                    trasp = _to_float(r.get("costo_trasporto", 0))
                    extra = _to_float(r.get("extra", 0))
                    unt = str(r.get("unt", "")).strip().upper()
                    
                    row_cost = 0.0
                    if unt == "MQ": row_cost = (price_netto * qt) + (trasp * qt) + extra
                    elif unt in ["PZ", "ML", "PZ."]: row_cost = (price_netto * qt) + trasp + extra
                    elif unt == "S": row_cost = (price_netto * qt)
                    else: row_cost = (price_netto * qt) + extra
                    costo_negozio_totale += row_cost

            imponibile_cliente = _to_float(p.get("tot_imponibile_cliente", 0))
            
            fee_pct_val = _to_float(p.get("fee_pct", 0))
            fee_euro = 0.0
            if fee_pct_val > 0:
                fee_euro = imponibile_cliente * (fee_pct_val / 100.0)

            incassato = 0.0
            programmato = 0.0
            for pag in p.get("pagamenti", []):
                val = _to_float(pag.get("importo", 0))
                try: d_pag = datetime.datetime.strptime(pag.get("data"), "%Y-%m-%d").date()
                except: d_pag = today
                if d_pag > today: programmato += val
                else: incassato += val
            
            if p.get("no_iva"):
                incassato += _to_float(p.get("tot_iva", 0))

            totale_preventivo = _to_float(p.get("totale", 0))
            da_incassare = totale_preventivo - incassato
            
            costi_riferimento = somma_importi_ordini if somma_importi_ordini > 0 else costo_negozio_totale
            margine_euro = imponibile_cliente - costi_riferimento

            # --- RIGA DATI ---
            row = {
                "N. Preventivo": p.get("numero"),
                "Data": p_date.strftime("%Y-%m-%d"),
                "Cliente": p.get("cliente"),
                "Stato": p.get("stato"),
                "Totale Preventivo (€)": totale_preventivo,
                "Imponibile Cliente (€)": imponibile_cliente,
                "IVA (€)": _to_float(p.get("tot_iva", 0)),
                "Costi da Ordini (€)": somma_importi_ordini,
                "IVA su Ordini (€)": somma_iva_ordini,
                "Costo Negozio Stimato (€)": costo_negozio_totale,
                "Margine (€)": margine_euro,
                "FEE %": p.get("fee_pct", ""),
                "FEE (€)": fee_euro,
                "Incassato (€)": incassato,
                "Da Incassare (€)": da_incassare,
                "Programmato Futuro (€)": programmato,
                "Esente IVA": "SÌ" if p.get("no_iva") else "NO",
                "Stato Fattura": p.get("stato_fattura", "N/D"),
                "Stato Pagamento": p.get("stato_pagamento_globale", "N/D"),
                "Venditore": p.get("venditore"),
                "Stato Consegna": p.get("stato_consegna_globale", "N/D")
            }
            export_data.append(row)

    if not export_data:
        flash("Nessun dato valido trovato (esclusi Bozze/Inviati/Annullati).", "warning")
        return redirect(url_for("dashboard_ceo", start_date=start_date_str, end_date=end_date_str))

    # --- SCRITTURA NEL TEMPLATE ---
    df = pd.DataFrame(export_data)
    cols = [
        "N. Preventivo", "Data", "Cliente", "Stato", 
        "Totale Preventivo (€)", "Imponibile Cliente (€)", "IVA (€)", 
        "Costi da Ordini (€)", "IVA su Ordini (€)", "Costo Negozio Stimato (€)", 
        "Margine (€)", "FEE %", "FEE (€)", 
        "Incassato (€)", "Da Incassare (€)", "Programmato Futuro (€)", 
        "Esente IVA", "Stato Fattura", "Stato Pagamento", "Venditore", "Stato Consegna"
    ]
    df = df[[c for c in cols if c in df.columns]]

    wb = load_workbook(template_filename)
    if "Analisi" not in wb.sheetnames:
        flash("Il file modello non contiene un foglio chiamato 'Analisi'.", "error")
        return redirect(url_for("dashboard_ceo"))
        
    ws = wb["Analisi"]

    # 1. Pulisce i dati vecchi
    max_row = ws.max_row
    if max_row > 1:
        ws.delete_rows(2, amount=max_row-1)

    # 2. Scrive i nuovi dati
    rows = dataframe_to_rows(df, index=False, header=False)
    for r_idx, row in enumerate(rows, 1):
        for c_idx, value in enumerate(row, 1):
            ws.cell(row=r_idx+1, column=c_idx, value=value)

    # 3. Aggiorna dimensioni Tabella Excel
    if ws.tables:
        total_rows = len(df) + 1
        last_col_letter = get_column_letter(len(cols))
        new_ref = f"A1:{last_col_letter}{total_rows}"
        for table in ws.tables.values():
            table.ref = new_ref

    # 4. Salva e Invia
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Analisi_Globale_{start_date.strftime('%d-%m')}_{end_date.strftime('%d-%m-%Y')}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )
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
            if pag.get("rectifies_id"): continue
            imp_pag = _to_num(pag.get("importo"))
            if imp_pag <= 0: continue
            
            if pag.get("is_scheduled"):
                analisi['da_incassare'] += imp_pag
            else:
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

        # 3. Calcoliamo gli articoli ancora da ordinare
        articoli_da_ordinare_count = len(indici_righe_valide - indici_gia_ordinati)
        p["articoli_da_ordinare_count"] = articoli_da_ordinare_count

        # 4. Calcoliamo (come prima) gli articoli in ordini in attesa di conferma
        articoli_in_attesa_conferma = 0
        ordini_in_attesa = [o for o in ordini_fornitore if not o.get("numero_conferma", "").strip()]
        for ordine in ordini_in_attesa:
            articoli_in_attesa_conferma += len(ordine.get("indici_righe", []))
        p["articoli_in_attesa_conferma"] = articoli_in_attesa_conferma

        # 5. Aggiungiamo il preventivo alla dashboard SOLO se c'è qualcosa da fare
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
                    preventivi_da_consegnare.append(p)
            continue

        ordini_confermati = [o for o in p.get("ordini_fornitore", []) if o.get("numero_conferma", "").strip()]
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
        ordini_confermati = [o for o in p.get("ordini_fornitore", []) if o.get("numero_conferma", "").strip()]
        
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

    # --- MODIFICA IMPORTANTE ---
    # ABBIAMO RIMOSSO IL CICLO CHE IMPOSTAVA "In Bolla" QUI.
    # Lo stato verrà aggiornato solo se il PDF viene generato con successo.
    # ---------------------------

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
    """Pagina di attesa per la generazione del PDF della bolla."""
    return render_template("loading_bolla.html", quote_id=quote_id, bolla_id=bolla_id)

@app.route("/generate-bolla-task/<quote_id>/<bolla_id>")
@login_or_local_required
def generate_bolla_task(quote_id, bolla_id):
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
    target_list = "righe_edili" if is_edile else "righe"
    template_name = "stampa_consegna_lavori.html" if is_edile else "stampa_bolla.html"
    
    righe_bolla = [p[target_list][i] for i in bolla.get("indici_righe", []) if 0 <= i < len(p[target_list])]
    
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

    url = url_for("stampa_bolla_html", quote_id=quote_id, bolla_id=bolla_id, _external=True)
    browser_exe = next((exe for exe in [shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome")] if exe), None)

    ok = False
    # --- TENTATIVO BROWSER ---
    if browser_exe:
        try:
            cmd = [browser_exe, "--headless=new", "--disable-gpu", f"--print-to-pdf={out_path}", url]
            subprocess.run(cmd, check=True, timeout=60, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            ok = out_path.exists() and out_path.stat().st_size > 1000 
            if ok: log_pdf_event(log_id, "SUCCESSO", f"PDF generato con browser. Size: {out_path.stat().st_size}")
        except Exception as e:
            log_pdf_event(log_id, "ERRORE", f"Errore browser: {e}")

    # --- TENTATIVO WEASYPRINT ---
    if not ok:
        try:
            from weasyprint import HTML
            html_string = render_template(template_name, p=p, bolla=bolla, righe_bolla=righe_bolla, indirizzo_consegna=indirizzo_consegna)
            HTML(string=html_string, base_url=request.url_root).write_pdf(out_path)
            ok = out_path.exists() and out_path.stat().st_size > 1000
            if ok: log_pdf_event(log_id, "SUCCESSO", f"PDF generato con WeasyPrint.")
        except Exception as e:
            log_pdf_event(log_id, "ERRORE", f"Errore WeasyPrint: {e}")

    if not ok:
        log_pdf_event(log_id, "FALLIMENTO", "Generazione fallita.")
        return jsonify({"error": "Impossibile generare il PDF."}), 500

    # === AGGIORNAMENTO DI STATO SULLA LISTA CORRETTA ===
    made_changes = False
    is_edile = p.get("tipo_preventivo") == "edile"
    if is_edile:
        for idx_assoluto in bolla.get("indici_righe", []):
            curr_idx = 0
            for sezione in p.get("sezioni_edili", []):
                for riga in sezione.get("righe", []):
                    if curr_idx == idx_assoluto:
                        riga["stato_consegna"] = "In Bolla"
                        riga["bolla_id"] = bolla_id
                        made_changes = True
                    curr_idx += 1
    else:
        for index in bolla.get("indici_righe", []):
            if 0 <= index < len(p[target_list]):
                p[target_list][index]["stato_consegna"] = "In Bolla"
                p[target_list][index]["bolla_id"] = bolla_id
                made_changes = True

    if made_changes:
        aggiorna_stato_consegna_globale(p)
        aggiorna_stato_avanzamento(p)
        save_quote(quote_id, p)
        log_pdf_event(log_id, "INFO", f"Stato righe {target_list} aggiornato.")

    pdf_url = url_for("pdf_inline", filename=pdf_name)
    return jsonify({"pdf_url": pdf_url})

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
    target_list = "righe_edili" if is_edile else "righe"
    template_name = "stampa_consegna_lavori.html" if is_edile else "stampa_bolla.html"

    righe_bolla = [p[target_list][i] for i in bolla.get("indici_righe", []) if 0 <= i < len(p[target_list])]

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
    return render_template("loading.html", quote_id=quote_id)
def get_new_revisione_id(preventivo_data):
    """Calcola il prossimo numero di revisione per un preventivo."""
    if "storico_pdf" not in preventivo_data or not preventivo_data["storico_pdf"]:
        return 1
    return len(preventivo_data["storico_pdf"]) + 1

@app.route("/generate-pdf-task/<quote_id>")
@login_or_local_required
def generate_pdf_task(quote_id):
    import subprocess, shutil 
    log_pdf_event(quote_id, "INFO", "Inizio generazione PDF preventivo.") 

    p = load_quote(quote_id)
    if not p:
        log_pdf_event(quote_id, "ERRORE", "Preventivo non trovato.") 
        return jsonify({"error": "Preventivo non trovato"}), 404

    if p.get("stato") == "Bozza":
        log_pdf_event(quote_id, "ERRORE", "Tentativo di generare PDF per preventivo in Bozza.") 
        return jsonify({"error": "Non è possibile generare un PDF per un preventivo in stato di Bozza."}), 400

    # Scelta del Template (Aggiornato per supportare Edile)
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

    url = url_for(html_endpoint, quote_id=quote_id, _external=True) 
    browser_exe = next((exe for exe in [shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome")] if exe), None)

    ok = False
    
    # --- 1. TENTATIVO CON BROWSER ---
    if browser_exe:
        log_pdf_event(quote_id, "INFO", f"Trovato browser: {browser_exe}. Tentativo con metodo Headless.") 
        try:
            cmd = [browser_exe, "--headless=new", "--disable-gpu", f"--print-to-pdf={out_path}", url]
            log_pdf_event(quote_id, "DEBUG", f"Comando browser: {' '.join(cmd)}") 
            result = subprocess.run(cmd, check=True, timeout=60, capture_output=True, text=True, encoding='utf-8', errors='ignore') 
            
            # --- CONTROLLO RIGOROSO (Novità) ---
            # Il file deve esistere ed essere più grande di 1KB (1000 byte)
            ok = out_path.exists() and out_path.stat().st_size > 1000 
            
            if ok:
                 log_pdf_event(quote_id, "SUCCESSO", f"PDF generato con browser. Dimensione: {out_path.stat().st_size} bytes.") 
            else:
                 log_pdf_event(quote_id, "ERRORE", f"Browser ha finito ma file troppo piccolo o assente.") 
        except subprocess.TimeoutExpired:
             log_pdf_event(quote_id, "ERRORE", "Timeout durante la generazione PDF con browser.") 
        except Exception as e:
            log_pdf_event(quote_id, "ERRORE", f"Errore durante l'esecuzione del browser: {e}") 

    # --- 2. TENTATIVO CON WEASYPRINT (Fallback) ---
    if not ok:
        log_pdf_event(quote_id, "INFO", "Metodo browser fallito o non disponibile. Tentativo con WeasyPrint.") 
        try:
            from weasyprint import HTML
            html_string = render_template(html_template_file, p=p) 
            HTML(string=html_string, base_url=request.url_root).write_pdf(out_path)
            
            # Anche qui controllo rigoroso
            ok = out_path.exists() and out_path.stat().st_size > 1000
            
            if ok:
                log_pdf_event(quote_id, "SUCCESSO", f"PDF generato con WeasyPrint.") 
            else:
                 log_pdf_event(quote_id, "ERRORE", "WeasyPrint ha fallito (file troppo piccolo).")
        except Exception as e:
            log_pdf_event(quote_id, "ERRORE", f"Errore generico WeasyPrint: {e}") 

    # --- 3. ESITO FINALE ---
    if not ok:
        log_pdf_event(quote_id, "FALLIMENTO", "Tutti i metodi hanno fallito. Nessuna revisione salvata.") 
        return jsonify({"error": "Impossibile generare il PDF."}), 500

    # Se arriviamo qui, il PDF esiste ed è valido. 
    # SOLO ORA salviamo la revisione nel JSON.
    log_pdf_event(quote_id, "INFO", f"PDF valido. Aggiornamento JSON preventivo con REV-{rev_num}.") 
    
    if "storico_pdf" not in p: p["storico_pdf"] = []
    p["storico_pdf"].append({
        "id": f"REV-{rev_num}",
        "data": datetime.date.today().strftime('%Y-%m-%d'),
        "filename": pdf_name,
        "totale": p.get("totale", "0,00")
    })
    p["pdf_attivo"] = pdf_name
    save_quote(quote_id, p)

    pdf_url = url_for("pdf_inline", filename=pdf_name)
    log_pdf_event(quote_id, "COMPLETATO", f"Processo terminato. URL PDF: {pdf_url}") 
    return jsonify({"pdf_url": pdf_url})

@app.route("/loading-static")
def loading_static(): return render_template("loading_static.html")
@app.route("/pdf/<path:filename>")
def pdf_inline(filename): 
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
    
    print(SERVER_ADDRESS_INFO)
    is_debug_mode = "--debug" in sys.argv
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

def setup_and_run_tray_icon():
    """Crea e avvia l'icona nella system tray."""
    try:
        image = Image.open(resource_path("static/favicon.ico"))
    except FileNotFoundError:
        print("ERRORE: file 'static/favicon.ico' non trovato!")
        return
    menu = (item('Apri Gestionale', open_app, default=True), item('Esci', quit_app))
    icon = pystray.Icon("Gestionale", image, SERVER_ADDRESS_INFO, menu)
    icon.run()
def load_messages():
    if not MESSAGES_FILE.exists(): return []
    try:
        with MESSAGES_FILE.open("r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_messages(msgs):
    with MESSAGES_FILE.open("w", encoding="utf-8") as f: json.dump(msgs, f, indent=2)

@app.route("/api/messages/users")
@login_required
def api_get_chat_users():
    all_users = load_users()
    me = session["user_id"]
    msgs = load_messages()
    
    users_with_stats = []
    for u in all_users:
        if u["username"] == me or u["role"] == 'amministratore': continue
        
        # 1. Conta non letti verso di me
        unread = sum(1 for m in msgs if m["from"] == u["username"] and m["to"] == me and not m.get("read", False))
        
        # 2. Trova il timestamp dell'ultimo messaggio (inviato o ricevuto)
        user_msgs = [m for m in msgs if (m["from"] == u["username"] and m["to"] == me) or (m["from"] == me and m["to"] == u["username"])]
        last_ts = "0000-00-00 00:00:00"
        if user_msgs:
            last_ts = max(m["timestamp"] for m in user_msgs)
        
        users_with_stats.append({
            "username": u["username"],
            "full_name": u["full_name"],
            "role": u["role"],
            "unread_count": unread,
            "last_message_timestamp": last_ts
        })
    
    # 3. Ordinamento: Prima chi ha messaggi non letti (desc), poi per data ultimo messaggio (desc)
    users_with_stats.sort(key=lambda x: (x["unread_count"] > 0, x["last_message_timestamp"]), reverse=True)
        
    return jsonify(users_with_stats)

@app.route("/api/messages/history/<other_user>")
@login_required
def api_get_chat_history(other_user):
    me = session["user_id"]
    msgs = load_messages()
    
    # Marcatura come letti: se il messaggio è per me ed è dell'utente che sto aprendo
    changed = False
    for m in msgs:
        if m["to"] == me and m["from"] == other_user and not m.get("read"):
            m["read"] = True
            changed = True
    
    if changed:
        save_messages(msgs)

    # Filtra messaggi tra ME e l'ALTRO UTENTE
    history = [m for m in msgs if (m["from"] == me and m["to"] == other_user) or (m["from"] == other_user and m["to"] == me)]
    return jsonify(history)

@app.route("/api/messages/send", methods=["POST"])
@login_required
def api_send_message():
    text = request.form.get("text", "")
    to_user = request.form.get("to", "")
    file = request.files.get("file")
    
    if not text and not file:
        return jsonify({"success": False, "error": "Messaggio vuoto"}), 400
    
    filename = None
    if file and file.filename != '':
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        file.save(CHAT_ATTACHMENTS_DIR / filename)

    msgs = load_messages()
    nuovo_msg = {
        "from": session["user_id"],
        "from_name": session["user_name"],
        "to": to_user,
        "text": text,
        "attachment": filename,
        "original_filename": file.filename if file else None,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "read": False
    }
    msgs.append(nuovo_msg)
    save_messages(msgs)
    return jsonify({"success": True, "msg": nuovo_msg})

@app.route("/api/messages/unread_total")
@login_required
def api_unread_total():
    me = session["user_id"]
    msgs = load_messages()
    count = sum(1 for m in msgs if m["to"] == me and not m.get("read", False))
    return jsonify({"unread_count": count})

def load_tagbox():
    if not TAGBOX_FILE.exists(): return []
    try:
        with TAGBOX_FILE.open("r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_tagbox(shouts):
    with TAGBOX_FILE.open("w", encoding="utf-8") as f: json.dump(shouts, f, indent=2)

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
    if not TASKS_FILE.exists(): return []
    try:
        with TASKS_FILE.open("r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_tasks(tasks):
    with TASKS_FILE.open("w", encoding="utf-8") as f: json.dump(tasks, f, indent=2)

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

        target_file = TASKS_FILE
        
        # Caricamento task dal file corretto
        tasks = []
        if target_file.exists():
            with target_file.open("r", encoding="utf-8") as f:
                tasks = json.load(f)

        task_id = str(uuid.uuid4())[:8].upper()
        mentions = re.findall(r"@(\w+)", desc)
        
        new_task = {
            "id": task_id,
            "created_by": session["user_id"],
            "created_by_name": session["user_name"],
            "description": desc,
            "assigned_to": [f"@{m}" for m in mentions] if mentions else ["@tutti"],
            "status": "open",
            "timestamp": datetime.datetime.now().strftime("%d/%m %H:%M"),
            "comments": []
        }
        tasks.insert(0, new_task)
        
        with target_file.open("w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)

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
        try:
            with ADMIN_TASKS_FILE.open("r", encoding="utf-8") as f:
                tasks = json.load(f)
        except:
            tasks = []

    new_support_request = {
        "id": f"SOS-{uuid.uuid4().hex[:6].upper()}",
        "user_id": session["user_id"],
        "user_name": session["user_name"],
        "description": desc,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "LOGGED_ONLY"
    }
    tasks.insert(0, new_support_request)
    
    with ADMIN_TASKS_FILE.open("w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)

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
    if not NOTIFICATIONS_FILE.exists(): return []
    try:
        with NOTIFICATIONS_FILE.open("r", encoding="utf-8") as f: return json.load(f)
    except: return []

def save_notifications(notifs):
    with NOTIFICATIONS_FILE.open("w", encoding="utf-8") as f: json.dump(notifs, f, indent=2)

def add_notification(user_id, text, link="/tasks"):
    notifs = load_notifications()
    notifs.insert(0, {
        "id": uuid.uuid4().hex[:6],
        "user_id": user_id,
        "text": text,
        "link": link,
        "timestamp": datetime.datetime.now().strftime("%d/%m %H:%M"),
        "read": False
    })
    save_notifications(notifs[:100]) # Teniamo le ultime 100

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
    my_n = [n for n in all_n if n["user_id"] == session["user_id"]]
    unread = sum(1 for n in my_n if not n["read"])
    return jsonify({"notifications": my_n[:20], "unread_count": unread})

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def mark_notifications_read():
    all_n = load_notifications()
    for n in all_n:
        if n["user_id"] == session["user_id"]:
            n["read"] = True
    save_notifications(all_n)
    return jsonify({"success": True})    


if __name__ == "__main__":
    # --- MODALITÀ DEBUG ---
    if "--debug" in sys.argv:
        print(">>> AVVIATO IN MODALITÀ DEBUG DIRETTA")

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