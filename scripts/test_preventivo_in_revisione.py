"""Test dell'etichetta "In revisione" (preventivo già confermato e riportato in Bozza/Inviato).
Gira su una cartella dati temporanea (APPDATA finto): non tocca i dati reali.
    python scripts/test_preventivo_in_revisione.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="gestionale_test_")
os.environ["APPDATA"] = TMP
os.environ["GESTIONALE_DB_PATH"] = os.path.join(TMP, "test.db")
sys.argv = ["gestionale.py"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gestionale as g  # noqa: E402

app = g.app
app.config["TESTING"] = True
ERRORI = []


def verifica(cond, msg):
    print(("  OK  " if cond else "  NO  ") + msg)
    if not cond:
        ERRORI.append(msg)


c = app.test_client()
with c.session_transaction() as s:
    s["user_id"], s["user_name"], s["user_role"], s["user_sigla"] = "admin", "Admin Prova", "amministratore", "AD"

CL = "CL-T1"
g.save_client(CL, {"id_cliente": CL, "cliente": "Cliente Prova", "rag_sociale": "Cliente Prova"})
base = {"id_cliente": CL, "cliente": "Cliente Prova", "data": "2026-11-01", "venditore": "Admin Prova"}
g.save_quote("PREV-REV", {**base, "numero": "PREV-REV", "stato": "Bozza", "data_conferma": "2026-11-05", "righe": []})
g.save_quote("PREV-NUOVO", {**base, "numero": "PREV-NUOVO", "stato": "Bozza", "righe": []})
g.save_quote("EDIL-REV", {**base, "numero": "EDIL-REV", "stato": "Inviato", "tipo_preventivo": "edile", "data_conferma": "2026-11-05",
                          "sezioni_edili": [{"titolo": "Lavori", "righe": [{"articolo": "Voce", "prezzo_vendita": "100"}]}]})
g.save_quote("PREV-CONF", {**base, "numero": "PREV-CONF", "stato": "Confermato", "data_conferma": "2026-11-05", "righe": []})


def pagina(url):
    r = c.get(url)
    return r.status_code, r.get_data(as_text=True)


print("1) Funzione badge")
verifica("In revisione" in g.badge_revisione(g.load_quote("PREV-REV")), "Bozza con data di conferma: In revisione")
verifica(g.badge_revisione(g.load_quote("PREV-NUOVO")) == "", "Bozza mai confermata: niente etichetta")
verifica(g.badge_revisione(g.load_quote("PREV-CONF")) == "", "Confermato: niente etichetta")

print("2) Editor")
st, h = pagina("/preventivo/edit/PREV-REV")
verifica(st == 200 and "In revisione" in h and "Confermato il 05/11/2026" in h, "editor commerciale: etichetta e data")
st, h = pagina("/preventivo/edit/PREV-NUOVO")
verifica(st == 200 and 'class="status-badge status-revisione"' not in h, "editor commerciale nuovo: nessuna etichetta")
st, h = pagina("/preventivo-edile/edit/EDIL-REV")
verifica(st == 200 and "In revisione" in h and "Riconferma" in h, "editor edile Inviato: etichetta e tasto Riconferma")

print("3) Elenchi")
for url in ("/cliente/dettaglio/" + CL, "/preventivi-cliente", "/preventivo/analisi/PREV-REV"):
    st, h = pagina(url)
    verifica(st == 200 and 'class="status-badge status-revisione"' in h, f"{url}: etichetta presente")

print("4) Conti: un preventivo in revisione resta nel venduto con la data della prima conferma")
import datetime  # noqa: E402
g.save_quote("REV-SOLDI", {**base, "numero": "REV-SOLDI", "stato": "Confermato", "data": "2026-09-20",
                           "data_conferma": "2026-10-03", "tot_imponibile_cliente": "1000", "tot_imponibile_negozio": "600",
                           "totale": "1220", "righe": [],
                           "pagamenti": [{"data": "2026-10-04", "importo": "500", "is_scheduled": False}]})
ottobre = (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
prima = g._calcola_dashboard_ceo(*ottobre)
p = g.load_quote("REV-SOLDI"); p["stato"] = "Bozza"; g.save_quote("REV-SOLDI", p)  # riportato in Bozza
dopo = g._calcola_dashboard_ceo(*ottobre)
verifica(prima["kpi"]["imponibile_totale"] == dopo["kpi"]["imponibile_totale"] and dopo["kpi"]["imponibile_totale"] >= 1000,
         f"venduto di ottobre invariato ({prima['kpi']['imponibile_totale']} -> {dopo['kpi']['imponibile_totale']})")
verifica(prima["cashflow"]["incassato_netto"] == dopo["cashflow"]["incassato_netto"] and dopo["cashflow"]["incassato_netto"] > 0,
         "incassato di ottobre invariato")
verifica(prima["funnel"]["confermati"] == dopo["funnel"]["confermati"], "conteggio confermati invariato")
verifica(dopo["funnel"]["valore_in_trattativa"] == prima["funnel"]["valore_in_trattativa"], "non finisce anche fra le trattative")
st, h = pagina("/cliente/analisi/" + CL)
verifica(st == 200, "Analisi cliente si apre")
verifica(any(p.get("numero") == "REV-SOLDI" for p, _ in g._preventivi_attivi_ceo()), "presente negli export Excel della direzione")
mai = {**base, "numero": "MAI-CONF", "stato": "Bozza", "data": "2026-10-10", "tot_imponibile_cliente": "777", "righe": []}
g.save_quote("MAI-CONF", mai)
verifica(not any(p.get("numero") == "MAI-CONF" for p, _ in g._preventivi_attivi_ceo()), "una Bozza mai confermata resta fuori")

print()
print("TUTTO OK" if not ERRORI else f"{len(ERRORI)} ERRORI")
sys.exit(1 if ERRORI else 0)
