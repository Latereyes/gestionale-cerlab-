"""Ceerlo, l'assistente AI del gestionale.

Il modello gira con Ollama su un altro PC dell'azienda, raggiunto via Tailscale (es. http://100.x.y.z:11434).
Il gestionale fa da arbitro: tutte le richieste passano da una coda unica, cosi' la GPU lavora su una
richiesta alla volta (o su quante ne sono impostate) e gli utenti vedono la loro posizione in coda.
Priorita': chat degli utenti, poi riassunti chiesti a mano, poi riassunti automatici degli appuntamenti.
Configurazione e riassunti in DATA_DIR/ceerlo (cartella dati in %APPDATA%, mai nel repo).
"""
import datetime
import heapq
import itertools
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

NOME = "Ceerlo"
PRIO_CHAT, PRIO_RICHIESTA, PRIO_AUTO = 0, 1, 2
SCADENZA_JOB = 30 * 60  # i risultati non ritirati si buttano dopo 30 minuti

_DATA_DIR = None
_LOCK_FILE = threading.Lock()

_PREDEFINITA = {
    "attivo": False,
    "url": "",                          # indirizzo Tailscale del PC con Ollama, es. http://100.x.y.z:11434
    "modello": "",
    "contemporanee": 1,                 # richieste elaborate insieme: con una GPU da 10 GB conviene 1
    "timeout": 300,
    "num_ctx": 32768,                   # misurato 31/10 con gemma4-12b: ~8 GB di VRAM, sta nella 3070 Ti da 10 GB
    "riassunti_auto": True,
    "ore_anticipo": 48,                 # riassunti automatici per gli appuntamenti delle prossime N ore
}


