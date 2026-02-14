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


APP_VERSION = "1.10.3"  

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
PDF_LOG_FILE = DATA_DIR / "pdf_generation.log"

# Creiamo le sottocartelle se non esistono
DATA_DIR.mkdir(parents=True, exist_ok=True)
CLIENTS_DIR.mkdir(exist_ok=True)
QUOTES_DIR.mkdir(exist_ok=True)
ALLEGATI_DIR.mkdir(exist_ok=True)

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
    for quote_file in QUOTES_DIR.glob("P*.json"):
        try:
            with quote_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                # Filtro per venditore basato su FULLNAME
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
    Ricalcola lo stato di consegna globale basandosi sullo stato delle sole righe
    incluse in ordini fornitore CONFERMATI.
    """
    stato_preventivo = preventivo_data.get("stato")
    
    # 1. Trova tutti gli indici confermati
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
    """
    def safe_money(val):
        """ Helper interno per leggere qualsiasi formato moneta """
        if not val: return 0.0
        s = str(val).strip()
        # Formato Italiano (es. 1.250,50) -> Ha la virgola
        if ',' in s:
            s = s.replace('.', '').replace(',', '.')
        # Altrimenti è formato standard (1250.50)
        try:
            return float(s)
        except ValueError:
            return 0.0

    # 1. Determina il "Totale Dovuto" (Target)
    if p.get("no_iva") is True:
        # SE ESENTE IVA: Il cliente deve pagare solo l'imponibile!
        # Usiamo tot_imponibile_cliente se esiste, altrimenti fallback su totale
        totale_dovuto = safe_money(p.get("tot_imponibile_cliente", p.get("totale", "0")))
    else:
        # CASO NORMALE: Il cliente paga il totale (inclusa IVA)
        totale_dovuto = safe_money(p.get("totale", "0"))
    
    # 2. Somma i pagamenti effettuati
    totale_pagato = 0.0
    for pay in p.get("pagamenti", []):
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
EMPTY_STATE = {"venditore": "", "numero": "", "data": "", "cliente": "", "regione": "", "regione_nome": "","indirizzo": "", "email": "", "telefono": "", "referente": "", "fee_pct": "", "iva_pct": "22 %","no_iva": False,"totale": "", "comune": "", "provincia": "", "rag_sociale": "", "p_iva": "", "cap": "", "righe": [], "stato": "Bozza", "is_locked": False,
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
            
            # --- LOGICA CORRETTA: Controlla se ci sono novità reali nel JSON ---
            last_seen_version = user_found.get("last_seen_version", "0.0")
            nuove_voci = [entry for entry in CHANGELOG_DATA if parse_version(entry['version']) > parse_version(last_seen_version)]

            if nuove_voci:
                # Se ci sono voci nel JSON che l'utente non ha visto, vai al changelog
                return redirect(url_for("changelog"))
            else:
                # Altrimenti, vai direttamente alla dashboard
                return redirect(url_for("dashboard"))
        else:
            flash("Credenziali non valide. Riprova.", "error")

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
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Non loggato'}), 401
    
    installed_ver = get_installed_version()
    users = load_users()
    updated = False
    
    for u in users:
        if u['username'] == session['user']:
            u['last_seen_version'] = installed_ver
            updated = True
            break
    
    if updated:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=4)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Utente non trovato'})

@app.route("/changelog")
@login_required
def changelog():
    """Mostra la pagina con le novità non ancora viste dall'utente."""
    users = load_users()
    user = next((u for u in users if u["username"] == session["user_id"]), None)
    if not user:
        return redirect(url_for("logout"))

    last_seen_version = user.get("last_seen_version", "0.0")

    # Filtra solo le novità effettive
    updates_to_show = [
        entry for entry in CHANGELOG_DATA
        if parse_version(entry['version']) > parse_version(last_seen_version)
    ]
    updates_to_show.sort(key=lambda x: parse_version(x['version']), reverse=True)

    # Se per qualche motivo l'utente arriva qui ma non ci sono novità, lo mandiamo alla dashboard
    if not updates_to_show:
        return redirect(url_for("dashboard"))
        
    return render_template("changelog.html", title="Novità", changelog_updates=updates_to_show)

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
    if 'user' in session:
        users = load_users()
        user_data = next((u for u in users if u['username'] == session['user']), None)
        installed_ver = get_installed_version()
        
        # Verifica usando la chiave last_seen_version
        if user_data and user_data.get('last_seen_version') != installed_ver:
            return redirect(url_for('show_changelog'))

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

