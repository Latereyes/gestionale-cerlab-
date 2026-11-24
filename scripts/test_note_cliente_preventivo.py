"""Test delle note: note cliente (visibili in tutti i preventivi del cliente) e note preventivo (solo su quel preventivo).
Gira su una cartella dati temporanea (APPDATA finto): non tocca i dati reali.
    python scripts/test_note_cliente_preventivo.py
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

CL, ALTRO = "CL-N1", "CL-N2"
g.save_client(CL, {"id_cliente": CL, "cliente": "Cliente Note", "rag_sociale": "Cliente Note"})
g.save_client(ALTRO, {"id_cliente": ALTRO, "cliente": "Altro", "rag_sociale": "Altro"})
base = {"id_cliente": CL, "cliente": "Cliente Note", "data": "2026-11-01", "venditore": "Admin Prova", "righe": []}
g.save_quote("P-A", {**base, "numero": "P-A", "stato": "Bozza"})
g.save_quote("P-B", {**base, "numero": "P-B", "stato": "Inviato"})
g.save_quote("P-X", {**base, "numero": "P-X", "id_cliente": ALTRO, "stato": "Bozza"})

# 1. Note scritte prima (testo libero, senza tipo) -> note cliente
db = g._DBSession()
cli = db.query(g._Cliente).filter_by(id_cliente=CL).first()
cli.note_interne, cli.note_voci = "• paga a 60 giorni\n• chiamare dopo le 17", []
db.commit(); db.close()
r = c.get(f"/api/cliente/{CL}/note?preventivo=P-A").get_json()
verifica(r["ok"] and [v["tipo"] for v in r["voci"]] == ["cliente", "cliente"], "le note vecchie diventano note cliente")
vecchie = r["voci"]

# 2. Dal preventivo P-A: aggiungo una nota preventivo (il numero lo mette il server)
r = c.post(f"/api/cliente/{CL}/note?preventivo=P-A", json={"voci": vecchie + [{"testo": "posa entro marzo", "tipo": "preventivo"}]}).get_json()
verifica(r["ok"], "salvataggio dal preventivo")
verifica(r["voci"][0]["tipo"] == "preventivo" and r["voci"][0]["preventivo"] == "P-A", "la nota preventivo va in cima, legata a P-A")
verifica(all(v.get("autore") == "" for v in r["voci"][1:]), "le note cliente invariate restano di chi le ha scritte")

# 3. P-B non vede la nota di P-A
r = c.get(f"/api/cliente/{CL}/note?preventivo=P-B").get_json()
verifica([v["testo"] for v in r["voci"]] == ["paga a 60 giorni", "chiamare dopo le 17"], "P-B vede solo le note cliente")

# 4. Salvando da P-B la nota di P-A non si perde
r = c.post(f"/api/cliente/{CL}/note?preventivo=P-B",
           json={"voci": r["voci"] + [{"testo": "colore grigio", "tipo": "preventivo", "preventivo": "P-A"}]}).get_json()
verifica(r["ok"] and r["voci"][0]["preventivo"] == "P-B", "da P-B la nota preventivo va comunque su P-B")
tutte = c.get(f"/api/cliente/{CL}/note").get_json()["voci"]
verifica({v["preventivo"] for v in tutte if v["tipo"] == "preventivo"} == {"P-A", "P-B"}, "cartella cliente: note di P-A e P-B entrambe presenti")
verifica([v["tipo"] for v in tutte] == ["preventivo", "preventivo", "cliente", "cliente"], "cartella cliente: note preventivo in cima")

# 5. Dalla cartella: nota preventivo con preventivo scelto; preventivo di un altro cliente rifiutato; senza preventivo rifiutata
r = c.post(f"/api/cliente/{CL}/note", json={"voci": tutte + [{"testo": "x", "tipo": "preventivo", "preventivo": "P-X"}]})
verifica(r.status_code == 400, "preventivo di un altro cliente rifiutato")
r = c.post(f"/api/cliente/{CL}/note", json={"voci": tutte + [{"testo": "x", "tipo": "preventivo"}]})
verifica(r.status_code == 400, "nota preventivo senza preventivo rifiutata")
r = c.get(f"/api/cliente/{CL}/note?preventivo=P-X")
verifica(r.status_code == 400, "?preventivo di un altro cliente rifiutato")
# cambio solo il tipo: P-A -> nota cliente, l'autore resta
prima = next(v for v in tutte if v["preventivo"] == "P-A")
mod = [dict(v, tipo="cliente", preventivo="") if v["id"] == prima["id"] else v for v in tutte]
r = c.post(f"/api/cliente/{CL}/note", json={"voci": mod}).get_json()
cambiata = next(v for v in r["voci"] if v["id"] == prima["id"])
verifica(cambiata["tipo"] == "cliente" and cambiata["quando"] == prima["quando"], "cambio di tipo: resta autore e data")

# 5b. salvataggio automatico: una nota nuova tiene l'id scelto dal browser; un id gia' usato viene cambiato
tutte = c.get(f"/api/cliente/{CL}/note").get_json()["voci"]
r = c.post(f"/api/cliente/{CL}/note", json={"voci": tutte + [{"id": "abc12345", "testo": "nota auto", "tipo": "cliente"}]}).get_json()
verifica(any(v["id"] == "abc12345" and v["testo"] == "nota auto" for v in r["voci"]), "nota nuova: resta l'id del browser")
r = c.post(f"/api/cliente/{CL}/note", json={"voci": r["voci"] + [{"id": "abc12345", "testo": "copia", "tipo": "cliente"}]}).get_json()
verifica(len({v["id"] for v in r["voci"]}) == len(r["voci"]), "id doppio: la nota nuova prende un id diverso")
r = c.post(f"/api/cliente/{CL}/note", json={"voci": [v for v in r["voci"] if v["testo"] not in ("nota auto", "copia")]}).get_json()

# 6. note_interne (Ceerlo, ricerche): numero del preventivo davanti
db = g._DBSession()
testo = db.query(g._Cliente).filter_by(id_cliente=CL).first().note_interne
db.close()
verifica("• [P-B] colore grigio" in testo and "• paga a 60 giorni" in testo, "note_interne con il numero del preventivo")

# 7. Pagine: pulsante Note nel preventivo e nella cartella cliente (con l'elenco dei preventivi)
pagina = c.get(f"/cliente/dettaglio/{CL}")
html = pagina.get_data(as_text=True)
verifica(pagina.status_code == 200 and 'id="noteClientePanel"' in html and '"P-A"' in html, "cartella cliente: pannello Note con i preventivi")

print()
print("TUTTO OK" if not ERRORI else f"{len(ERRORI)} ERRORI")
sys.exit(1 if ERRORI else 0)
