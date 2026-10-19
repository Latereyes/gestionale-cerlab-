# Popolazione automatica del catalogo dai preventivi salvati.
# Stessa logica della bozza di catalogo (catalogo_bozza_v1): una riga per ogni riga di preventivo standard,
# costo = listino x (1-s1)(1-s2)(1-s3) + trasporto + spese (unitari), statistiche per articolo e sconti per marca.
# Il file del catalogo sta nella cartella dati (DATA_DIR/catalogo/catalogo.db), mai nel programma.
# Al salvataggio di un preventivo le sue righe vengono sostituite (nessun doppione se lo si salva piu' volte);
# i testi gia' visti vanno sull'articolo esistente, quelli nuovi creano un articolo "da verificare".
import json
import re
import sqlite3
import statistics
import collections
import threading

SCHEMA = """
create table if not exists articoli(id integer primary key, nome text, marca text, categoria text, unita text,
  listino_ultimo real, data_listino_ultimo text, preventivo_listino_ultimo text, listino_min real, listino_max real, n_listini_diversi int,
  sconti_ultimi text, costo_netto_ultimo real, trasporto_tipico real, spese_tipiche real,
  n_preventivi int, n_vendite int, prezzo_vendita_mediano real, prezzo_vendita_min real, prezzo_vendita_max real,
  ricarico_mediano_pct real, margine_mediano_pct real, data_ultima_vendita text,
  nomi_originali text, dubbio text, stato_bozza text);
create table if not exists condizioni_marca(marca text primary key, sconti_ultimi text, data_ultima text, preventivo_ultimo text,
  sconti_piu_usati text, quota_piu_usati_pct real, n_righe int, combinazioni text, trasporto_mq_tipico real, nota text);
create table if not exists righe(articolo_id int, preventivo text, data text, stato text, venduto int, articolo_originale text, unita text, qt real,
  listino real, s1 real, s2 real, s3 real, trasporto real, spese real, ricarico_pct real, costo real, prezzo_vendita real);
create table if not exists marche_alias(alias text primary key, marca text);
create table if not exists info(chiave text, valore text);
create index if not exists righe_preventivo on righe(preventivo);
create index if not exists righe_articolo on righe(articolo_id);
"""

_LOCK = threading.Lock()


def combo(r):
    return '+'.join(f"{x:g}" for x in (r['s1'] or 0, r['s2'] or 0, r['s3'] or 0))


def netto(listino, r):
    v = listino
    for k in ('s1', 's2', 's3'):
        if r[k]: v *= 1 - r[k] / 100
    return v


def num(v):
    """Converte un valore in formato italiano a float. Restituisce None se non convertibile."""
    if v is None:
        return None
    s = str(v).replace('%', '').replace('€', '').replace(' ', '')
    if not s:
        return None
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

def riga_catalogo(p, i, r, costi_magazzino):
    """Elabora una riga di catalogo da un preventivo."""
    # Pulizia articolo
    articolo = re.sub(r'\s+', ' ', (r.get("articolo") or "")).strip()
    qt = num(r.get("qt"))
    
    if not articolo or not qt or qt == 0:
        return None

    # Lettura dati principali
    vend = num(r.get("tot_prezzo_unitario"))
    ric = num(r.get("ricarico_pct")) or 0
    listino = num(r.get("prezzo_catalogo"))
    s1 = num(r.get("s1"))
    s2 = num(r.get("s2"))
    s3 = num(r.get("s3"))
    
    # Calcolo netto con sconti a cascata
    netto = listino or 0
    for s in (s1, s2, s3):
        if s is not None:
            netto *= (1 - s / 100)

    # Trasporto e spese
    tr = num(r.get("costo_trasporto")) or 0
    sp = num(r.get("spese_incasso")) or num(r.get("extra")) or 0
    
    unita = (r.get("unt") or "").upper().strip()
    
    # Trasporto per unità
    tr_q = tr if unita == "MQ" else tr / qt

    # Calcolo costo
    if netto > 0:
        costo = netto + tr_q + sp / qt
    elif vend:
        costo = vend / (1 + ric / 100)
    else:
        costo = 0

    # Override costo da magazzino
    id_art = r.get("id_articolo_magazzino")
    if id_art is not None:
        try:
            id_int = int(id_art)
            if id_int in costi_magazzino and costi_magazzino[id_int] > 0:
                costo = costi_magazzino[id_int] + tr_q + sp / qt
        except (ValueError, TypeError):
            pass

    venduto = p.get("stato") in ("Chiuso", "In Lavorazione", "Confermato")

    return {
        "preventivo": p.get("numero"),
        "data": p.get("data") or "",
        "stato": p.get("stato") or "",
        "venduto": venduto,
        "riga": i,
        "articolo": articolo,
        "unita": unita,
        "qt": qt,
        "listino": listino,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "trasporto": tr,
        "spese": sp,
        "ricarico_pct": ric,
        "costo": round(costo, 4),
        "prezzo_vendita": round(vend or 0, 4)
    }


