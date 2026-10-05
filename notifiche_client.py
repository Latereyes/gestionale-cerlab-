"""Gestionale Notifiche — piccolo programma per i PC dell'ufficio.

Resta nell'area di notifica vicino all'orologio e mostra avvisi (con suono) quando:
- un collega ti scrive in chat: anteprima del messaggio e RISPOSTA RAPIDA senza aprire il gestionale;
- arriva una notifica del gestionale (task, menzioni...);
- i colleghi lavorano sul gestionale (pagamenti, bolle, conferme, PDF...).
Cliccando un avviso si apre la pagina giusta del gestionale.

Trova da solo il PC server sulla rete locale e si avvia con Windows. Al primo avvio chiede
utente e password del gestionale (una volta sola) per abilitare il PC.

Messaggi e notifiche personali seguono chi sta usando il gestionale da questo PC: se nell'arco
della giornata si alternano più colleghi, ciascuno riceve i propri. Quando il PC viene bloccato o
resta inattivo, o si esce dal gestionale, i messaggi personali si nascondono finché qualcuno non
torna a usare il gestionale.

Compilato da build.py come GestionaleNotifiche.exe e incluso nell'installer;
si scarica anche dal gestionale (pulsante "Notifiche su questo PC").
"""
import concurrent.futures
import ctypes
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

APP = "Gestionale Notifiche"
APP_VERSION = "3.0.0"    # aggiornata da build.py insieme a quella del gestionale
PORTA = 5001
INTERVALLO_SECS = 5
MINUTI_INATTIVITA = 30   # PC senza mouse/tastiera per tanto tempo: si nascondono i messaggi personali
SECS_BLOCCO = 60         # PC bloccato (Win+L) per almeno tanto: idem
CONFIG = Path(os.environ.get("APPDATA") or Path.home()) / "GestionaleNotifiche" / "config.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Dimensione degli avvisi scelta dal menu, moltiplicata alla scala calcolata dallo schermo
DIMENSIONI = [("Automatica", 1.0), ("Più piccoli", 0.85), ("Più grandi", 1.25), ("Molto grandi", 1.5)]

COLORI = {"chat": "#4f46e5", "notifica": "#d97706", "attivita": "#059669", "pdf": "#059669",
          "pdf_errore": "#dc2626", "sistema": "#64748b"}


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def http_json(url, data=None, token=None, timeout=5):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Widget-Token"] = token
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def versione_tupla(v):
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except Exception:
        return (0,)


def imposta_dpi_awareness():
    """Da chiamare PRIMA di creare Tk: altrimenti Windows disegna tutto a 96 DPI e su schermi
    ad alta risoluzione gli avvisi risultano minuscoli (o sfocati se ingranditi da Windows)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ip_locale():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def e_un_gestionale(base):
    try:
        return http_json(base + "api/attivita", timeout=1.5).get("app") == "Gestionale Cerlab"
    except Exception:
        return False


def cerca_server():
    """Cerca il PC server sulla rete locale (stessa sottorete, porta 5001)."""
    locale = f"http://127.0.0.1:{PORTA}/"
    if e_un_gestionale(locale):  # questo PC è il server
        return locale
    mio = ip_locale()
    if mio.count(".") != 3:
        return None
    prefisso = mio.rsplit(".", 1)[0]
    candidati = [f"http://{prefisso}.{n}:{PORTA}/" for n in range(1, 255)]
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=64)
    try:
        futuri = {ex.submit(e_un_gestionale, u): u for u in candidati}
        for f in concurrent.futures.as_completed(futuri):
            if f.result():
                return futuri[f]
        return None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)  # non aspetta gli indirizzi che non rispondono


def suono(tipo):
    try:
        import winsound
        alias = "SystemNotification" if tipo in ("chat", "notifica") else "SystemAsterisk"
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


def secondi_inattivita():
    """Da quanti secondi nessuno tocca mouse o tastiera di questo PC."""
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
    except Exception:
        return 0


def pc_bloccato():
    """True se è mostrata la schermata di blocco di Windows (il desktop non è accessibile)."""
    try:
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not h:
            return True
        user32.CloseDesktop(ctypes.c_void_p(h))
        return False
    except Exception:
        return False


def area_lavoro():
    """Area dello schermo senza la barra delle applicazioni (sinistra, alto, destra, basso)."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.l, r.t, r.r, r.b
    except Exception:
        return None


