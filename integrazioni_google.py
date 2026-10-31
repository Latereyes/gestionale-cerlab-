"""Integrazioni Google del gestionale: email dei report via Gmail (SMTP) e calendario condiviso (Google Calendar).

Le credenziali stanno in DATA_DIR/integrazioni/google.json (cartella dati in %APPDATA%, mai nel repo).
Password per le app e token Google sono cifrati con DPAPI di Windows: si leggono solo dall'utente
Windows del PC del gestionale. Nessuna libreria in piu': SMTP e chiamate HTTP con la libreria standard.
"""
import base64
import datetime
import hashlib
import json
import re
import secrets
import smtplib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

_DATA_DIR = None
_LOCK = threading.Lock()

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
# Scope minimo: vedere e creare eventi sui calendari a cui l'account ha accesso (non legge la posta, non gestisce i calendari)
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
FUSO = "Europe/Rome"


def configura(data_dir):
    global _DATA_DIR
    _DATA_DIR = Path(data_dir)
    (_DATA_DIR / "integrazioni").mkdir(parents=True, exist_ok=True)


def _file_config():
    return _DATA_DIR / "integrazioni" / "google.json"


def _file_log():
    return _DATA_DIR / "integrazioni" / "google.log"


def log(msg):
    riga = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(f"[google] {msg}")
    try:
        with open(_file_log(), "a", encoding="utf-8") as f:
            f.write(riga + "\n")
    except Exception:
        pass


# --- Cifratura dei segreti (DPAPI su Windows) ---

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _dpapi(dati, cifra):
        buf = ctypes.create_string_buffer(dati, len(dati))
        ingresso = _BLOB(len(dati), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        uscita = _BLOB()
        fn = ctypes.windll.crypt32.CryptProtectData if cifra else ctypes.windll.crypt32.CryptUnprotectData
        if not fn(ctypes.byref(ingresso), None, None, None, None, 0x1, ctypes.byref(uscita)):  # 0x1 = nessuna finestra
            raise OSError("DPAPI non riuscita")
        try:
            return ctypes.string_at(uscita.pbData, uscita.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(uscita.pbData)


def proteggi(testo):
    if not testo:
        return ""
    dati = testo.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(dati, True)).decode()
    return "b64:" + base64.b64encode(dati).decode()  # solo per prove fuori da Windows


def svela(valore):
    if not valore:
        return ""
    tipo, _, dati = valore.partition(":")
    try:
        grezzo = base64.b64decode(dati)
        if tipo == "dpapi" and sys.platform == "win32":
            return _dpapi(grezzo, False).decode("utf-8")
        if tipo == "b64":
            return grezzo.decode("utf-8")
    except Exception as e:
        log(f"Segreto non leggibile: {e}")
    return ""


# --- Configurazione ---

_PREDEFINITA = {
    "email": {"mittente": "", "password": "",
              "invia_report": True, "riepilogo": True, "ora_riepilogo": "19:00", "ultimo_riepilogo": ""},
    "calendar": {"client_id": "", "client_secret": "", "calendar_id": "", "refresh_token": "",
                 "account": "", "collegato_il": ""},
    # Chiusura serale: Gestionale Notifiche spegne i PC all'ora scelta; il riepilogo parte MINUTI_PRIMA prima
    "chiusura": {"spegni": False, "ora": "20:00"},
}

MINUTI_PRIMA = 30  # con lo spegnimento attivo il riepilogo parte mezz'ora prima (c'e' tempo per il riassunto AI)


def leggi_config():
    cfg = json.loads(json.dumps(_PREDEFINITA))
    try:
        with open(_file_config(), "r", encoding="utf-8") as f:
            salvata = json.load(f)
        for sezione in cfg:
            cfg[sezione].update(salvata.get(sezione) or {})
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"Config non leggibile: {e}")
    return cfg


def salva_config(cfg):
    with _LOCK:
        tmp = _file_config().with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        tmp.replace(_file_config())


def aggiorna_sezione(sezione, valori):
    cfg = leggi_config()
    cfg[sezione].update(valori)
    salva_config(cfg)
    return cfg


