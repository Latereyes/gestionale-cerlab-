"""Test dei DDT (dati del documento di trasporto) e delle consegne parziali.
Gira su una cartella dati temporanea (APPDATA finto): non tocca i dati reali.
    python scripts/test_ddt_consegna_parziale.py
"""
import io
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="gestionale_test_")
os.environ["APPDATA"] = TMP
os.environ["GESTIONALE_DB_PATH"] = os.path.join(TMP, "test.db")
sys.argv = ["gestionale.py"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gestionale as g  # noqa: E402
from models import SessionLocal, Utente, ArticoloMagazzino  # noqa: E402

app = g.app
app.config["TESTING"] = True
ERRORI = []


def verifica(cond, msg):
    print(("  OK  " if cond else "  NO  ") + msg)
    if not cond:
        ERRORI.append(msg)


db = SessionLocal()
db.add(Utente(username="carla", password_hash="x", full_name="Carla Prova", role="segreteria", sigla="CA"))
art = ArticoloMagazzino(codice="M1", descrizione="Collante", unita="PZ", giacenza=20.0, costo=5.0)
db.add(art)
db.commit()
ID_ART = art.id
db.close()

c = app.test_client()
with c.session_transaction() as s:
    s["user_id"], s["user_name"], s["user_role"], s["user_sigla"] = "carla", "Carla Prova", "segreteria", "CA"

Q = "PREV-TEST-1"
g.save_quote(Q, {
    "numero": Q, "id_cliente": "CL-1", "cliente": "Mario Rossi", "rag_sociale": "Rossi Srl", "p_iva": "01234567890",
    "indirizzo": "Via Roma 1", "cap": "04011", "comune": "Aprilia", "provincia": "LT",
    "stato": "Confermato", "tipo_preventivo": "standard", "data": "2026-11-01",
    "righe": [
        {"articolo": "Gres 60x60", "unt": "MQ", "qt": "100", "stato_consegna": "Pronto per Consegna", "data_arrivo_in_house": "2026-11-05"},
        {"articolo": "Battiscopa", "unt": "PZ", "qt": "40", "stato_consegna": "Pronto per Consegna", "data_arrivo_in_house": "2026-11-05"},
        {"articolo": "Collante", "unt": "PZ", "qt": "10", "id_articolo_magazzino": str(ID_ART),
         "stato_consegna": "Pronto per Consegna", "data_arrivo_in_house": "2026-11-05"},
    ],
    "ordini_fornitore": [{"ordine_id": "O1", "numero_conferma": "C-1", "azienda": "Fornitore", "indici_righe": [0, 1]}],
})


def righe():
    return g.load_quote(Q)["righe"]


def giacenza():
    d = SessionLocal()
    try:
        return d.get(ArticoloMagazzino, ID_ART).giacenza
    finally:
        d.close()


def consegna(indici):
    data = {"selected_items[]": [str(i) for i in indici],
            "file": (io.BytesIO(b"%PDF-firmato"), "firmata.pdf")}
    return c.post(f"/consegna/{Q}/marca-consegnato", data=data, content_type="multipart/form-data").get_json()


print("1. Pagina consegna con il modulo DDT")
r = c.get(f"/consegna/{Q}")
html = r.get_data(as_text=True)
verifica(r.status_code == 200, "pagina consegna aperta")
verifica('id="ddt-modal"' in html and 'name="ddt_causale"' in html and 'id="ddt-parziale"' in html,
         "modulo DDT con spunta 'Consegna parziale'")
verifica('name="ddt_numero" value="1"' in html, "primo numero DDT proposto: 1")

print("2. Quantita' non valida rifiutata")
r = c.post(f"/consegna/{Q}/crea-bolla", data={"selected_items[]": ["0"], "parziale": "1", "qt_0": "150"}).get_json()
verifica(not r["success"] and "Quantità non valida" in r["error"], "150 mq su 100 rifiutati")
verifica(not g.load_quote(Q).get("bolle"), "nessuna bolla creata")

print("3. DDT parziale: 30 mq di gres, 10 di 40 battiscopa, 4 di 10 collante dal magazzino")
r = c.post(f"/consegna/{Q}/crea-bolla", data={
    "selected_items[]": ["0", "1", "2"], "parziale": "1", "qt_0": "30", "qt_1": "10", "qt_2": "4",
    "ddt_numero": "", "ddt_causale": "Vendita", "ddt_trasporto_a_cura": "Vettore",
    "ddt_vettore": "Trasporti Bianchi Srl, Latina", "ddt_conducente": "Luca Verdi", "ddt_targa": "AB123CD",
    "ddt_aspetto_beni": "Bancali", "ddt_n_colli": "3", "ddt_peso_kg": "1200", "ddt_annotazioni": "Scarico a cura del cliente",
}).get_json()
verifica(r["success"], "bolla creata")
p = g.load_quote(Q)
b1 = p["bolle"][0]
verifica(b1.get("numero_ddt") == "1" and b1.get("anno_ddt"), "DDT numero 1 dell'anno")
verifica(b1.get("causale") == "Vendita" and b1.get("vettore") == "Trasporti Bianchi Srl, Latina"
         and b1.get("n_colli") == "3" and b1.get("peso_kg") == "1200" and b1.get("targa") == "AB123CD",
         "dati del DDT salvati sulla bolla")
verifica(b1.get("quantita") == {"0": "30", "1": "10", "2": "4"} and b1.get("parziale") is True, "quantita' della bolla salvate")
verifica(all(x["stato_consegna"] == "In Bolla" for x in p["righe"]) and p["righe"][0]["qt_bolla"] == "30",
         "righe in bolla con la quantita' parziale")

print("4. Stampa del DDT")
r = c.get(f"/stampa-bolla-html/{Q}/{b1['id']}")
html = r.get_data(as_text=True)
verifica(r.status_code == 200 and "Documento di Trasporto" in html, "stampa DDT")
for testo in ("Causale del trasporto", "Trasporto a cura del", "Vettore", "Conducente", "Targa",
              "Aspetto esteriore dei beni", "N. colli", "Peso (kg)", "Data inizio trasporto", "Ora",
              "Annotazioni", "Firma del conducente", "Firma del destinatario", "Luogo di destinazione",
              "P.IVA / C.F.: 01234567890", "Trasporti Bianchi Srl, Latina", "Luca Verdi", "AB123CD"):
    verifica(testo in html, f"stampa contiene «{testo}»")
verifica("<strong>30</strong>" in html and "<strong>10</strong>" in html, "in stampa le quantita' consegnate, non quelle ordinate")
verifica("Consegna parziale: 30 di 100 MQ, restano 70 MQ da consegnare" in html, "nota di consegna parziale sulla riga")
verifica("CONSEGNA PARZIALE" in html, "avviso di consegna parziale")
verifica(">Porto<" not in html, "niente campo Porto (consegne su gomma in ambito nazionale)")

print("5. Consegna della bolla parziale: la rimanenza resta in attesa")
verifica(consegna([0, 1, 2])["success"], "consegna registrata")
rr = righe()
verifica(rr[0]["stato_consegna"] == "Pronto per Consegna" and rr[0]["qt_consegnata"] == "30"
         and not rr[0].get("bolla_id") and not rr[0].get("qt_bolla"), "gres: consegnati 30, 70 in attesa di consegna")
verifica(rr[0]["consegne"][0]["bolla_id"] == b1["id"] and rr[0]["consegne"][0]["qt"] == "30", "storico della consegna sulla riga")
verifica(giacenza() == 16, f"magazzino: scaricati solo 4 pezzi (giacenza {giacenza()})")
p = g.load_quote(Q)
verifica(p["stato_consegna_globale"] == "Parziale", "stato consegna globale: Parziale")
html = c.get(f"/consegna/{Q}").get_data(as_text=True)
verifica("Parz. consegnato" in html and "consegnati 30" in html, "pagina consegna mostra la consegna parziale")
verifica('name="ddt_numero" value="2"' in html, "numero DDT successivo proposto: 2")

print("6. Numero DDT gia' usato rifiutato")
r = c.post(f"/consegna/{Q}/crea-bolla", data={"selected_items[]": ["0"], "ddt_numero": "1"}).get_json()
verifica(not r["success"] and "esiste già" in r["error"], "DDT n. 1 doppio rifiutato")

print("7. Secondo DDT senza spunta: va tutto il residuo (saldo)")
r = c.post(f"/consegna/{Q}/crea-bolla", data={"selected_items[]": ["0", "1", "2"]}).get_json()
verifica(r["success"], "seconda bolla creata")
b2 = g.load_quote(Q)["bolle"][1]
verifica(b2["numero_ddt"] == "2" and b2["quantita"] == {"0": "70", "1": "30", "2": "6"} and not b2["parziale"],
         "DDT 2 con le rimanenze")
html = c.get(f"/stampa-bolla-html/{Q}/{b2['id']}").get_data(as_text=True)
verifica("Saldo consegna: 70 di 100 MQ" in html, "nota 'saldo consegna' in stampa")
verifica(consegna([0, 1, 2])["success"], "seconda consegna registrata")
rr = righe()
verifica(all(x["stato_consegna"] == "Consegnato" for x in rr) and rr[0]["qt_consegnata"] == "100", "tutto consegnato")
verifica(giacenza() == 10, f"magazzino: scaricati 10 in totale (giacenza {giacenza()})")
verifica(g.load_quote(Q)["stato_consegna_globale"] == "Completato", "stato consegna globale: Completato")

print("8. Annulla l'ultima consegna del collante: torna In Bolla nel DDT 2, 6 pezzi tornano in giacenza")
r = c.post(f"/consegna/{Q}/annulla-stato", data={"target_status": "annulla_ultima_consegna", "keep_bolla": "true",
                                                 "indices[]": ["2"]}).get_json()
verifica(r["success"], "annullo eseguito")
x = righe()[2]
verifica(x["stato_consegna"] == "In Bolla" and x["bolla_id"] == b2["id"] and x["qt_consegnata"] == "4", "collante di nuovo nel DDT 2")
verifica(giacenza() == 16, f"giacenza tornata a 16 ({giacenza()})")
verifica(consegna([2])["success"] and righe()[2]["stato_consegna"] == "Consegnato" and giacenza() == 10, "riconsegnato")

print("9. Annulla la consegna del battiscopa riportandolo a 'Pronto' senza bolla")
r = c.post(f"/consegna/{Q}/annulla-stato", data={"target_status": "Pronto per Consegna", "keep_bolla": "false",
                                                 "indices[]": ["1"]}).get_json()
x = righe()[1]
verifica(r["success"] and x["stato_consegna"] == "Pronto per Consegna" and x["qt_consegnata"] == "10"
         and not x.get("bolla_id"), "battiscopa: restano consegnati i 10 del DDT 1, 30 di nuovo da consegnare")
b2 = g.load_quote(Q)["bolle"][1]
verifica(1 not in b2["indici_righe"] and "1" not in b2["quantita"], "battiscopa tolto dal DDT 2")

print("10. Annulla anche la consegna parziale del battiscopa")
r = c.post(f"/consegna/{Q}/annulla-stato", data={"target_status": "annulla_ultima_consegna", "keep_bolla": "true",
                                                 "indices[]": ["1"]}).get_json()
x = righe()[1]
verifica(r["success"] and x["stato_consegna"] == "In Bolla" and x["bolla_id"] == b1["id"]
         and x["qt_bolla"] == "10" and not x.get("qt_consegnata"), "battiscopa di nuovo nel DDT 1 per 10 pezzi")

print("11. Prenotazioni di magazzino con consegna parziale")
g.save_quote("PREV-TEST-2", {
    "numero": "PREV-TEST-2", "cliente": "Anna", "stato": "Confermato", "tipo_preventivo": "standard",
    "righe": [{"articolo": "Collante", "unt": "PZ", "qt": "8", "id_articolo_magazzino": str(ID_ART),
               "magazzino_scaricato": "3", "qt_consegnata": "3", "stato_consegna": "Pronto per Consegna"}]})
pren = g.calcola_prenotazioni_magazzino().get(ID_ART, {})
verifica(abs(pren.get("qt", 0) - 5) < 1e-9, f"prenotati solo i 5 pezzi non ancora consegnati ({pren.get('qt')})")

print("12. Bolle vecchie (senza dati DDT) si stampano ancora")
g.save_quote("PREV-TEST-3", {
    "numero": "PREV-TEST-3", "cliente": "Vecchio", "stato": "Confermato", "tipo_preventivo": "standard",
    "righe": [{"articolo": "Mattoni", "unt": "PZ", "qt": "5", "stato_consegna": "In Bolla", "bolla_id": "BOLLA-2025-1"}],
    "bolle": [{"id": "BOLLA-2025-1", "data": "2025-05-02", "indici_righe": [0]}]})
html = c.get("/stampa-bolla-html/PREV-TEST-3/BOLLA-2025-1").get_data(as_text=True)
verifica("BOLLA-2025-1" in html and "<strong>5</strong>" in html and "02/05/2025" in html, "bolla vecchia stampata")
verifica(consegna.__name__ and c.post("/consegna/PREV-TEST-3/marca-consegnato", data={
    "selected_items[]": ["0"], "file": (io.BytesIO(b"x"), "f.pdf")}, content_type="multipart/form-data").get_json()["success"]
    and g.load_quote("PREV-TEST-3")["righe"][0]["stato_consegna"] == "Consegnato", "bolla vecchia consegnata per intero")

print("13. DDT per ritiro in negozio")
g.save_quote("PREV-TEST-4", {
    "numero": "PREV-TEST-4", "id_cliente": "CL-4", "cliente": "Paolo", "stato": "Confermato", "tipo_preventivo": "standard",
    "righe": [{"articolo": "Piastrelle 20x20", "unt": "MQ", "qt": "12", "stato_consegna": "Pronto per Consegna"}],
    "ordini_fornitore": [{"ordine_id": "O4", "numero_conferma": "C-4", "azienda": "F", "indici_righe": [0]}]})
r = c.post("/consegna/PREV-TEST-4/crea-bolla", data={
    "selected_items[]": ["0"], "ritiro_negozio": "1", "ddt_ritirato_da": "Paolo Neri",
    "ddt_vettore": "da ignorare", "ddt_trasporto_a_cura": "Mittente", "ddt_causale": "Vendita"}).get_json()
b4 = g.load_quote("PREV-TEST-4")["bolle"][0]
verifica(r["success"] and b4.get("ritiro_negozio") is True and b4.get("trasporto_a_cura") == "Destinatario"
         and b4.get("ritirato_da") == "Paolo Neri" and "vettore" not in b4, "ritiro salvato senza vettore, a cura del destinatario")
html = c.get(f"/stampa-bolla-html/PREV-TEST-4/{b4['id']}").get_data(as_text=True)
for testo in ("Ritiro in negozio a cura del cliente", "Paolo Neri", "Firma di chi ritira", "Data ritiro", "Ora ritiro"):
    verifica(testo in html, f"stampa ritiro contiene «{testo}»")
verifica("Firma del conducente" not in html and "Targa" not in html, "niente conducente/targa nel ritiro")

print()
if ERRORI:
    print(f"FALLITI {len(ERRORI)} controlli")
    sys.exit(1)
print("Tutti i controlli superati.")
