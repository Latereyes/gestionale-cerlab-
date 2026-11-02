"""Test del registro attivita', della bozza di Ceerlo e del report automatico alla chiusura.
Gira su una cartella dati temporanea (APPDATA finto): non tocca i dati reali.
    python scripts/test_registro_report.py
"""
import datetime
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="gestionale_test_")
os.environ["APPDATA"] = TMP
os.environ["GESTIONALE_DB_PATH"] = os.path.join(TMP, "test.db")
sys.argv = ["gestionale.py"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gestionale as g  # noqa: E402
from models import SessionLocal, Utente, Report, RegistroAttivita  # noqa: E402

app = g.app
app.config["TESTING"] = True
ERRORI = []


def verifica(cond, msg):
    print(("  OK  " if cond else "  NO  ") + msg)
    if not cond:
        ERRORI.append(msg)


db = SessionLocal()
for u, nome, ruolo in (("anna", "Anna Prova", "venditore"), ("bruno", "Bruno Prova", "venditore"),
                       ("carla", "Carla Prova", "segreteria")):
    db.add(Utente(username=u, password_hash="x", full_name=nome, role=ruolo, sigla=u[:2].upper()))
db.commit()
db.close()


def client_di(utente, nome, ruolo):
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"], s["user_name"], s["user_role"], s["user_sigla"] = utente, nome, ruolo, utente[:2].upper()
    return c


anna = client_di("anna", "Anna Prova", "venditore")

print("1. Registro attivita' scritto dalle azioni")
r = anna.post("/cliente/crea", data={"cliente": "Mario Test", "action": "new_quote"})
verifica(r.status_code == 302, "cliente creato")
cliente_id = r.location.rstrip("/").split("/")[-1]
r = anna.get(f"/preventivo/nuovo/{cliente_id}")
verifica(r.status_code == 302 and "/edit/" in r.location, "preventivo creato")
quote_id = r.location.rstrip("/").split("/")[-1]
anna.post(f"/api/cliente/{cliente_id}/note", json={"note": "nota di prova"})
anna.post(f"/api/cliente/{cliente_id}/note", json={"note": "nota di prova 2"})
db = SessionLocal()
reg = [x.to_dict() for x in db.query(RegistroAttivita).filter_by(utente="anna").order_by(RegistroAttivita.id).all()]
db.close()
tipi = [x["tipo"] for x in reg]
verifica("cliente_nuovo" in tipi and "preventivo_nuovo" in tipi, f"registro con cliente e preventivo nuovi ({tipi})")
note = [x for x in reg if x["tipo"] == "cliente_modificato"]
verifica(len(note) == 1 and note[0]["volte"] == 2, "le modifiche ripetute nello stesso giorno fanno una voce sola")
verifica(any(f"#{quote_id}[Mario Test]" in x["testo"] for x in reg), "la voce ha il link #CODICE[nome]")

print("2. Bozza dal registro (Ceerlo spento) e con Ceerlo")
g.ceerlo.attivo = lambda cfg=None: False
d = anna.post("/api/report/bozza-ceerlo").get_json()
verifica(d["stato"] == "pronta", "senza Ceerlo la bozza riporta il registro")
lista = anna.get("/api/report").get_json()
verifica(lista["bozza"]["origine"] == "ceerlo" and all(v.get("registro") for v in lista["bozza"]["righe"]),
         "bozza segnata come generata, voci dal registro")
verifica(len(lista["registro"]) == len(reg), "la pagina riceve il registro")

g.ceerlo.attivo = lambda cfg=None: True
def finto_aggiungi(utente, messaggi, priorita, tipo, al_termine=None, chiave=""):
    al_termine(f"- Creato il cliente #{cliente_id}[Mario Test] e il preventivo #{quote_id}[Mario Test]\n- Aggiornate le note del cliente")
    return "job1"
g.ceerlo.aggiungi = finto_aggiungi
d = anna.post("/api/report/bozza-ceerlo").get_json()
lista = anna.get("/api/report").get_json()
righe = lista["bozza"]["righe"]
verifica(len(righe) == 2 and all(v.get("ai") for v in righe), "Ceerlo riscrive la bozza a voci col robottino")

r = anna.post("/api/report", json={"azione": "bozza", "righe": righe}).get_json()
verifica(r["report"]["origine"] == "ceerlo", "salvarla senza cambiarla la lascia 'di Ceerlo'")
cambiate = [dict(righe[0]), dict(righe[1], testo="Chiamato il cliente per il sopralluogo")]
r = anna.post("/api/report", json={"azione": "bozza", "righe": cambiate}).get_json()
voci = r["report"]["righe"]
verifica(r["report"]["origine"] == "", "cambiata dall'utente non e' piu' di Ceerlo")
verifica(voci[0].get("ai") and not voci[1].get("ai"), "il robottino resta solo sulla voce non toccata")
d = anna.post("/api/report/bozza-ceerlo").get_json()
verifica(d["stato"] == "occupata", "Ceerlo non sovrascrive la bozza dell'utente")
# torna una bozza di Ceerlo intatta per il test della chiusura
db = SessionLocal()
b = db.query(Report).filter_by(autore="anna", stato="bozza").first()
b.origine, b.righe = "ceerlo", righe
db.commit()
db.close()

print("3. Chiusura serale")
oggi = datetime.date.today()
ora_chiusura = datetime.datetime.combine(oggi, datetime.time(*map(int, g.integrazioni_google.ora_riepilogo().split(":"))))
# bruno ha lavorato e ha inviato il report a meta' giornata (turno); carla ha una bozza sua non inviata
g.scrivi_registro("bruno", "Bruno Prova", "incasso", "Registrato un pagamento sul preventivo #PREV-X[Rossi]",
                  "PREV-X", quando=f"{oggi} 08:30:00")
bruno = client_di("bruno", "Bruno Prova", "venditore")
bruno.post("/api/report", json={"azione": "invia", "righe": [{"testo": "Turno del mattino: incassi"}]})
g.scrivi_registro("carla", "Carla Prova", "consegna", "Segnata la merce consegnata (#PREV-Y[Verdi])",
                  "PREV-Y", quando=f"{oggi} 09:00:00")
carla = client_di("carla", "Carla Prova", "segreteria")
carla.post("/api/report", json={"azione": "bozza", "righe": [{"testo": "Consegna Verdi fatta, manca un pezzo"}]})

prima = g.chiudi_report_mancanti(ora_chiusura - datetime.timedelta(minutes=1))
verifica(prima == [], "prima dell'ora del riepilogo non parte nulla")
creati = {r["autore"]: r for r in g.chiudi_report_mancanti(ora_chiusura + datetime.timedelta(minutes=1))}
verifica(set(creati) == {"anna", "carla"}, f"report automatici per chi non l'ha inviato ({sorted(creati)})")
verifica(all(v.get("registro") and not v.get("ai") for v in creati["anna"]["righe"]),
         "bozza di Ceerlo non toccata: vale il registro, non il testo di Ceerlo")
verifica(creati["carla"]["righe"][0]["testo"].startswith("Consegna Verdi"), "bozza modificata dall'utente: vale la sua bozza")
db = SessionLocal()
verifica(db.query(Report).filter_by(autore="anna", stato="bozza").count() == 0, "la bozza di Ceerlo superata e' tolta")
bruno_rep = db.query(Report).filter_by(autore="bruno").all()
verifica(len(bruno_rep) == 1 and bruno_rep[0].origine == "", "il report gia' inviato (turno) non e' toccato")
db.close()
verifica(g.chiudi_report_mancanti(ora_chiusura + datetime.timedelta(minutes=2)) == [], "si puo' richiamare: nessun doppione")

print("4. Riepilogo serale")
reports = g.report_inviati_dal(f"{oggi} 00:00:00")
_, testo, html = g.componi_riepilogo(reports, f"{oggi} 00:00:00", ora_chiusura + datetime.timedelta(minutes=3), minuti_ceerlo=0)
verifica("dal registro attivit" in html and "dal registro attivit" in testo, "nell'email i report automatici sono segnati")
verifica(html.count("Report di ") >= 3, "nell'email ci sono i tre report")

print("5. I miei report: solo l'ultimo, gli archiviati a parte")
for i in range(3):
    time.sleep(1.1)  # la data dei report e' al secondo
    bruno.post("/api/report", json={"azione": "invia", "righe": [{"testo": f"report {i}"}]})
lista = bruno.get("/api/report").get_json()
verifica(len(lista["miei"]) == 1 and lista["miei"][0]["righe"][0]["testo"] == "report 2", "si vede solo l'ultimo report")
verifica(lista["miei_archiviati"] == 3, "gli altri sono contati come archiviati")
arch = bruno.get("/api/report/archivio?autore=bruno").get_json()
verifica(len(arch["reports"]) == 4, "gli archiviati sono nell'Archivio")

print("6. Note cliente a voci e riassunto di Ceerlo")
from models import Cliente  # noqa: E402
db = SessionLocal()
c = db.query(Cliente).filter_by(id_cliente=cliente_id).first()
c.note_voci, c.note_interne = [], "Preferisce il mattino\nHa un cane"
db.commit()
db.close()
d = anna.get(f"/api/cliente/{cliente_id}/note").get_json()
verifica([v["testo"] for v in d["voci"]] == ["Preferisce il mattino", "Ha un cane"], "le note di prima diventano una voce per riga")
d = anna.post(f"/api/cliente/{cliente_id}/note", json={"voci": d["voci"] + [{"testo": "Vuole la posa a dicembre"}]}).get_json()
verifica(d["voci"][-1]["autore"] == "anna" and not d["voci"][0]["autore"], "la voce nuova ha l'autore, le vecchie restano com'erano")
chiamate = []


def finto_aggiungi_note(utente, messaggi, priorita, tipo, al_termine=None, chiave=""):
    chiamate.append(chiave)
    al_termine("- Preferisce essere chiamato al mattino\n- Vuole la posa a dicembre")
    return "job-note"


g.ceerlo.aggiungi = finto_aggiungi_note
d = anna.get(f"/api/ceerlo/note-cliente/{cliente_id}").get_json()
verifica(d["stato"] == "in_coda" and len(chiamate) == 1, "la prima volta Ceerlo riassume le note")
d = anna.get(f"/api/ceerlo/note-cliente/{cliente_id}").get_json()
verifica(d["stato"] == "pronto" and "dicembre" in d["testo"] and len(chiamate) == 1, "poi il riassunto e' pronto senza richiederlo")
anna.post(f"/api/cliente/{cliente_id}/note", json={"voci": [{"testo": "Nuova nota"}]})
anna.get(f"/api/ceerlo/note-cliente/{cliente_id}")
verifica(len(chiamate) == 2, "se le note cambiano il riassunto si rifa'")
html = anna.get(f"/preventivo/edit/{quote_id}").get_data(as_text=True)
verifica('data-note-per="preventivo"' in html and f'data-cliente="{cliente_id}"' in html, "nell'editor del preventivo Ceerlo sa di quale cliente si tratta")

print("7. Note e cantieri nella pagina di consegna")
anna.post(f"/api/cliente/{cliente_id}/note", json={"voci": [{"testo": "Fa il rogito a febbraio, prima non puo' ricevere"}]})
risposte = {"consegna": "- Il materiale serve dopo il rogito di febbraio"}
def finto_consegna(utente, messaggi, priorita, tipo, al_termine=None, chiave=""):
    chiamate.append(chiave)
    al_termine(risposte["consegna"])
    return "job-consegna"
g.ceerlo.aggiungi = finto_consegna
anna.get(f"/api/ceerlo/note-cliente/{cliente_id}?per=consegna")
d = anna.get(f"/api/ceerlo/note-cliente/{cliente_id}?per=consegna").get_json()
verifica(d["stato"] == "pronto" and "febbraio" in d["testo"] and ":consegna:" in chiamate[-1], "per la consegna Ceerlo cerca quando serve il materiale")
anna.post(f"/cliente/{cliente_id}/salva-indirizzo-cantiere", data={"descrizione": "Casa al mare", "indirizzo": "Via del Porto 3", "comune": "Rimini", "provincia": "RN", "cap": "47921"})
risposte["consegna"] = "NIENTE"
anna.post(f"/api/cliente/{cliente_id}/note", json={"voci": [{"testo": "Cliente simpatico"}]})
anna.get(f"/api/ceerlo/note-cliente/{cliente_id}?per=consegna")
d = anna.get(f"/api/ceerlo/note-cliente/{cliente_id}?per=consegna").get_json()
verifica(d["stato"] == "pronto" and d["testo"] == "" and "Via del Porto 3" in d["cantieri"][0], "niente nelle note ma il cantiere salvato si segnala lo stesso")
html = anna.get(f"/consegna/{quote_id}").get_data(as_text=True)
verifica('data-note-per="consegna"' in html, "nella pagina di consegna il fumetto parla della consegna")

print("8. Richiesta admin: codici in chiaro e registro allegato")
richiesta = {"id": "SOS-1", "user_id": "anna", "user_name": "Anna Prova", "timestamp": "2026-11-02 17:00:00",
             "pagina": f"/preventivo/edit/{quote_id}",
             "description": f"Non riesco a salvare #{quote_id}[Mario Test], chiedi a @bruno"}
testo, html, allegati = g.componi_email_admin(richiesta)
verifica(f"Mario Test ({quote_id})" in testo and "Bruno Prova" in testo and "#" + quote_id + "[" not in testo,
         "nell'email codici e @ diventano nomi")
verifica(len(allegati) == 1 and allegati[0][0].endswith(".csv") and "Creato il preventivo" in allegati[0][1],
         "il registro attivita' dell'utente e' allegato")
verifica("500" not in allegati[0][1] or "[importo]" in allegati[0][1], "niente importi nell'allegato")
inviati = []


class FintoSMTP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def send_message(self, msg):
        inviati.append(msg)


g.integrazioni_google.smtplib.SMTP_SSL = FintoSMTP
g.integrazioni_google.leggi_config = lambda: {"email": {"mittente": "prova@example.com", "password": ""}}
g.integrazioni_google.svela = lambda x: "segreta"
ok, _ = g.integrazioni_google._manda(["admin@example.com"], "Prova", testo, html, allegati)
nomi = [part.get_filename() for part in inviati[0].iter_attachments()] if inviati else []
verifica(ok and nomi == [allegati[0][0]], "l'email parte con il file allegato")

print("\nCartella di prova:", TMP)
print("ERRORI:" if ERRORI else "Tutto ok.", *ERRORI, sep="\n  ")
sys.exit(1 if ERRORI else 0)