# =====================================================================================
# Interfaccia (avvisi a comparsa e finestra di accesso) — tutto nel thread di Tkinter
# =====================================================================================
class UI:
    LARGHEZZA = 370   # in pixel "a 100%": moltiplicata per la scala dello schermo
    MAX_AVVISI = 4

    def __init__(self, app):
        self.app = app
        self.coda = queue.Queue()
        self.avvisi = []
        self.pronta = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()
        self.pronta.wait(5)

    def esegui(self, fn, *args):
        """Chiamabile da qualsiasi thread: esegue fn nel thread dell'interfaccia."""
        self.coda.put((fn, args))

    def _loop(self):
        imposta_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.scala_schermo = self._calcola_scala()
        self.pronta.set()
        self._svuota_coda()
        self.root.mainloop()

    def _svuota_coda(self):
        try:
            while True:
                fn, args = self.coda.get_nowait()
                try:
                    fn(*args)
                except Exception as e:
                    print(f"Errore interfaccia: {e}")
        except queue.Empty:
            pass
        self.root.after(150, self._svuota_coda)

    # ---------- dimensioni adattive ----------
    def _calcola_scala(self):
        """Scala rispetto a uno schermo Full HD al 100%: segue il ridimensionamento di Windows (DPI)
        e, sugli schermi grandi lasciati al 100% (es. 1440p o 4K), anche la risoluzione."""
        try:
            dpi = self.root.winfo_fpixels("1i") / 96.0
        except Exception:
            dpi = 1.0
        dpi = max(dpi, 1.0)
        alto_logico = self.root.winfo_screenheight() / dpi
        extra = min(max(alto_logico / 1080.0, 1.0), 2.0)
        return dpi * extra

    @property
    def scala(self):
        return getattr(self, "scala_schermo", 1.0) * self.app.dimensione

    def px(self, n):
        return max(1, round(n * self.scala))

    def font(self, punti, famiglia="Segoe UI"):
        # dimensione negativa = pixel: così il testo segue la stessa scala di finestre e margini
        return (famiglia, -max(8, round(punti * 96 / 72 * self.scala)))

    # ---------- avvisi ----------
    def avviso(self, tipo, titolo, testo, link=None, rispondi_a=None, durata=12, di=None):
        """di = username a cui appartiene l'avviso (chat, notifiche): si chiude se al PC cambia utente."""
        if len(self.avvisi) >= self.MAX_AVVISI:
            self._chiudi(self.avvisi[0])
        colore = COLORI.get(tipo, "#4f46e5")
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg="#cbd5e1")
        corpo = tk.Frame(w, bg="#ffffff", padx=self.px(12), pady=self.px(10))
        corpo.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(corpo, bg=colore, height=self.px(3)).pack(fill="x", pady=(0, self.px(8)))

        testa = tk.Frame(corpo, bg="#ffffff")
        testa.pack(fill="x")
        etichette = {"chat": "💬 Messaggio", "notifica": "🔔 Notifica", "attivita": "Gestionale",
                     "pdf": "📄 PDF", "pdf_errore": "⚠️ PDF", "sistema": "Gestionale"}
        tk.Label(testa, text=etichette.get(tipo, "Gestionale") + " · " + time.strftime("%H:%M"), bg="#ffffff",
                 fg="#64748b", font=self.font(8)).pack(side="left")
        x = tk.Label(testa, text="✕", bg="#ffffff", fg="#94a3b8", font=self.font(10), cursor="hand2")
        x.pack(side="right")

        t = tk.Label(corpo, text=titolo, bg="#ffffff", fg="#0f172a", font=self.font(10, "Segoe UI Semibold"),
                     anchor="w", justify="left", wraplength=self.px(self.LARGHEZZA - 30))
        t.pack(fill="x", pady=(self.px(4), 0))
        testo = testo if len(testo) <= 260 else testo[:257] + "..."
        b = tk.Label(corpo, text=testo, bg="#ffffff", fg="#334155", font=self.font(9),
                     anchor="w", justify="left", wraplength=self.px(self.LARGHEZZA - 30))
        b.pack(fill="x", pady=(self.px(2), 0))

        stato = {"finestra": w, "timer": None, "durata": durata * 1000, "entry": None, "di": di}
        x.bind("<Button-1>", lambda e: self._chiudi(stato))

        def apri(_e=None):
            if link:
                self.app.apri(link)
            self._chiudi(stato)

        if link:
            for wid in (t, b):
                wid.configure(cursor="hand2")
                wid.bind("<Button-1>", apri)

        azioni = tk.Frame(corpo, bg="#ffffff")
        azioni.pack(fill="x", pady=(self.px(8), 0))
        if rispondi_a:
            entry = tk.Entry(azioni, font=self.font(10), relief="solid", bd=1)
            entry.pack(side="left", fill="x", expand=True, ipady=self.px(4))
            entry.insert(0, "")
            stato["entry"] = entry
            esito = tk.Label(corpo, text="", bg="#ffffff", fg="#059669", font=self.font(8), anchor="w")
            esito.pack(fill="x")

            def invia(_e=None):
                txt = entry.get().strip()
                if not txt:
                    return
                entry.configure(state="disabled")
                esito.configure(text="Invio...", fg="#64748b")

                def lavoro():
                    ok, err = self.app.rispondi(rispondi_a, txt, di)
                    self.esegui(fine, ok, err)

                def fine(ok, err):
                    if ok:
                        esito.configure(text="✓ Risposta inviata", fg="#059669")
                        w.after(1500, lambda: self._chiudi(stato))
                    else:
                        entry.configure(state="normal")
                        esito.configure(text="Non inviato: " + err, fg="#dc2626")

                threading.Thread(target=lavoro, daemon=True).start()

            entry.bind("<Return>", invia)
            tk.Button(azioni, text="Invia", command=invia, bg=colore, fg="#ffffff", relief="flat",
                      activebackground=colore, font=self.font(9, "Segoe UI Semibold"), padx=self.px(10), cursor="hand2").pack(side="left", padx=(self.px(6), 0))
            tk.Button(azioni, text="Apri chat", command=apri, relief="flat", bg="#f1f5f9",
                      font=self.font(9), padx=self.px(8), cursor="hand2").pack(side="left", padx=(self.px(6), 0))
            # le finestre senza bordo non prendono la tastiera da sole: la si dà al clic sulla casella
            entry.bind("<Button-1>", lambda e: (w.focus_force(), entry.focus_set()))
        elif link:
            tk.Button(azioni, text="Apri", command=apri, bg=colore, fg="#ffffff", relief="flat",
                      activebackground=colore, font=self.font(9, "Segoe UI Semibold"), padx=self.px(12), cursor="hand2").pack(side="right")

        # pausa del timer finché il mouse è sopra o si sta scrivendo una risposta
        def ferma(_e=None):
            if stato["timer"]:
                w.after_cancel(stato["timer"])
                stato["timer"] = None

        def riprendi(_e=None):
            if stato["entry"] is not None and stato["entry"].get().strip():
                return
            self._programma_chiusura(stato)

        w.bind("<Enter>", ferma)
        w.bind("<Leave>", riprendi)

        self.avvisi.append(stato)
        self._disponi()
        self._programma_chiusura(stato)
        if self.app.suono_attivo:
            suono(tipo)

    def chiudi_personali(self, tranne=None):
        """Chiude gli avvisi con messaggi e notifiche di un utente che non è più al PC."""
        for stato in [s for s in self.avvisi if s["di"] and s["di"] != tranne]:
            self._chiudi(stato)

    def _programma_chiusura(self, stato):
        w = stato["finestra"]
        if stato["timer"]:
            w.after_cancel(stato["timer"])
        stato["timer"] = w.after(stato["durata"], lambda: self._chiudi(stato))

    def _chiudi(self, stato):
        if stato in self.avvisi:
            self.avvisi.remove(stato)
        try:
            stato["finestra"].destroy()
        except Exception:
            pass
        self._disponi()

    def _disponi(self):
        area = area_lavoro()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        destra, basso = (area[2], area[3]) if area else (sw, sh - self.px(48))
        margine, larghezza = self.px(12), self.px(self.LARGHEZZA)
        y = basso - margine
        for stato in reversed(self.avvisi):
            w = stato["finestra"]
            w.update_idletasks()
            h = w.winfo_reqheight()
            y -= h
            w.geometry(f"{larghezza}x{h}+{destra - larghezza - margine}+{y}")
            y -= self.px(10)

    # ---------- finestra di accesso ----------
    def chiedi_accesso(self):
        if getattr(self, "_login_aperto", False):
            return
        self._login_aperto = True
        w = tk.Toplevel(self.root)
        w.title(APP + " - Accesso")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        try:
            w.iconbitmap(resource_path("favicon.ico"))
        except Exception:
            pass
        f = tk.Frame(w, padx=self.px(22), pady=self.px(18))
        f.pack()
        tk.Label(f, text="Accedi con il tuo utente del gestionale", font=self.font(11, "Segoe UI Semibold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(f, text="Serve una volta sola per abilitare questo PC. Poi qui arrivano i messaggi e le notifiche\n"
                         "di chi sta usando il gestionale su questo PC, e si può rispondere in chat da qui.",
                 font=self.font(9), fg="#64748b", justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(self.px(2), self.px(12)))
        tk.Label(f, text="Utente", font=self.font(9)).grid(row=2, column=0, sticky="w")
        u = tk.Entry(f, width=28, font=self.font(10))
        u.grid(row=2, column=1, pady=self.px(3))
        tk.Label(f, text="Password", font=self.font(9)).grid(row=3, column=0, sticky="w")
        p = tk.Entry(f, width=28, show="•", font=self.font(10))
        p.grid(row=3, column=1, pady=self.px(3))
        msg = tk.Label(f, text="", fg="#dc2626", font=self.font(9))
        msg.grid(row=4, column=0, columnspan=2, sticky="w")
        bottoni = tk.Frame(f)
        bottoni.grid(row=5, column=0, columnspan=2, sticky="e", pady=(self.px(8), 0))

        def chiudi():
            self._login_aperto = False
            w.destroy()

        def accedi(_e=None):
            msg.configure(text="Accesso in corso...", fg="#64748b")

            def lavoro():
                ok, err = self.app.accedi(u.get(), p.get())
                self.esegui(fine, ok, err)

            def fine(ok, err):
                if ok:
                    chiudi()
                else:
                    msg.configure(text=err, fg="#dc2626")

            threading.Thread(target=lavoro, daemon=True).start()

        tk.Button(bottoni, text="Più tardi", command=chiudi, relief="flat", bg="#f1f5f9", padx=self.px(10), font=self.font(9)).pack(side="left", padx=(0, self.px(6)))
        tk.Button(bottoni, text="Accedi", command=accedi, relief="flat", bg="#4f46e5", fg="#ffffff", padx=self.px(14), font=self.font(9)).pack(side="left")
        w.bind("<Return>", accedi)
        w.protocol("WM_DELETE_WINDOW", chiudi)
        w.update_idletasks()
        w.geometry(f"+{(w.winfo_screenwidth() - w.winfo_reqwidth()) // 2}+{(w.winfo_screenheight() - w.winfo_reqheight()) // 3}")
        w.focus_force()
        u.focus_set()


# =====================================================================================
# Programma principale
# =====================================================================================
class ClientNotifiche:
    def __init__(self):
        self.cfg = self._carica_config()
        self.server = self.cfg.get("server")
        self.attive = self.cfg.get("notifiche", True)
        self.suono_attivo = self.cfg.get("suono", True)
        self.token = self.cfg.get("token")
        self.utente = None           # nome di chi sta usando il gestionale da questo PC (dal server)
        self.utente_pc = None        # il suo username
        self.salutato = None         # ultimo utente a cui si è mostrato "ora arrivano i messaggi di..."
        self.rilasciato = False      # PC bloccato/inattivo già segnalato al server
        self.minuti_inattivita = self.cfg.get("minuti_inattivita", MINUTI_INATTIVITA)
        self.dimensione = self.cfg.get("dimensione", 1.0)
        self.versione_server = None  # versione del programma notifiche offerta dal server
        self.prossimo_tentativo = 0  # dopo un download fallito si riprova più tardi
        self.ultimo_id = None        # attività
        self.ultimo_msg = None       # messaggi chat
        self.notifiche_viste = None  # id notifiche già mostrate
        self.non_letti = 0
        self.collegato = None
        self.mio_ip = None
        self.base_img = Image.open(resource_path("favicon.ico")).convert("RGBA").resize((64, 64))
        self.icon = pystray.Icon("GestionaleNotifiche", self._immagine(), self._tooltip(), self._menu())
        self.ui = UI(self)

    # ---------- configurazione ----------
    def _carica_config(self):
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _salva_config(self):
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            self.cfg.update({"server": self.server, "notifiche": self.attive, "suono": self.suono_attivo,
                             "token": self.token, "minuti_inattivita": self.minuti_inattivita,
                             "dimensione": self.dimensione})
            self.cfg.pop("utente_nome", None)  # l'utente non è più fisso: lo dice il server
            CONFIG.write_text(json.dumps(self.cfg), encoding="utf-8")
        except Exception:
            pass

    # ---------- avvio automatico con Windows ----------
    @staticmethod
    def _comando_avvio():
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}"'
        return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

    def avvio_automatico(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                return winreg.QueryValueEx(k, APP)[0] == self._comando_avvio()
        except Exception:
            return False

    def imposta_avvio_automatico(self, attivo):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if attivo:
                    winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, self._comando_avvio())
                else:
                    try:
                        winreg.DeleteValue(k, APP)
                    except FileNotFoundError:
                        pass
        except Exception as e:
            print(f"Avvio automatico non impostato: {e}")

    # ---------- azioni verso il server ----------
    def apri(self, link="/"):
        if self.server:
            webbrowser.open(urllib.parse.urljoin(self.server, link or "/"))

    def accedi(self, utente, password):
        if not self.server:
            return False, "Server non trovato sulla rete."
        try:
            r = http_json(self.server + "api/widget/login",
                          {"username": utente, "password": password, "pc": socket.gethostname()})
        except urllib.error.HTTPError as e:
            return False, "Utente o password non validi." if e.code == 401 else f"Errore del server ({e.code})."
        except Exception:
            return False, "Server non raggiungibile."
        if not r.get("ok"):
            return False, r.get("error", "Accesso non riuscito.")
        self.token = r["token"]
        self._salva_config()
        self.rilasciato = False
        # chi fa l'accesso qui è seduto al PC: anche il server lo considera l'utente di questo PC
        self._cambia_utente(r["username"], r["full_name"], saluto=False)
        self.salutato = r["username"]
        self.ui.esegui(self.ui.avviso, "sistema", f"Ciao {self.utente}!",
                       "Ricevi qui i tuoi messaggi e le tue notifiche finché usi il gestionale su questo PC. "
                       "Puoi rispondere in chat direttamente dagli avvisi.")
        return True, ""

    def rilascia(self, *_):
        """Nasconde i messaggi personali: il PC non è più di nessuno finché qualcuno non usa il gestionale."""
        if self.utente_pc and self.server and self.token:
            try:
                http_json(self.server + "api/widget/rilascia", {"user": self.utente_pc}, token=self.token)
            except Exception:
                pass
        self._cambia_utente(None, None)

    def _cambia_utente(self, username, nome, saluto=True):
        if username == self.utente_pc:
            self.utente = nome or self.utente
            return
        self.utente_pc, self.utente = username, nome
        # si riparte da zero: niente arretrati, e via gli avvisi dell'utente precedente
        self.ultimo_msg, self.notifiche_viste, self.non_letti = None, None, 0
        self.ui.esegui(self.ui.chiudi_personali, username)
        if username and saluto and username != self.salutato:
            self.avviso("sistema", f"Messaggi di {nome}",
                        f"Su questo PC ora arrivano i messaggi e le notifiche di {nome}.")
        if username:
            self.salutato = username
        self._aggiorna()

    def rispondi(self, a_chi, testo, di=None):
        dati = {"to": a_chi, "text": testo}
        if di:
            dati["come"] = di  # il server rifiuta se nel frattempo al PC c'è un altro utente
        try:
            r = http_json(self.server + "api/widget/rispondi", dati, token=self.token)
            return bool(r.get("ok")), r.get("error", "")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                return False, "su questo PC ora c'è un altro utente"
            return False, "accesso scaduto, accedi di nuovo" if e.code == 401 else f"errore {e.code}"
        except Exception:
            return False, "server non raggiungibile"

    # ---------- icona e menu ----------
    def _immagine(self):
        img = self.base_img.copy()
        d = ImageDraw.Draw(img)
        colore = (148, 163, 184) if self.collegato is None else ((22, 163, 74) if self.collegato else (220, 38, 38))
        if self.non_letti:
            colore = (79, 70, 229)
        d.ellipse((34, 34, 63, 63), fill=colore, outline=(255, 255, 255), width=4)
        if self.non_letti:
            n = str(min(self.non_letti, 9))
            d.text((44, 38), n, fill=(255, 255, 255))
        return img

    def _stato(self):
        if self.collegato is None:
            return "Stato: ricerca del server..."
        if not self.collegato:
            return "Stato: ✖ server non raggiungibile"
        return f"Stato: ✔ collegato a {self.server.split('//')[1].rstrip('/')}"

    def _tooltip(self):
        extra = f"\n{self.non_letti} messaggi non letti" if self.non_letti else ""
        chi = f"\nMessaggi di {self.utente}" if self.utente else ""
        return f"{APP}{chi}\n{self._stato()}{extra}"[:127]

    def _aggiorna(self):
        self.icon.icon = self._immagine()
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def _menu(self):
        M = pystray.MenuItem
        return pystray.Menu(
            M(f"{APP} v{APP_VERSION}", None, enabled=False),
            M(lambda i: self._stato(), None, enabled=False),
            M(lambda i: self._chi(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            M("Apri Gestionale", lambda *_: self.apri("/"), default=True, enabled=lambda i: bool(self.server)),
            M(lambda i: f"Apri chat ({self.non_letti} non letti)" if self.non_letti else "Apri chat",
              lambda *_: self.apri("/?chat=__"), enabled=lambda i: bool(self.server)),
            pystray.Menu.SEPARATOR,
            M("Mostra avvisi", self._toggle_notifiche, checked=lambda i: self.attive),
            M("Suono", self._toggle_suono, checked=lambda i: self.suono_attivo),
            M("Avvia con Windows", self._toggle_avvio, checked=lambda i: self.avvio_automatico()),
            M("Dimensione avvisi", pystray.Menu(*[
                M(nome, self._imposta_dimensione(valore), radio=True,
                  checked=lambda i, v=valore: abs(self.dimensione - v) < 0.01)
                for nome, valore in DIMENSIONI])),
            pystray.Menu.SEPARATOR,
            M(lambda i: f"Non sono {self.utente}: nascondi i suoi messaggi" if self.utente else "-", self.rilascia,
              visible=lambda i: bool(self.utente)),
            M(lambda i: "Cambia utente..." if self.token else "Accedi...", lambda *_: self.ui.esegui(self.ui.chiedi_accesso),
              enabled=lambda i: bool(self.server)),
            M("Cerca di nuovo il server", self._ricerca),
            M("Chiudi programma", self._esci),
        )

    def _chi(self):
        if not self.token:
            return "Non hai ancora fatto l'accesso"
        if self.utente:
            return f"Messaggi di: {self.utente}"
        return "Nessuno sta usando il gestionale su questo PC"

    def _toggle_notifiche(self, *_):
        self.attive = not self.attive
        self._salva_config()
        self.icon.update_menu()

    def _toggle_suono(self, *_):
        self.suono_attivo = not self.suono_attivo
        self._salva_config()
        self.icon.update_menu()

    def _toggle_avvio(self, *_):
        self.imposta_avvio_automatico(not self.avvio_automatico())
        self.icon.update_menu()

    def _imposta_dimensione(self, valore):
        def imposta(*_):
            self.dimensione = valore
            self._salva_config()
            self.icon.update_menu()
            self.avviso("sistema", "Dimensione avvisi", "Gli avvisi ora avranno questa dimensione.", durata=6)
        return imposta

    def _ricerca(self, *_):
        self.server = None
        self.collegato = None
        self.ultimo_id = None
        self._aggiorna()

    def _esci(self, *_):
        self.icon.stop()
        os._exit(0)

    def avviso(self, *args, **kwargs):
        if self.attive:
            self.ui.esegui(lambda: self.ui.avviso(*args, **kwargs))

    # ---------- aggiornamento automatico ----------
    # Il programma arriva sul server insieme al gestionale (stesso installer, che il gestionale
    # scarica da solo da GitHub): quando il server ne ha una versione più nuova, questo PC la
    # scarica dal server, sostituisce il proprio .exe e si riavvia.
    def _controlla_aggiornamento(self):
        if not getattr(sys, "frozen", False) or not self.versione_server:
            return  # avviato da sorgente (sviluppo) o server vecchio che non offre aggiornamenti
        if versione_tupla(self.versione_server) <= versione_tupla(APP_VERSION):
            return
        if self.cfg.get("aggiornamento_tentato") == self.versione_server:
            return  # già provato per questa versione: niente tentativi a ripetizione
        if self.ui.avvisi or time.time() < self.prossimo_tentativo:
            return  # non si interrompe chi sta leggendo o rispondendo a un avviso
        exe = Path(sys.executable)
        nuovo = exe.with_name(exe.stem + ".nuovo.exe")
        try:
            req = urllib.request.Request(self.server + "api/notifiche/programma")
            with urllib.request.urlopen(req, timeout=120) as r, open(nuovo, "wb") as f:
                while True:
                    blocco = r.read(1 << 16)
                    if not blocco:
                        break
                    f.write(blocco)
            with open(nuovo, "rb") as f:
                if f.read(2) != b"MZ" or nuovo.stat().st_size < 1_000_000:
                    raise ValueError("file scaricato non valido")
        except Exception as e:
            # cartella non scrivibile (es. Programmi sul PC server: lì lo aggiorna l'installer) o rete
            print(f"Aggiornamento non riuscito: {e}")
            self.prossimo_tentativo = time.time() + 3600
            try:
                nuovo.unlink()
            except Exception:
                pass
            return
        try:
            self._avvia_sostituzione(exe, nuovo)
        except Exception as e:
            print(f"Aggiornamento non avviato: {e}")
            self.prossimo_tentativo = time.time() + 3600
            return
        # segnato prima di chiudere: se il nuovo .exe avesse ancora la vecchia versione non si riprova
        self.cfg["aggiornamento_tentato"] = self.versione_server
        self._salva_config()
        self._esci()

    def _avvia_sostituzione(self, exe, nuovo):
        """Come per il gestionale: un piccolo .bat aspetta che questo programma si chiuda,
        mette il nuovo .exe al posto del vecchio e lo riavvia."""
        bat = Path(os.environ.get("TEMP", str(Path.home()))) / f"aggiorna_notifiche_{os.getpid()}.bat"
        bat.write_text(f"""@echo off
chcp 65001 > nul
set /a n=0
:attendi
timeout /t 1 /nobreak > nul
move /y "{nuovo}" "{exe}" > nul 2>&1 && goto avvia
set /a n+=1
if %n% lss 60 goto attendi
del "{nuovo}" > nul 2>&1
:avvia
start "" "{exe}"
del "%~f0"
""", encoding="utf-8")
        import subprocess
        subprocess.Popen(["cmd.exe", "/c", str(bat)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         close_fds=True)

    # ---------- ciclo principale ----------
    def _controlla_attivita(self):
        url = self.server + "api/attivita" + (f"?dopo={self.ultimo_id}" if self.ultimo_id is not None else "")
        dati = http_json(url)
        eventi = dati.get("eventi", [])
        if self.ultimo_id is not None and dati.get("ultimo_id", 0) < self.ultimo_id:
            eventi = []  # server riavviato: il contatore riparte da zero
        self.mio_ip = dati.get("tuo_ip")
        self.versione_server = dati.get("notifiche_version")
        if self.ultimo_id is not None:
            # niente avvisi per le azioni fatte da questo stesso PC (tranne i PDF falliti)
            altrui = [e for e in eventi if e.get("ip") != self.mio_ip or e.get("tipo") == "pdf_errore"]
            if len(altrui) > 3:
                self.avviso("attivita", f"{len(altrui)} nuove attività",
                            "\n".join(e["testo"] for e in altrui[-3:]) + "\n...", link="/")
            else:
                for e in altrui:
                    self.avviso(e.get("tipo", "attivita"), e["testo"], "", link=e.get("link") or "/")
        self.ultimo_id = dati.get("ultimo_id", self.ultimo_id or 0)

    def _controlla_personali(self):
        if not self.token:
            return
        url = self.server + "api/widget/feed" + (f"?msg={self.ultimo_msg}" if self.ultimo_msg is not None else "")
        try:
            dati = http_json(url, token=self.token)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.token = None
                self._salva_config()
                self._cambia_utente(None, None)
                self.avviso("sistema", "Accesso scaduto", "Accedi di nuovo dal menu dell'icona per ricevere i messaggi.")
            return
        # Il server dice chi sta usando il gestionale da questo PC (un server vecchio dà sempre
        # l'utente del widget). Se nessuno lo sta usando non si mostra nulla di personale.
        self._cambia_utente(dati.get("username"), dati.get("full_name"))
        if not self.utente_pc:
            return
        di = self.utente_pc
        primo_giro = self.ultimo_msg is None
        self.non_letti = dati.get("messaggi_non_letti", 0)
        if not primo_giro:
            # un avviso per collega: l'ultimo messaggio, con il numero se sono più di uno
            per_mittente = {}
            for m in dati.get("messaggi", []):
                per_mittente.setdefault(m["from"], []).append(m)
            for mittente, msgs in per_mittente.items():
                ultimo = msgs[-1]
                testo = ultimo["text"] or (f"📎 {ultimo['allegato']}" if ultimo["allegato"] else "")
                titolo = ultimo["from_name"] + (f"  ({len(msgs)} messaggi)" if len(msgs) > 1 else "")
                self.avviso("chat", titolo, testo, link=f"/?chat={urllib.parse.quote(mittente)}",
                            rispondi_a=mittente, durata=30, di=di)
        self.ultimo_msg = dati.get("ultimo_msg_id", self.ultimo_msg or 0)

        ids = {n["id"] for n in dati.get("notifiche", [])}
        if self.notifiche_viste is not None:
            for n in dati.get("notifiche", []):
                if n["id"] not in self.notifiche_viste:
                    self.avviso("notifica", n["text"], "", link=n.get("link") or "/", durata=15, di=di)
        self.notifiche_viste = (self.notifiche_viste or set()) | ids

    def _controlla_presenza(self):
        """PC bloccato o lasciato inattivo: i messaggi personali si nascondono (una volta per assenza)."""
        fermo = secondi_inattivita()
        assente = (pc_bloccato() and fermo >= SECS_BLOCCO) or (
            self.minuti_inattivita and fermo >= self.minuti_inattivita * 60)
        if not assente:
            self.rilasciato = False
        elif not self.rilasciato and self.utente_pc:
            self.rilasciato = True
            self.rilascia()

    def _ciclo(self):
        fallimenti = 0
        while True:
            if not self.server:
                trovato = cerca_server()
                if trovato:
                    self.server = trovato
                    self._salva_config()
                    if not self.token:
                        self.ui.esegui(self.ui.chiedi_accesso)
                else:
                    self.collegato = False
                    self._aggiorna()
                    time.sleep(30)
                    continue
            try:
                self._controlla_attivita()
                if self.collegato is False:
                    self.avviso("sistema", "Di nuovo collegato al gestionale.", "")
                self.collegato, fallimenti = True, 0
                if self.token:
                    self._controlla_presenza()
                self._controlla_personali()
                self._controlla_aggiornamento()
            except Exception:
                fallimenti += 1
                if self.collegato and fallimenti >= 3:
                    self.collegato = False
                    self.avviso("sistema", "Il gestionale non risponde", "Il PC server potrebbe essere spento o scollegato.")
                if fallimenti >= 12:  # ~1 minuto: forse il server ha cambiato indirizzo
                    self.server, fallimenti = None, 0
            self._aggiorna()
            time.sleep(INTERVALLO_SECS)

    def avvia(self):
        if "avvio_impostato" not in self.cfg:
            # Al primo avvio si attiva l'avvio automatico con Windows
            self.imposta_avvio_automatico(True)
            self.cfg["avvio_impostato"] = True
            self._salva_config()
        threading.Thread(target=self._ciclo, daemon=True).start()
        self.icon.run()


def gia_in_esecuzione():
    """Una sola copia per utente (mutex di Windows)."""
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GestionaleNotificheCerlab")
        return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


if __name__ == "__main__":
    if gia_in_esecuzione():
        sys.exit(0)
    ClientNotifiche().avvia()