def stato_pubblico():
    """La configurazione senza segreti, per la pagina impostazioni."""
    cfg = leggi_config()
    e, c = cfg["email"], cfg["calendar"]
    return {
        "email": {k: e[k] for k in ("mittente", "invia_report", "riepilogo", "ora_riepilogo", "ultimo_riepilogo")}
                 | {"password_salvata": bool(e["password"]), "attiva": email_attiva(cfg)},
        "calendar": {k: c[k] for k in ("client_id", "calendar_id", "account", "collegato_il")}
                    | {"secret_salvato": bool(c["client_secret"]), "collegato": bool(c["refresh_token"])},
        "chiusura": dict(cfg["chiusura"]) | {"ora_riepilogo": ora_riepilogo(cfg)},
    }


def _ora_minuti(testo, predefinita):
    try:
        ora, minuti = (int(x) for x in (testo or predefinita).split(":"))
        return ora, minuti
    except ValueError:
        return tuple(int(x) for x in predefinita.split(":"))


def ora_riepilogo(cfg=None):
    """Ora del riepilogo serale: quella scelta, oppure MINUTI_PRIMA prima dello spegnimento dei PC."""
    cfg = cfg or leggi_config()
    if cfg["chiusura"]["spegni"]:
        ora, minuti = _ora_minuti(cfg["chiusura"]["ora"], "20:00")
        t = datetime.datetime.combine(datetime.date.today(), datetime.time(ora, minuti)) - datetime.timedelta(minutes=MINUTI_PRIMA)
        return t.strftime("%H:%M")
    return cfg["email"]["ora_riepilogo"] or "19:00"


def stato_chiusura(destinatari_presenti=True, adesso=None):
    """Per Gestionale Notifiche: se e a che ora spegnere i PC, e se il riepilogo e' gia' partito (pronto)."""
    cfg = leggi_config()
    adesso = adesso or datetime.datetime.now()
    e = cfg["email"]
    ora, minuti = _ora_minuti(ora_riepilogo(cfg), "19:00")
    scadenza = adesso.replace(hour=ora, minute=minuti, second=0, microsecond=0)
    serve = email_attiva(cfg) and e["riepilogo"] and destinatari_presenti
    pronto = not serve or (e["ultimo_riepilogo"] or "") >= scadenza.strftime("%Y-%m-%d %H:%M:%S")
    return {"spegni": bool(cfg["chiusura"]["spegni"]), "ora": cfg["chiusura"]["ora"] or "20:00", "pronto": pronto}


# --- Email ---

def email_attiva(cfg=None):
    e = (cfg or leggi_config())["email"]
    return bool(e["mittente"] and e["password"])


_IMPORTO = re.compile(
    r"(€\s*\d[\d.,]*|\d[\d.,]*\s*(?:€|euro\b|eur\b)|\b(?:iva|imponibile|totale|prezzo|importo|sconto)\b[^\n]*?\d[\d.,]*)",
    re.IGNORECASE)


def togli_importi(testo):
    """Nelle email non deve passare nessun dato economico: gli importi diventano [importo]."""
    return _IMPORTO.sub("[importo]", testo or "")


def _manda(destinatari, oggetto, testo, html=None):
    cfg = leggi_config()["email"]
    password = svela(cfg["password"])
    if not cfg["mittente"] or not password:
        return False, "Email non configurata."
    dest = [d for d in destinatari if d]
    if not dest:
        return False, "Nessun destinatario."
    msg = EmailMessage()
    msg["From"] = f"Gestionale Cerlab <{cfg['mittente']}>"
    msg["To"] = ", ".join(dest)
    msg["Subject"] = oggetto
    msg.set_content(togli_importi(testo))
    if html:
        msg.add_alternative(html, subtype="html")  # l'HTML arriva gia' senza importi (lo compone chi lo manda)
    utente, chiave = cfg["mittente"].strip(), password.replace(" ", "").strip()
    errori = []
    # prima SSL sulla 465; se Gmail chiude la connessione (rete, antivirus, errore temporaneo) riprova con STARTTLS sulla 587
    for porta in (SMTP_PORT, 587):
        fase = "connessione"
        try:
            contesto = ssl.create_default_context()
            if porta == 465:
                s = smtplib.SMTP_SSL(SMTP_HOST, porta, timeout=30, context=contesto)
            else:
                s = smtplib.SMTP(SMTP_HOST, porta, timeout=30)
                s.ehlo()
                s.starttls(context=contesto)
                s.ehlo()
            with s:
                fase = "accesso"
                s.login(utente, chiave)
                fase = "invio"
                s.send_message(msg)
            log(f"Email inviata a {', '.join(dest)} (porta {porta}): {oggetto}")
            return True, ""
        except smtplib.SMTPAuthenticationError as e:
            log(f"Email: accesso a Gmail rifiutato ({e.smtp_code})")
            return False, "Gmail ha rifiutato l'accesso: controlla l'indirizzo e crea una nuova password per le app."
        except (smtplib.SMTPException, OSError) as e:
            log(f"Email non inviata ({oggetto}), porta {porta}, fase {fase}: {e!r}")
            errori.append(f"porta {porta} ({fase}): {e}")
    return False, ("Invio non riuscito, Gmail ha chiuso la connessione. Se si ripete, crea una nuova password "
                   "per le app. Dettagli: " + "; ".join(errori))