@app.route("/preventivi-cliente")
@login_required
def dashboard_clienti():
    """Pagina che raggruppa i preventivi aperti per cliente."""

    tutti_i_preventivi = get_all_quotes()
    clienti_preventivi = {}
    today = datetime.date.today()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p:
            continue

        # Se l'utente è segreteria, salta anche le bozze
        if session.get("user_role") == 'segreteria' and p.get("stato") == "Bozza":
            continue
        
        is_attivo = p.get("stato") not in ["Chiuso", "Annullato"]
        if not is_attivo:
            continue
        
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

@app.route("/preventivo/<quote_id>/allega", methods=["POST"])
@login_required
def allega_documento(quote_id):
    """Gestisce l'upload di un nuovo allegato per un preventivo."""
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(request.referrer or url_for('dashboard'))

    if 'file' not in request.files:
        flash("Nessun file selezionato.", "error")
        return redirect(request.referrer)

    file = request.files['file']
    descrizione = request.form.get("descrizione", "Nessuna descrizione")

    if file.filename == '':
        flash("Nessun file selezionato.", "error")
        return redirect(request.referrer)

    if file:
        # Crea la cartella specifica per questo preventivo, se non esiste
        quote_allegati_dir = ALLEGATI_DIR / quote_id
        quote_allegati_dir.mkdir(exist_ok=True)
        
        filename = secure_filename(file.filename)
        file.save(quote_allegati_dir / filename)

        # Aggiungi il riferimento al file nel JSON del preventivo
        if "allegati" not in p:
            p["allegati"] = []
        
        p["allegati"].append({
            "filename": filename,
            "descrizione": descrizione,
            "data_upload": datetime.date.today().strftime('%Y-%m-%d')
        })
        save_quote(quote_id, p)
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