def trova_o_crea_articolo(con, articolo, unita):
    # 1. Cerca in righe una riga con lower(articolo_originale) = lower(articolo)
    # Preferisci quelle con la stessa unita', poi la data piu' recente
    cur = con.execute(
        """
        SELECT articolo_id
        FROM righe
        WHERE lower(articolo_originale) = lower(?)
        ORDER BY
            CASE WHEN lower(unita) = lower(?) THEN 0 ELSE 1 END,
            data DESC
        LIMIT 1
        """,
        (articolo, unita)
    )
    row = cur.fetchone()
    if row:
        art_id = row['articolo_id']
        # Verifica che l'articolo esista ancora in articoli
        check = con.execute("SELECT 1 FROM articoli WHERE id = ?", (art_id,)).fetchone()
        if check:
            return art_id

    # 2. Cerca un articolo i cui nomi_originali (lista JSON) contengano il testo in minuscolo
    cur = con.execute("SELECT id, nomi_originali FROM articoli")
    art_lower = articolo.lower()
    for r in cur.fetchall():
        try:
            nomi = json.loads(r['nomi_originali']) if r['nomi_originali'] else []
        except (json.JSONDecodeError, TypeError):
            nomi = []
        for nome in nomi:
            if isinstance(nome, str) and nome.lower() == art_lower:
                return r['id']

    # 3. Crea un nuovo articolo
    # Riconoscimento marca: scorri marche_alias ordinate per lunghezza alias decrescente
    marca = None
    cur = con.execute("SELECT alias, marca FROM marche_alias ORDER BY length(alias) DESC")
    for r in cur.fetchall():
        alias = r['alias']
        if alias and len(alias) >= 3:
            # Regex con \b e re.escape per parola intera
            pattern = r'\b' + re.escape(alias.lower()) + r'\b'
            if re.search(pattern, articolo.lower()):
                marca = r['marca']
                break

    # Inserisci il nuovo articolo
    nomi_originali_json = json.dumps([articolo], ensure_ascii=False)
    cur = con.execute(
        """
        INSERT INTO articoli (
            nome, marca, categoria, unita,
            nomi_originali, n_preventivi, n_vendite,
            stato_bozza, dubbio
        )
        VALUES (?, ?, 'altro', ?, ?, 0, 0, 'da verificare', ?)
        """,
        (
            articolo,
            marca,
            unita,
            nomi_originali_json,
            'aggiunto in automatico da un preventivo: nome, marca e categoria da controllare'
        )
    )
    return cur.lastrowid