def configura(data_dir):
    global _DATA_DIR
    _DATA_DIR = Path(data_dir) / "ceerlo"
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[ceerlo] {msg}")
    try:
        with open(_DATA_DIR / "ceerlo.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def _leggi_json(nome, predefinito):
    try:
        with open(_DATA_DIR / nome, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return predefinito
    except Exception as e:
        log(f"{nome} non leggibile: {e}")
        return predefinito


def _scrivi_json(nome, dati):
    with _LOCK_FILE:
        tmp = _DATA_DIR / (nome + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dati, f, ensure_ascii=False, indent=2)
        tmp.replace(_DATA_DIR / nome)


def leggi_config():
    cfg = dict(_PREDEFINITA)
    cfg.update(_leggi_json("config.json", {}))
    return cfg


def salva_config(valori):
    cfg = leggi_config()
    cfg.update(valori)
    _scrivi_json("config.json", cfg)
    _CODA.adegua_lavoratori()
    return cfg


def attivo(cfg=None):
    cfg = cfg or leggi_config()
    return bool(cfg["attivo"] and cfg["url"] and cfg["modello"])


# --- Ollama ---

def _http(metodo, percorso, corpo=None, timeout=10, url=None):
    url = url or leggi_config()["url"]
    if not url:
        raise RuntimeError("indirizzo di Ollama non impostato")
    req = urllib.request.Request(url.rstrip("/") + percorso, method=metodo,
                                 data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def normalizza_url(url):
    url = (url or "").strip().rstrip("/")
    if url and not url.lower().startswith(("http://", "https://")):
        url = "http://" + url
    return url


def modelli_disponibili(url=None):
    """Prova la connessione (all'indirizzo dato o a quello salvato): restituisce i modelli installati su Ollama."""
    return sorted(m["name"] for m in _http("GET", "/api/tags", url=normalizza_url(url) or None).get("models", []))


def chat_ollama(messaggi):
    cfg = leggi_config()
    corpo = {"model": cfg["modello"], "messages": messaggi, "stream": False, "think": False,
             "options": {"num_ctx": int(cfg["num_ctx"] or 32768)}}
    try:
        r = _http("POST", "/api/chat", corpo, timeout=int(cfg["timeout"] or 300))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama ha risposto {e.code}: {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"PC dell'AI non raggiungibile ({e}). E' acceso e collegato a Tailscale?")
    return ((r.get("message") or {}).get("content") or "").strip()


# --- Coda con arbitraggio ---

class _Coda:
    def __init__(self):
        self._heap, self._job = [], {}
        self._seq = itertools.count()
        self._cond = threading.Condition()
        self._lavoratori = 0

    def adegua_lavoratori(self):
        voluti = max(1, min(4, int(leggi_config()["contemporanee"] or 1)))
        with self._cond:
            while self._lavoratori < voluti:
                self._lavoratori += 1
                threading.Thread(target=self._lavora, daemon=True, name=f"Ceerlo-{self._lavoratori}").start()

    def aggiungi(self, utente, messaggi, priorita, tipo, al_termine=None, chiave=""):
        """Mette in coda una richiesta. Un utente ha al massimo una richiesta di chat in attesa;
        un riassunto con la stessa chiave gia' in coda non si duplica."""
        with self._cond:
            self._pulisci()
            for j in self._job.values():
                if j["stato"] in ("in_coda", "in_lavoro"):
                    if chiave and j["chiave"] == chiave:
                        return j["id"]
                    if tipo == "chat" and j["tipo"] == "chat" and j["utente"] == utente:
                        raise ValueError(f"{NOME} sta ancora rispondendo alla tua domanda precedente.")
            jid = uuid.uuid4().hex[:12]
            self._job[jid] = {"id": jid, "utente": utente, "tipo": tipo, "chiave": chiave, "stato": "in_coda",
                              "messaggi": messaggi, "risposta": "", "errore": "", "creato": time.time(),
                              "finito": 0, "al_termine": al_termine, "priorita": priorita}
            heapq.heappush(self._heap, (priorita, next(self._seq), jid))
            self._cond.notify()
        self.adegua_lavoratori()
        return jid

    def posizione(self, jid):
        """Quante richieste ci sono prima di questa (comprese quelle gia' in lavorazione)."""
        with self._cond:
            j = self._job.get(jid)
            if not j or j["stato"] != "in_coda":
                return 0
            mia = next((v for v in self._heap if v[2] == jid), None)
            prima = sum(1 for v in self._heap if mia and v < mia)
            in_lavoro = sum(1 for x in self._job.values() if x["stato"] == "in_lavoro")
            return prima + in_lavoro

    def stato(self, jid, utente=None):
        with self._cond:
            j = self._job.get(jid)
            if not j or (utente and j["utente"] != utente):
                return None
            dati = {k: j[k] for k in ("id", "tipo", "stato", "risposta", "errore")}
        dati["posizione"] = self.posizione(jid)
        return dati

    def riepilogo(self):
        with self._cond:
            return {"in_coda": sum(1 for j in self._job.values() if j["stato"] == "in_coda"),
                    "in_lavoro": sum(1 for j in self._job.values() if j["stato"] == "in_lavoro")}

    def _pulisci(self):
        adesso = time.time()
        for jid in [k for k, j in self._job.items() if j["finito"] and adesso - j["finito"] > SCADENZA_JOB]:
            del self._job[jid]

    def _lavora(self):
        while True:
            with self._cond:
                while not self._heap:
                    self._cond.wait()
                _, _, jid = heapq.heappop(self._heap)
                j = self._job.get(jid)
                if not j:
                    continue
                j["stato"] = "in_lavoro"
            try:
                inizio = time.time()
                risposta = chat_ollama(j["messaggi"])
                j.update(risposta=risposta, stato="fatto")
                log(f"{j['tipo']} per {j['utente']} in {time.time() - inizio:.0f}s")
                if j["al_termine"]:
                    j["al_termine"](risposta)
            except Exception as e:
                j.update(errore=str(e), stato="errore")
                log(f"{j['tipo']} per {j['utente']}: errore {e}")
            finally:
                j["finito"] = time.time()
                j["messaggi"] = None


_CODA = _Coda()
aggiungi = _CODA.aggiungi
stato_job = _CODA.stato
riepilogo_coda = _CODA.riepilogo


# --- Prompt ---

def prompt_sistema(utente_nome, ruolo, contesto):
    oggi = datetime.datetime.now()
    return (
        f"Sei {NOME}, l'assistente del gestionale di CERLAB (negozio di arredo bagno, pavimenti e rivestimenti). "
        f"Rispondi sempre in italiano, in modo breve, cordiale e pratico. Oggi e' {oggi:%A %d/%m/%Y}, ore {oggi:%H:%M}. "
        f"Stai parlando con {utente_nome} (ruolo: {ruolo}). "
        "Usa solo le informazioni del CONTESTO qui sotto: se una cosa non c'e', dillo e non inventare "
        "nomi, date o numeri. Non puoi ancora modificare dati del gestionale: se ti chiedono di farlo, "
        "spiega dove farlo nelle pagine.\n\nCONTESTO:\n" + (contesto or "(nessun dato)")
    )


def prompt_riassunto(evento, contesto):
    return (
        f"Prepara un riassunto per l'appuntamento \"{evento.get('titolo')}\" del {evento.get('inizio', '')[:16].replace('T', ' ')}"
        f"{' con ' + evento['cliente'] if evento.get('cliente') else ''}. "
        "In massimo 8 righe: chi e' il cliente, cosa ha in corso (preventivi e stato), cosa dicono note e report recenti, "
        "e 2-3 punti da ricordare o chiedere all'appuntamento. Usa solo i dati del contesto.\n\nCONTESTO:\n" + contesto
    )


# --- Riassunti degli appuntamenti ---

def riassunti():
    return _leggi_json("riassunti.json", {})


def salva_riassunto(evento, testo):
    tutti = riassunti()
    tutti[evento["id"]] = {"testo": testo, "creato_il": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                           "titolo": evento.get("titolo", ""), "inizio": evento.get("inizio", ""),
                           "cliente": evento.get("cliente", "")}
    # tiene solo gli ultimi 60 giorni
    limite = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
    tutti = {k: v for k, v in tutti.items() if (v.get("inizio") or "9999") >= limite}
    _scrivi_json("riassunti.json", tutti)


def chiedi_riassunto(evento, contesto, utente="ceerlo", priorita=PRIO_RICHIESTA):
    messaggi = [{"role": "system", "content": prompt_sistema("il team", "tutti", "")},
                {"role": "user", "content": prompt_riassunto(evento, contesto)}]
    return aggiungi(utente, messaggi, priorita, "riassunto",
                    al_termine=lambda testo: salva_riassunto(evento, testo), chiave=f"riassunto:{evento['id']}")


def avvia_riassunti_automatici(prossimi_eventi, contesto_evento):
    """Ogni 15 minuti mette in coda (a bassa priorita') i riassunti degli appuntamenti in arrivo che non ce l'hanno.
    prossimi_eventi(ore) -> eventi del calendario; contesto_evento(evento) -> testo di contesto."""
    def _giro():
        time.sleep(60)
        while True:
            try:
                cfg = leggi_config()
                if attivo(cfg) and cfg["riassunti_auto"]:
                    fatti = riassunti()
                    for ev in prossimi_eventi(int(cfg["ore_anticipo"] or 48)):
                        if ev["id"] not in fatti and (ev.get("cliente") or ev.get("cliente_id")):
                            chiedi_riassunto(ev, contesto_evento(ev), priorita=PRIO_AUTO)
            except Exception as e:
                log(f"Riassunti automatici: {e}")
            time.sleep(900)
    threading.Thread(target=_giro, daemon=True, name="CeerloRiassunti").start()