@app.route("/cliente/cerca", methods=["GET", "POST"])
@login_required
def cerca_cliente():
    if request.method == "POST":
        search_term = request.form.get("search_term", "")
        
        # 1. RECUPERA 'action' DAL FORM INVIATO
        action = request.form.get('action', 'open_archive')
        
        clients = find_clients_by_term(search_term)

        # 2. PASSA 'action' AL TEMPLATE
        return render_template(
            "risultati_ricerca_cliente.html", 
            title="Risultati Ricerca", 
            clients=clients, 
            search_term=search_term,
            action=action  # <-- Aggiungi questo!
        )
        
    # La parte GET per mostrare il form di ricerca rimane invariata
    return render_template("cerca_cliente.html", title="Cerca Cliente")
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
    if request.method == "POST":
        new_client_id = get_new_client_id()
        client_data = { "id_cliente": new_client_id }
        form_keys = ["cliente", "rag_sociale", "p_iva", "indirizzo", "cap", "comune", "provincia", "regione", "regione_nome", "email", "telefono", "codice_univoco"]
        for key in form_keys: client_data[key] = request.form.get(key, "")
        save_client(new_client_id, client_data)
        flash("Nuovo cliente creato con successo.")
        return redirect(url_for("nuovo_preventivo", client_id=new_client_id))
    return render_template("crea_cliente.html", title="Crea Nuovo Cliente", geo_data=GEO_DATA)
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
    Crea una copia esatta di un preventivo esistente, ma lo imposta
    come una nuova bozza pronta per essere modificata.
    """
    # 1. Carica il preventivo originale
    p_originale = load_quote(quote_id)
    if not p_originale:
        flash("Preventivo originale non trovato.", "error")
        return redirect(url_for("dashboard"))

    # 2. Crea una copia profonda per non modificare l'originale
    p_clonato = copy.deepcopy(p_originale)

    # 3. Genera un nuovo ID e aggiorna i dati chiave
    venditore_sigla = session.get("user_sigla", "XX")
    nuovo_id = get_new_quote_id(venditore_sigla)
    
    p_clonato["numero"] = nuovo_id
    p_clonato["data"] = datetime.date.today().strftime('%Y-%m-%d')
    
    # 4. Resetta lo stato a "Bozza" e rimuovi la cronologia
    p_clonato["stato"] = "Bozza"
    p_clonato["is_locked"] = False
    
    # Rimuove dati specifici della "vita" del vecchio preventivo
    p_clonato.pop("pdf_attivo", None)
    p_clonato.pop("storico_pdf", None)
    p_clonato.pop("pagamenti", None)
    p_clonato.pop("bolle", None)
    p_clonato.pop("fatture_allegate", None)
    p_clonato.pop("ordini_fornitore", None) # Rimuoviamo anche gli ordini
    
    # Resetta lo stato di consegna di ogni riga
    for riga in p_clonato.get("righe", []):
        riga.pop("stato_consegna", None)
        riga.pop("bolla_id", None)
        riga.pop("data_consegna", None)
        riga.pop("data_arrivo_in_house", None)
    
    # Ricalcola gli stati globali per pulizia
    aggiorna_stato_consegna_globale(p_clonato)
    aggiorna_stato_pagamento_globale(p_clonato)

    # 5. Salva il nuovo preventivo
    save_quote(nuovo_id, p_clonato)

    # 6. Restituisci i dati in formato JSON
    return jsonify({
        "success": True, 
        "vecchio_id": quote_id, 
        "nuovo_id": nuovo_id,
        "new_url": url_for('editor_preventivo', quote_id=nuovo_id)
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

    # --- BLOCCO AGGIUNTO ---
    # Aggiorniamo lo stato di pagamento, che passerà
    # da "N/D" a "Da Saldare"
    aggiorna_stato_pagamento_globale(p)
    # --- FINE BLOCCO ---

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
        
        try: p_date = datetime.datetime.strptime(p.get("data"), "%Y-%m-%d").date()
        except: continue

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

                d_str = p.get("data")
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

                # A. PAGAMENTI GIÀ INCASSATI
                if start_date <= d_pag <= end_date and d_pag <= today:
                    cashflow["incassato_netto"] += val_netto
                    cashflow["fee_versata"] += fee_su_incasso
                    if not is_no_iva: cashflow["iva_preventivi"] += quota_iva

                # B. PAGAMENTI FUTURI
                if d_pag > today:
                    cashflow["in_attesa_netto"] += val_netto
                    future_payments.append({
                        "data": d_pag, "cliente": p.get("cliente"), "preventivo": p.get("numero"),
                        "importo_netto": val_netto, "note": pag.get("note", "")
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
                    # Fallback alla data preventivo se non c'è altra data
                    try: d_trans = datetime.datetime.strptime(p.get("data"), "%Y-%m-%d").date()
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
             if not d_trans: d_trans = _str_to_date(p.get("data")) # Fallback
             
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
        for ordine in p.get("ordini_fornitore", []):
            d_transazione = None
            if ordine.get("allegati"): 
                try: d_transazione = datetime.datetime.strptime(ordine["allegati"][0]["data_upload"], "%Y-%m-%d").date()
                except: pass
            if not d_transazione and ordine.get("data_arrivo"):
                try: d_transazione = datetime.datetime.strptime(ordine.get("data_arrivo"), "%Y-%m-%d").date()
                except: pass
            if not d_transazione:
                try: d_transazione = datetime.datetime.strptime(p.get("data"), "%Y-%m-%d").date()
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

        try:
            p_date = datetime.datetime.strptime(p.get("data"), "%Y-%m-%d").date()
        except:
            continue
            
        if start_date <= p_date <= end_date:
            
            # --- CALCOLI ---
            somma_importi_ordini = 0.0
            somma_iva_ordini = 0.0
            for ordine in p.get("ordini_fornitore", []):
                imp = _to_float(ordine.get("importo", 0))
                iva = _to_float(ordine.get("iva_ordine", 0)) 
                somma_importi_ordini += imp
                somma_iva_ordini += iva

            costo_negozio_totale = 0.0
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
                "Data": p.get("data"),
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

        # Cash Flow (incassi)
        for pag in p.get("pagamenti", []):
            if pag.get("rectifies_id"): continue
            imp_pag = _to_num(pag.get("importo"))
            if imp_pag <= 0: continue
            try:
                d_pag = datetime.datetime.strptime(pag.get("data"), '%Y-%m-%d').date()
                if d_pag <= today: analisi['incassato'] += imp_pag
                else: analisi['da_incassare'] += imp_pag
            except: pass

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
@app.route("/consegne")
@login_required
def dashboard_consegne():
    """Pagina che elenca i preventivi con ordini confermati da consegnare."""
    preventivi_da_consegnare = []
    
    tutti_i_preventivi = get_all_quotes()

    for prev_summary in tutti_i_preventivi:
        p = load_quote(prev_summary["numero"])
        if not p: continue

        ordini_confermati = [o for o in p.get("ordini_fornitore", []) if o.get("numero_conferma", "").strip()]
        if not ordini_confermati: continue

        indici_confermati = set()
        for o in ordini_confermati:
            indici_confermati.update(o.get("indici_righe", []))

        if not indici_confermati: continue

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
    """Pagina per gestire la consegna di un singolo preventivo."""
    p = load_quote(quote_id)
    if not p:
        flash("Preventivo non trovato.")
        return redirect(url_for("dashboard_consegne"))

    ordini_confermati = [o for o in p.get("ordini_fornitore", []) if o.get("numero_conferma", "").strip()]
    
    for ordine in ordini_confermati:
        items_in_ordine = []
        for item_index in ordine.get("indici_righe", []):
            if 0 <= item_index < len(p["righe"]):
                riga = p["righe"][item_index]
                riga["original_index"] = item_index
                items_in_ordine.append(riga)
        ordine["articoli"] = items_in_ordine

    # --- NUOVA LOGICA DI ORDINAMENTO ---
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
@app.route("/consegna/<quote_id>/marca-pronto", methods=["POST"])
@login_required
def marca_pronto(quote_id):
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici_da_marcare = [int(i) for i in request.form.getlist("selected_items[]")]
    if not indici_da_marcare:
        return jsonify({"success": False, "error": "Nessun articolo selezionato"})

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    for index in indici_da_marcare:
        if 0 <= index < len(p["righe"]):
            p["righe"][index]["stato_consegna"] = "Pronto per Consegna"
            p["righe"][index]["data_arrivo_in_house"] = today_str # <-- AGGIUNTO

    save_quote(quote_id, p)
    return jsonify({"success": True})

@app.route("/consegna/<quote_id>/marca-consegnato", methods=["POST"])
@login_required
def marca_consegnato(quote_id):
    allowed_roles = ['segreteria', 'amministratore', 'ceo']
    if session.get("user_role") not in allowed_roles:
        return jsonify({"success": False, "error": "Non disponi delle autorizzazioni per eseguire questa azione."})
    p = load_quote(quote_id)
    if not p: return jsonify({"success": False, "error": "Preventivo non trovato"})

    indici_da_marcare = [int(i) for i in request.form.getlist("selected_items[]")]
    if not indici_da_marcare:
        return jsonify({"success": False, "error": "Nessun articolo selezionato"})

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    for index in indici_da_marcare:
        if 0 <= index < len(p["righe"]):
            p["righe"][index]["stato_consegna"] = "Consegnato"
            p["righe"][index]["data_consegna"] = today_str # <-- AGGIUNTO

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

    if not item_indices or not target_status:
        return jsonify({"success": False, "error": "Dati mancanti per l'operazione."})

    for index in item_indices:
        if 0 <= index < len(p["righe"]):
            riga = p["righe"][index]
            original_bolla_id = riga.get("bolla_id")

            # 1. Aggiorna lo stato e resetta le date successive
            riga["stato_consegna"] = target_status
            riga.pop("data_consegna", None) # Rimuovi la data di consegna in ogni caso

            if target_status == "Da Consegnare":
                riga.pop("data_arrivo_in_house", None) # Rimuovi anche la data di arrivo

            # 2. Gestisci il collegamento con la bolla
            if original_bolla_id and not keep_bolla:
                riga.pop("bolla_id", None)
                # Rimuovi l'articolo anche dalla bolla stessa
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
@login_required
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
        
        # 1. Calcolo Pagamenti Fisici
        for pag in pagamenti:
            importo_float = _str_to_float(pag.get("importo"))
            try:
                payment_date = datetime.datetime.strptime(pag.get("data"), '%Y-%m-%d').date()
            except: payment_date = today 

            if payment_date > today and importo_float > 0:
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
        is_future = False

        try:
            payment_date = datetime.datetime.strptime(new_pag.get("data"), '%Y-%m-%d').date()
            if payment_date > today and importo_float > 0:
                is_future = True
                totale_da_incassare += importo_float
            else:
                totale_pagato_effettivo += importo_float
        except:
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
        "note": nota_finale
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

@app.route("/export-bolla-pdf/<quote_id>/<bolla_id>")
@login_required
def export_bolla_pdf(quote_id, bolla_id):
    """Pagina di attesa per la generazione del PDF della bolla."""
    return render_template("loading_bolla.html", quote_id=quote_id, bolla_id=bolla_id)

@app.route("/generate-bolla-task/<quote_id>/<bolla_id>")
@login_required
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

    righe_bolla = [p["righe"][i] for i in bolla.get("indici_righe", []) if 0 <= i < len(p["righe"])]
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
    log_pdf_event(log_id, "INFO", f"Percorso output PDF: {out_path}")

    url = url_for("stampa_bolla_html", quote_id=quote_id, bolla_id=bolla_id, _external=True)
    browser_exe = next((exe for exe in [shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome")] if exe), None)

    ok = False
    
    # --- TENTATIVO BROWSER ---
    if browser_exe:
        try:
            cmd = [browser_exe, "--headless=new", "--disable-gpu", f"--print-to-pdf={out_path}", url]
            subprocess.run(cmd, check=True, timeout=60, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            # Controllo rigoroso: il file deve esistere ed essere > 1KB
            ok = out_path.exists() and out_path.stat().st_size > 1000 
            if ok:
                 log_pdf_event(log_id, "SUCCESSO", f"PDF generato con browser. Size: {out_path.stat().st_size}")
        except Exception as e:
            log_pdf_event(log_id, "ERRORE", f"Errore browser: {e}")

    # --- TENTATIVO WEASYPRINT ---
    if not ok:
        try:
            from weasyprint import HTML
            html_string = render_template("stampa_bolla.html", p=p, bolla=bolla, righe_bolla=righe_bolla, indirizzo_consegna=indirizzo_consegna)
            HTML(string=html_string, base_url=request.url_root).write_pdf(out_path)
            ok = out_path.exists() and out_path.stat().st_size > 1000
            if ok:
                log_pdf_event(log_id, "SUCCESSO", f"PDF generato con WeasyPrint.")
        except Exception as e:
            log_pdf_event(log_id, "ERRORE", f"Errore WeasyPrint: {e}")

    if not ok:
        log_pdf_event(log_id, "FALLIMENTO", "Generazione fallita.")
        return jsonify({"error": "Impossibile generare il PDF della bolla."}), 500

    # === PUNTO CRUCIALE: AGGIORNAMENTO DI STATO ===
    # Aggiorniamo lo stato delle righe SOLO ORA che siamo sicuri che il PDF esiste
    made_changes = False
    for index in bolla.get("indici_righe", []):
        if 0 <= index < len(p["righe"]):
            # Imposta lo stato e collega l'ID bolla
            p["righe"][index]["stato_consegna"] = "In Bolla"
            p["righe"][index]["bolla_id"] = bolla_id
            made_changes = True

    if made_changes:
        # Aggiorniamo anche gli stati globali per riflettere il cambiamento
        aggiorna_stato_consegna_globale(p)
        aggiorna_stato_avanzamento(p)
        save_quote(quote_id, p)
        log_pdf_event(log_id, "INFO", "Stato righe aggiornato a 'In Bolla'.")

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
    # --- BLOCCO DI MIGRAZIONE DA AGGIUNGERE ---
    if p and migra_vecchie_fatture_a_iva(p):
        save_quote(quote_id, p)
        print(f"MIGRAZIONE: Dati fattura migrati per {quote_id}")
    # --- FINE BLOCCO MIGRAZIONE ---
    if not p:
        flash("Preventivo non trovato.", "error")
        return redirect(url_for("dashboard_fatture"))
    
    stati_validi = ["Confermato", "In Lavorazione", "Chiuso"]
    if p.get("stato") not in stati_validi:
        flash("Questo preventivo non è ancora stato confermato.", "warning")
        return redirect(url_for("dashboard_fatture"))
        
    # --- NUOVA LOGICA DI RAGGRUPPAMENTO ---
    dati_fattura = {}
    
    # Helper per convertire stringhe di prezzo in numeri
    def _clean_num(val_str):
        try:
            return float(str(val_str).replace("€", "").replace(".", "").replace(",", ".").strip())
        except (ValueError, TypeError):
            return 0.0

    # 1. Raggruppa le righe per aliquota IVA
    for riga in p.get("righe", []):
        if not riga.get("articolo"): continue
        
        # Pulisce la chiave IVA (es. "22 %" -> "22")
        iva_key = riga.get("iva_pct", "22 %").replace("%", "").strip()
        
        if iva_key not in dati_fattura:
            # Prepara il contenitore per questa aliquota IVA
            dati_fattura[iva_key] = {
                "righe": [],
                "imponibile_str": p.get("imponibili_iva", {}).get(iva_key, "0,00"),
                "iva_str": p.get("tot_iva_dettaglio", {}).get(iva_key, "0,00"),
                # Usa il NUOVO modello dati p.fatture_per_iva
                "fatture_allegate": p.get("fatture_per_iva", {}).get(iva_key, []),
                # Aggiungiamo il flag per lo stato specifico di questa aliquota
                "is_fatturato": p.get("stati_fattura_iva", {}).get(iva_key, False)
            }
        
        dati_fattura[iva_key]["righe"].append(riga)

    # 2. Calcola il totale per ogni gruppo
    for key, data in dati_fattura.items():
        imponibile = _clean_num(data["imponibile_str"])
        iva = _clean_num(data["iva_str"])
        data["totale"] = imponibile + iva

    # 3. Ordina i gruppi (es. 22% prima, poi 10%, ecc.)
    dati_fattura_ordinati = dict(sorted(dati_fattura.items(), key=lambda item: item[0], reverse=True))
    # --- FINE NUOVA LOGICA ---

    return render_template("editor_fattura.html", 
        title=f"Dettaglio Fattura da Preventivo {quote_id}",
        p=p,
        dati_fattura=dati_fattura_ordinati # Passiamo i dati raggruppati
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
@login_required
def stampa_bolla_html(quote_id, bolla_id):
    """Renderizza il template HTML per la stampa della bolla."""
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    
    bolla = next((b for b in p.get("bolle", []) if b.get("id") == bolla_id), None)
    if not bolla: return "Bolla non trovata", 404

    righe_bolla = [p["righe"][i] for i in bolla.get("indici_righe", []) if 0 <= i < len(p["righe"])]

    # Logica per trovare l'indirizzo di consegna corretto
    indirizzo_consegna = None
    indirizzo_id = bolla.get("indirizzo_cantiere_id")
    if indirizzo_id:
        client = load_client(p.get("id_cliente"))
        if client:
            indirizzo_consegna = next((addr for addr in client.get("indirizzi_cantiere", []) if addr.get("id") == indirizzo_id), None)

    return render_template("stampa_bolla.html", p=p, bolla=bolla, righe_bolla=righe_bolla, indirizzo_consegna=indirizzo_consegna)
@app.route("/stampa-html/<quote_id>")
@login_required
def stampa_html(quote_id):
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    return render_template("stampa.html", p=p)
@app.route("/stampa-semplice-html/<quote_id>")
@login_required
def stampa_semplice_html(quote_id):
    """Renderizza il template HTML per la stampa SEMPLICE (senza totali di riga)."""
    p = load_quote(quote_id)
    if not p: return "Preventivo non trovato", 404
    # Fai attenzione al nome del nuovo template che creeremo tra poco:
    return render_template("stampa_semplice.html", p=p)
@app.route("/export-pdf/<quote_id>")
@login_required
def export_pdf(quote_id):
    return render_template("loading.html", quote_id=quote_id)
def get_new_revisione_id(preventivo_data):
    """Calcola il prossimo numero di revisione per un preventivo."""
    if "storico_pdf" not in preventivo_data or not preventivo_data["storico_pdf"]:
        return 1
    return len(preventivo_data["storico_pdf"]) + 1

@app.route("/generate-pdf-task/<quote_id>")
@login_required
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

    # Scelta del Template
    template_choice = request.args.get('template', 'standard')
    if template_choice == 'semplice':
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

# --- Funzioni per l'icona e il Server ---
# NUOVA VERSIONE CON AUTO-RELOAD
def run_server():
    """Funzione che avvia il server web."""
    print(SERVER_ADDRESS_INFO)

    # Controlla se siamo in modalità debug (impostata all'avvio)
    is_debug_mode = "--debug" in sys.argv

    if is_debug_mode:
        print(">>> INFO: Server avviato in modalità DEBUG con auto-reload.")
        # Usa il server di sviluppo di Flask che ha l'auto-reloader
        app.run(host=HOST_BIND, port=PORT, debug=True)
    else:
        # Altrimenti, usa il server di produzione Waitress per la versione normale
        print(">>> INFO: Server avviato in modalità PRODUZIONE con Waitress.")
        serve(app, host=HOST_BIND, port=PORT)

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