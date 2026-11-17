"""Test della scelta "Prezzi nel preventivo stampato" dei preventivi edili.
Gira su una cartella dati temporanea (APPDATA finto): non tocca i dati reali.
    python scripts/test_prezzi_stampa_edile.py
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

Q = "EDIL-TEST-1"
g.save_quote(Q, {
    "numero": Q, "cliente": "Cliente Prova", "stato": "Bozza", "tipo_preventivo": "edile", "data": "2026-11-17",
    "sezioni_edili": [
        {"titolo": "Demolizioni", "righe": [
            {"articolo": "Rimozione pavimento", "prezzo_vendita": "1200,50", "iva_pct": "10"},
            {"articolo": "Smaltimento macerie", "prezzo_vendita": "300", "iva_pct": "10"},
        ]},
        {"titolo": "Pavimenti", "righe": [
            {"articolo": "Posa gres", "prezzo_vendita": "2.000,00", "iva_pct": "10"},
        ]},
    ],
})


def stampa():
    return c.get(f"/stampa-html/{Q}").get_data(as_text=True)


print("1) Preventivo esistente, nessuna scelta salvata")
h = stampa()
corpo = h.split("</style>")[-1]
verifica('class="section-total"' not in corpo and 'class="row-price"' not in corpo, "solo totale finale, come prima")
verifica('value="totale" selected' in c.get(f"/preventivo-edile/edit/{Q}").get_data(as_text=True), "editor propone 'Solo totale finale'")


def salva(scelta):
    p = g.load_quote(Q)
    form = {"is_ajax": "1", "is_locked": "false", "data": p["data"], "riepilogo": "", "prezzi_stampa_edile": scelta}
    for si, s in enumerate(p["sezioni_edili"]):
        form[f"s[{si}][titolo]"] = s["titolo"]
        for ri, r in enumerate(s["righe"]):
            for k, v in r.items():
                form[f"s[{si}][r][{ri}][{k}]"] = v
    r = c.post(f"/salva-righe-edili/{Q}", data=form)
    return r.status_code


print("2) Totale di ogni sezione")
verifica(salva("sezioni") == 200, "salvataggio ok")
verifica(g.load_quote(Q).get("prezzi_stampa_edile") == "sezioni", "scelta salvata nel preventivo")
h = stampa()
corpo = h.split("</style>")[-1]
verifica("1500,50 €" in corpo and "2000,00 €" in corpo, "totali di sezione 1500,50 e 2000,00")
verifica('class="row-price"' not in corpo and "1200,50" not in corpo, "prezzi delle voci nascosti")

print("3) Prezzo di ogni voce + totale sezione")
salva("voci")
corpo = stampa().split("</style>")[-1]
verifica("1200,50 €" in corpo and "300,00 €" in corpo and "1500,50 €" in corpo, "prezzi voce e totale sezione presenti")
verifica('value="voci" selected' in c.get(f"/preventivo-edile/edit/{Q}").get_data(as_text=True), "editor ricorda la scelta")

print("4) Valore non valido o campo assente non cambia la scelta")
salva("boh")
verifica(g.load_quote(Q).get("prezzi_stampa_edile") == "voci", "scelta invariata")

print("5) Torno a solo totale")
salva("totale")
corpo = stampa().split("</style>")[-1]
verifica('class="section-total"' not in corpo and 'class="row-price"' not in corpo, "di nuovo solo totale finale")

print()
print("TUTTO OK" if not ERRORI else f"{len(ERRORI)} ERRORI")
sys.exit(1 if ERRORI else 0)