def manda_in_background(destinatari, oggetto, testo):
    """Non blocca mai la richiesta: l'invio va in un thread e gli errori finiscono nel log."""
    threading.Thread(target=_manda, args=(destinatari, oggetto, testo), daemon=True).start()


def email_prova(destinatari):
    if isinstance(destinatari, str):
        destinatari = [destinatari]
    return _manda(list(destinatari), "Prova email dal Gestionale Cerlab",
                  "Se leggi questo messaggio l'invio delle email dal gestionale funziona.")


def _voci_testo(report):
    voci = report.get("righe") or []
    if voci:
        return "\n".join(f"- {v.get('testo', '')}" for v in voci)
    return report.get("testo") or ""


def email_report(report, destinatari):
    """Un report appena inviato: va a chi in gestione utenze ha "riceve i report"."""
    cfg = leggi_config()
    if not email_attiva(cfg) or not cfg["email"]["invia_report"] or not destinatari:
        return
    quando = (report.get("creato_il") or "")[:16]
    oggetto = f"Report di {report.get('autore_nome') or report.get('autore')} - {quando}"
    testo = (f"{report.get('autore_nome') or report.get('autore')} ha inviato un report ({quando}).\n\n"
             f"{_voci_testo(report)}\n\nApri il gestionale per i dettagli: pagina Task & Report.")
    manda_in_background(destinatari, oggetto, testo)


def email_admin_task(richiesta, destinatari):
    """Una richiesta dal tasto flottante admin: va a chi in gestione utenze ha "riceve le richieste admin"."""
    cfg = leggi_config()
    if not email_attiva(cfg) or not destinatari:
        return
    oggetto = f"Richiesta admin {richiesta.get('id')} da {richiesta.get('user_name')}"
    testo = (f"{richiesta.get('user_name')} ha inviato una richiesta admin il {richiesta.get('timestamp')}.\n\n"
             f"{richiesta.get('description')}")
    manda_in_background(destinatari, oggetto, testo)


def avvia_riepilogo_giornaliero(report_dal, destinatari, componi=None):
    """Ogni giorno all'ora del riepilogo manda i report inviati dall'ultimo riepilogo a chi riceve i report.
    report_dal(quando) -> lista di report (dict) inviati dopo 'quando' ("YYYY-MM-DD HH:MM:SS");
    destinatari() -> indirizzi email;
    componi(reports, dal, adesso) -> (oggetto, testo, html): l'email impaginata (facoltativa, se fallisce si manda il testo).
    Se il PC era spento all'ora del riepilogo, parte appena il gestionale si riaccende."""
    def _giro():
        while True:
            try:
                _controlla_riepilogo(report_dal, destinatari(), componi=componi)
            except Exception as e:
                log(f"Riepilogo: errore {e}")
            time.sleep(60)
    threading.Thread(target=_giro, daemon=True, name="RiepilogoEmail").start()