def ricalcola_articolo(con, articolo_id):
    # Recupero le righe ordinate e l'articolo corrente
    rs = con.execute("SELECT * FROM righe WHERE articolo_id=? ORDER BY data, preventivo", (articolo_id,)).fetchall()
    art = con.execute("SELECT * FROM articoli WHERE id=?", (articolo_id,)).fetchone()
    
    if not rs:
        con.execute("UPDATE articoli SET n_preventivi=0, n_vendite=0 WHERE id=?", (articolo_id,))
        return

    # Filtri e aggregazioni base
    con_listino = [r for r in rs if r['listino'] is not None and r['listino'] > 1.01]
    ult = con_listino[-1] if con_listino else None
    
    vend = [r for r in rs if r['venduto'] == 1 and r['prezzo_vendita'] > 0]
    aff = [r for r in vend if r['costo'] > 1.01]
    
    # Dati listino
    listino_ultimo = ult['listino'] if ult else None
    data_listino_ultimo = ult['data'] if ult else None
    preventivo_listino_ultimo = ult['preventivo'] if ult else None
    
    listini_valori = [r['listino'] for r in con_listino]
    listino_min = min(listini_valori) if listini_valori else None
    listino_max = max(listini_valori) if listini_valori else None
    n_listini_diversi = len(set(listini_valori))
    
    sconti_ultimi = combo(ult) if ult else None
    costo_netto_ultimo = round(netto(ult['listino'], ult), 2) if ult else None
    
    # Trasporto e spese tipici (mediana dei non nulli e non zero)
    trasporti = [r['trasporto'] for r in rs if r['trasporto'] is not None and r['trasporto'] != 0]
    spese = [r['spese'] for r in rs if r['spese'] is not None and r['spese'] != 0]
    trasporto_tipico = statistics.median(trasporti) if trasporti else None
    spese_tipiche = statistics.median(spese) if spese else None
    
    # Preventivi e vendite
    n_preventivi = len(set(r['preventivo'] for r in rs))
    n_vendite = len(vend)
    
    prezzi_vend = [r['prezzo_vendita'] for r in vend]
    prezzo_vendita_mediano = round(statistics.median(prezzi_vend), 2) if prezzi_vend else None
    prezzo_vendita_min = min(prezzi_vend) if prezzi_vend else None
    prezzo_vendita_max = max(prezzi_vend) if prezzi_vend else None
    
    # Ricarico mediano (None -> 0)
    ricarichi = [r['ricarico_pct'] if r['ricarico_pct'] is not None else 0 for r in con_listino]
    ricarico_mediano_pct = round(statistics.median(ricarichi), 1) if ricarichi else None
    
    # Margine mediano
    margini = [(r['prezzo_vendita'] - r['costo']) / r['prezzo_vendita'] * 100 for r in aff]
    margine_mediano_pct = round(statistics.median(margini), 1) if margini else None
    
    data_ultima_vendita = vend[-1]['data'] if vend else None
    
    # Nomi originali: unione con quelli esistenti
    nomi_esistenti = set()
    if art and art['nomi_originali']:
        try:
            nomi_esistenti = set(json.loads(art['nomi_originali']))
        except:
            pass
    nuovi_nomi = set(r['articolo_originale'] for r in rs if r['articolo_originale'])
    nomi_finali = sorted(nomi_esistenti | nuovi_nomi)
    nomi_originali = json.dumps(nomi_finali, ensure_ascii=False)
    
    # Update unico
    con.execute("""
        UPDATE articoli SET
            listino_ultimo=?, data_listino_ultimo=?, preventivo_listino_ultimo=?,
            listino_min=?, listino_max=?, n_listini_diversi=?,
            sconti_ultimi=?, costo_netto_ultimo=?,
            trasporto_tipico=?, spese_tipiche=?,
            n_preventivi=?, n_vendite=?,
            prezzo_vendita_mediano=?, prezzo_vendita_min=?, prezzo_vendita_max=?,
            ricarico_mediano_pct=?, margine_mediano_pct=?,
            data_ultima_vendita=?, nomi_originali=?
        WHERE id=?
    """, (
        listino_ultimo, data_listino_ultimo, preventivo_listino_ultimo,
        listino_min, listino_max, n_listini_diversi,
        sconti_ultimi, costo_netto_ultimo,
        trasporto_tipico, spese_tipiche,
        n_preventivi, n_vendite,
        prezzo_vendita_mediano, prezzo_vendita_min, prezzo_vendita_max,
        ricarico_mediano_pct, margine_mediano_pct,
        data_ultima_vendita, nomi_originali,
        articolo_id
    ))


def ricalcola_marca(con, marca):
    # Recupera le righe con listino vero per la marca, ordinate per data e preventivo
    rs = con.execute(
        """
        SELECT r.* FROM righe r
        JOIN articoli a ON a.id = r.articolo_id
        WHERE a.marca = ? AND r.listino > 1.01
        ORDER BY r.data, r.preventivo
        """,
        (marca,)
    ).fetchall()

    # Se non ci sono righe, cancella la riga della marca e ritorna
    if not rs:
        con.execute("DELETE FROM condizioni_marca WHERE marca = ?", (marca,))
        return

    # Conta le combinazioni di sconti
    c = collections.Counter(combo(r) for r in rs)
    top, ntop = c.most_common(1)[0]

    # Dati dell'ultima riga
    sconti_ultimi = combo(rs[-1])
    data_ultima = rs[-1]['data']
    preventivo_ultimo = rs[-1]['preventivo']

    # Statistiche sulle combinazioni
    sconti_piu_usati = top
    quota_piu_usati_pct = round(ntop / len(rs) * 100, 1)
    n_righe = len(rs)
    combinazioni = json.dumps(dict(c.most_common()), ensure_ascii=False)

    # Trasporto medio per MQ (mediana dei valori non zero)
    mq_trasporti = [r['trasporto'] for r in rs if r['unita'] == 'MQ' and r['trasporto'] is not None and r['trasporto'] != 0]
    trasporto_mq_tipico = statistics.median(mq_trasporti) if mq_trasporti else None

    # Costruzione della nota
    note = []
    if top == '0+0+0' and ntop / len(rs) >= 0.8:
        note.append("quasi sempre senza sconti: il prezzo scritto è probabilmente già il netto di acquisto")
    if len(c) > 1:
        note.append(f"{len(c)} combinazioni di sconto diverse: forse dipendono dalla linea o sono cambiate nel tempo")
    if combo(rs[-1]) != top:
        note.append("l'ultima combinazione usata è diversa dalla più frequente")
    nota = '; '.join(note)

    # Inserisci o sostituisci la riga in condizioni_marca
    con.execute(
        """
        INSERT OR REPLACE INTO condizioni_marca
        (marca, sconti_ultimi, data_ultima, preventivo_ultimo, sconti_piu_usati,
         quota_piu_usati_pct, n_righe, combinazioni, trasporto_mq_tipico, nota)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            marca,
            sconti_ultimi,
            data_ultima,
            preventivo_ultimo,
            sconti_piu_usati,
            quota_piu_usati_pct,
            n_righe,
            combinazioni,
            trasporto_mq_tipico,
            nota
        )
    )


def apri(db_path):
    """Connessione in scrittura; crea le tabelle se il file e' nuovo."""
    con = sqlite3.connect(str(db_path), timeout=10)
    con.row_factory = sqlite3.Row
    nuovo = not con.execute("select 1 from sqlite_master where name = 'articoli'").fetchone()
    con.executescript(SCHEMA)
    if nuovo:
        con.executemany("insert into info values (?, ?)", [
            ("stato", "catalogo creato in automatico dai preventivi salvati, da controllare"),
            ("listino", "prezzo_catalogo della riga piu' recente con listino vero (> 1 euro)"),
            ("sconti", "s1+s2+s3 a cascata; costo_netto_ultimo = listino x (1-s1)(1-s2)(1-s3), senza trasporto e spese"),
            ("prezzo_vendita", "tot_prezzo_unitario delle righe dei preventivi Chiuso / In Lavorazione / Confermato, IVA esclusa"),
            ("margine", "(prezzo - costo) / prezzo, costo = netto + trasporto + spese; solo righe vendute con costo attendibile")])
        con.commit()
    return con


def aggiorna_da_preventivo(db_path, p, costi_magazzino=None):
    """Sostituisce nel catalogo le righe del preventivo p e ricalcola articoli e marche toccati.
    Solo preventivi standard; restituisce il numero di righe scritte."""
    if not p or (p.get("tipo_preventivo") or "standard") != "standard" or not p.get("numero"):
        return 0
    righe = [x for i, r in enumerate(p.get("righe") or [])
             if isinstance(r, dict) and (x := riga_catalogo(p, i, r, costi_magazzino or {}))]
    with _LOCK:
        con = apri(db_path)
        try:
            # articoli che avevano righe di questo preventivo: vanno ricalcolati anche se ora non ne hanno piu'
            toccati = {r[0] for r in con.execute("select distinct articolo_id from righe where preventivo = ?", (p["numero"],))}
            # l'abbinamento si fa prima di cancellare, cosi' un preventivo gia' nel catalogo resta sugli stessi articoli
            abbinati = [(trova_o_crea_articolo(con, r["articolo"], r["unita"]), r) for r in righe]
            con.execute("delete from righe where preventivo = ?", (p["numero"],))
            for aid, r in abbinati:
                con.execute("insert into righe values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    aid, r["preventivo"], r["data"], r["stato"], int(r["venduto"]), r["articolo"], r["unita"], r["qt"],
                    r["listino"], r["s1"], r["s2"], r["s3"], r["trasporto"], r["spese"], r["ricarico_pct"], r["costo"],
                    r["prezzo_vendita"] or None))
                toccati.add(aid)
            marche = set()
            for aid in toccati:
                ricalcola_articolo(con, aid)
                m = con.execute("select marca from articoli where id = ?", (aid,)).fetchone()
                if m and m["marca"]:
                    marche.add(m["marca"])
            for m in marche:
                ricalcola_marca(con, m)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
    return len(righe)