def _controlla_riepilogo(report_dal, destinatari, adesso=None, componi=None):
    cfg = leggi_config()
    e = cfg["email"]
    if not email_attiva(cfg) or not e["riepilogo"] or not destinatari:
        return False
    adesso = adesso or datetime.datetime.now()
    ora, minuti = _ora_minuti(ora_riepilogo(cfg), "19:00")
    scadenza = adesso.replace(hour=ora, minute=minuti, second=0, microsecond=0)
    ultimo = e["ultimo_riepilogo"]
    if adesso < scadenza or (ultimo and ultimo >= scadenza.strftime("%Y-%m-%d %H:%M:%S")):
        return False
    dal = ultimo or (scadenza - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    reports = sorted(report_dal(dal), key=lambda r: r.get("creato_il", ""))
    if reports:
        blocchi = [f"{r.get('autore_nome') or r.get('autore')} ({(r.get('creato_il') or '')[:16]})\n{_voci_testo(r)}"
                   for r in reports]
        testo = f"Report inviati dal {dal[:16]}: {len(reports)}\n\n" + "\n\n".join(blocchi)
    else:
        testo = f"Nessun report inviato dal {dal[:16]}."
    oggetto, html = f"Riepilogo report del {adesso:%d/%m/%Y}", None
    if componi:
        try:
            oggetto, testo, html = componi(reports, dal, adesso)
        except Exception as ex:
            log(f"Riepilogo impaginato non riuscito, parte quello semplice: {ex}")
    ok, _ = _manda(destinatari, oggetto, testo, html)
    if ok:
        aggiorna_sezione("email", {"ultimo_riepilogo": adesso.strftime("%Y-%m-%d %H:%M:%S")})
    return ok


# --- Google Calendar ---

_ATTESE = {}  # state -> (code_verifier, redirect_uri, scadenza) per il collegamento in corso
_TOKEN = {"valore": "", "scade": 0}


def calendar_collegato(cfg=None):
    c = (cfg or leggi_config())["calendar"]
    return bool(c["refresh_token"] and c["client_id"])


def url_collegamento(redirect_uri):
    c = leggi_config()["calendar"]
    if not c["client_id"] or not c["client_secret"]:
        raise ValueError("Inserisci prima ID client e segreto client.")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    sfida = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    adesso = time.time()
    for k in [k for k, v in _ATTESE.items() if v[2] < adesso]:
        _ATTESE.pop(k, None)
    _ATTESE[state] = (verifier, redirect_uri, adesso + 600)
    parametri = {
        "client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": f"{CALENDAR_SCOPE} openid email", "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": sfida, "code_challenge_method": "S256",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(parametri)


def _post_form(url, dati):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(dati).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="replace")
        raise RuntimeError(f"Google ha risposto {e.code}: {corpo[:300]}")


def completa_collegamento(code, state):
    attesa = _ATTESE.pop(state, None)
    if not attesa or attesa[2] < time.time():
        raise ValueError("Collegamento scaduto o non valido: riprova da Impostazioni Google.")
    verifier, redirect_uri, _ = attesa
    c = leggi_config()["calendar"]
    risposta = _post_form(GOOGLE_TOKEN_URL, {
        "code": code, "client_id": c["client_id"], "client_secret": svela(c["client_secret"]),
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if not risposta.get("refresh_token"):
        raise RuntimeError("Google non ha restituito il token di accesso permanente: riprova il collegamento.")
    account = _email_da_id_token(risposta.get("id_token", ""))
    _TOKEN.update(valore=risposta.get("access_token", ""), scade=time.time() + int(risposta.get("expires_in", 0)) - 60)
    aggiorna_sezione("calendar", {"refresh_token": proteggi(risposta["refresh_token"]), "account": account,
                                  "collegato_il": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
    log(f"Calendar collegato all'account {account}")
    return account


def _email_da_id_token(id_token):
    try:
        corpo = id_token.split(".")[1]
        corpo += "=" * (-len(corpo) % 4)
        return json.loads(base64.urlsafe_b64decode(corpo)).get("email", "")
    except Exception:
        return ""


def scollega_calendar():
    _TOKEN.update(valore="", scade=0)
    aggiorna_sezione("calendar", {"refresh_token": "", "account": "", "collegato_il": ""})


def _access_token():
    if _TOKEN["valore"] and _TOKEN["scade"] > time.time():
        return _TOKEN["valore"]
    c = leggi_config()["calendar"]
    refresh = svela(c["refresh_token"])
    if not refresh:
        raise RuntimeError("Calendario non collegato: un amministratore deve collegarlo da Impostazioni Google.")
    try:
        r = _post_form(GOOGLE_TOKEN_URL, {"client_id": c["client_id"], "client_secret": svela(c["client_secret"]),
                                          "refresh_token": refresh, "grant_type": "refresh_token"})
    except RuntimeError as e:
        if "invalid_grant" in str(e):
            log("Calendar: accesso revocato o scaduto, va ricollegato")
            raise RuntimeError("Il collegamento a Google Calendar e' scaduto: un amministratore deve ricollegarlo.")
        raise
    _TOKEN.update(valore=r["access_token"], scade=time.time() + int(r.get("expires_in", 3600)) - 60)
    return _TOKEN["valore"]


def _api(metodo, percorso, parametri=None, corpo=None):
    url = CALENDAR_API + percorso
    if parametri:
        url += "?" + urllib.parse.urlencode(parametri)
    req = urllib.request.Request(url, method=metodo, data=json.dumps(corpo).encode() if corpo is not None else None,
                                 headers={"Authorization": f"Bearer {_access_token()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            dati = r.read().decode()
            return json.loads(dati) if dati else {}
    except urllib.error.HTTPError as e:
        corpo_err = e.read().decode(errors="replace")
        log(f"Calendar {metodo} {percorso}: {e.code} {corpo_err[:300]}")
        if e.code == 404:
            raise RuntimeError("Calendario non trovato: controlla l'ID calendario in Impostazioni Google.")
        if e.code == 403:
            raise RuntimeError("L'account collegato non ha il permesso di modificare questo calendario.")
        raise RuntimeError(f"Google Calendar ha risposto {e.code}.")


def normalizza_id_calendario(testo):
    """Accetta l'ID calendario anche incollato come link (embed?src=..., ?cid=..., indirizzo iCal):
    restituisce solo l'ID, es. 'negozio@gmail.com' o 'abc...@group.calendar.google.com'."""
    testo = (testo or "").strip()
    if "://" not in testo:
        return urllib.parse.unquote(testo)
    url = urllib.parse.urlparse(testo)
    q = urllib.parse.parse_qs(url.query)
    for chiave in ("src", "cid"):
        if q.get(chiave):
            valore = q[chiave][0]
            if chiave == "cid" and "@" not in valore:  # i link "aggiungi calendario" hanno l'ID in base64
                try:
                    valore = base64.urlsafe_b64decode(valore + "=" * (-len(valore) % 4)).decode()
                except Exception:
                    pass
            return valore.strip()
    m = re.search(r"/calendar/ical/([^/]+)/", url.path)  # indirizzo iCal pubblico o segreto
    return urllib.parse.unquote(m.group(1)) if m else testo


def _id_calendario():
    return leggi_config()["calendar"]["calendar_id"] or "primary"


def _evento_semplice(ev):
    inizio, fine = ev.get("start", {}), ev.get("end", {})
    privati = (ev.get("extendedProperties") or {}).get("private") or {}
    return {
        "id": ev.get("id"), "titolo": ev.get("summary") or "(senza titolo)",
        "descrizione": ev.get("description") or "", "luogo": ev.get("location") or "",
        "inizio": inizio.get("dateTime") or inizio.get("date") or "",
        "fine": fine.get("dateTime") or fine.get("date") or "",
        "tutto_il_giorno": "date" in inizio and "dateTime" not in inizio,
        "link": ev.get("htmlLink") or "",
        "cliente": privati.get("cliente", ""), "cliente_id": privati.get("cliente_id", ""),
        "preventivo": privati.get("preventivo", ""), "task": privati.get("task", ""),
        "creato_da": privati.get("creato_da", ""),
        "assegnati": [u for u in (privati.get("assegnati") or "").split(",") if u],
    }


def _ora_locale(giorno, ora):
    """Data e ora con il fuso del PC (Google vuole RFC 3339 con l'offset)."""
    return datetime.datetime.combine(giorno, ora).astimezone().isoformat()


def eventi(dal, al):
    """Eventi del calendario condiviso tra due date (datetime.date), in ordine di inizio."""
    risultato, pagina = [], None
    while True:
        parametri = {"timeMin": _ora_locale(dal, datetime.time(0, 0)),
                     "timeMax": _ora_locale(al, datetime.time(23, 59, 59)),
                     "singleEvents": "true", "orderBy": "startTime", "maxResults": 250, "timeZone": FUSO}
        if pagina:
            parametri["pageToken"] = pagina
        r = _api("GET", f"/calendars/{urllib.parse.quote(_id_calendario(), safe='')}/events", parametri)
        risultato += [_evento_semplice(e) for e in r.get("items", []) if e.get("status") != "cancelled"]
        pagina = r.get("nextPageToken")
        if not pagina:
            return risultato


def _riga_assegnati(nomi):
    return f"Assegnato a: {', '.join(nomi)}" if nomi else ""


def crea_evento(titolo, giorno, ora_inizio="", durata_minuti=60, descrizione="", luogo="",
                collegamenti=None, creato_da="", assegnati=None, nomi_assegnati=None):
    """Crea un appuntamento. Senza ora e' un evento di tutto il giorno.
    collegamenti: cliente, cliente_id, preventivo, task (restano nell'evento per ritrovarli dal gestionale).
    assegnati: username dei colleghi responsabili; nomi_assegnati: i loro nomi, scritti anche nella descrizione."""
    giorno = datetime.date.fromisoformat(giorno)
    if ora_inizio:
        inizio = datetime.datetime.combine(giorno, datetime.time.fromisoformat(ora_inizio))
        fine = inizio + datetime.timedelta(minutes=max(5, int(durata_minuti or 60)))
        tempi = {"start": {"dateTime": inizio.isoformat(), "timeZone": FUSO},
                 "end": {"dateTime": fine.isoformat(), "timeZone": FUSO}}
    else:
        tempi = {"start": {"date": giorno.isoformat()}, "end": {"date": (giorno + datetime.timedelta(days=1)).isoformat()}}
    privati = {k: str(v) for k, v in (collegamenti or {}).items() if v}
    if creato_da:
        privati["creato_da"] = creato_da
    if assegnati:
        privati["assegnati"] = ",".join(assegnati)
    righe = [descrizione.strip()] if descrizione.strip() else []
    if assegnati:
        righe.append(_riga_assegnati(nomi_assegnati or assegnati))
    if privati.get("cliente"):
        righe.append(f"Cliente: {privati['cliente']}")
    if privati.get("preventivo"):
        righe.append(f"Preventivo: {privati['preventivo']}")
    if creato_da:
        righe.append(f"Creato dal gestionale da {creato_da}")
    corpo = {"summary": titolo.strip(), "description": "\n".join(righe), "location": luogo.strip(),
             "extendedProperties": {"private": privati}, **tempi}
    ev = _api("POST", f"/calendars/{urllib.parse.quote(_id_calendario(), safe='')}/events", corpo=corpo)
    log(f"Appuntamento creato da {creato_da}: {titolo} {giorno}")
    return _evento_semplice(ev)


def assegna_evento(evento_id, assegnati, nomi_assegnati=None):
    """Cambia i colleghi assegnati a un appuntamento gia' esistente (dati privati + riga nella descrizione).
    Restituisce (assegnati di prima, evento aggiornato)."""
    percorso = f"/calendars/{urllib.parse.quote(_id_calendario(), safe='')}/events/{urllib.parse.quote(evento_id, safe='')}"
    ev = _api("GET", percorso)
    privati = dict((ev.get("extendedProperties") or {}).get("private") or {})
    prima = [u for u in (privati.get("assegnati") or "").split(",") if u]
    if assegnati:
        privati["assegnati"] = ",".join(assegnati)
    else:
        privati.pop("assegnati", None)
    righe = [r for r in (ev.get("description") or "").split("\n") if not r.startswith("Assegnato a: ")]
    if assegnati:
        righe.append(_riga_assegnati(nomi_assegnati or assegnati))
    corpo = {"description": "\n".join(righe).strip(),
             "extendedProperties": {**(ev.get("extendedProperties") or {}), "private": privati}}
    ev = _api("PATCH", percorso, corpo=corpo)
    log(f"Appuntamento {evento_id} assegnato a: {', '.join(assegnati) or 'nessuno'}")
    return prima, _evento_semplice(ev)
