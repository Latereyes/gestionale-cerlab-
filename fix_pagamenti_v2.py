#!/usr/bin/env python3
"""
fix_pagamenti_v2.py
===================
Script ONE-SHOT di riallineamento per DB del cliente dopo migrazione V2->V3.

Problema: I preventivi piu' vecchi erano saldati con un sistema senza PAY ID.
Dopo la migrazione, aggiorna_stato_pagamento_globale() li ricalcola da zero
con pagamenti=[] e li segna "Da Saldare" erroneamente.

Fix applicati:
  1. Preventivo stato="Chiuso" => stato_pagamento_globale="Saldato" (sempre)
  2. Preventivo stato_pagamento_globale="Saldato" + pagamenti=[] + stato attivo
     => mantiene "Saldato" (era saldato nel sistema V2)
  3. Aggiunge PAY ID ai pagamenti vecchi che ne sono privi (migrazione retrocompatibilita')

IDEMPOTENTE: sicuro da rieseguire piu' volte.

Utilizzo:
  .venv\\Scripts\\python.exe fix_pagamenti_v2.py [percorso_db]
"""

import sys
import os
import re
import uuid

# --- Setup path ---
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Supporta percorso DB custom da argv
if len(sys.argv) > 1:
    db_custom = sys.argv[1]
    if os.path.isfile(db_custom):
        os.environ["GESTIONALE_DB_PATH"] = db_custom
        print(f"INFO: Uso DB custom: {db_custom}")

from models import SessionLocal, Preventivo

# --------------------------------------------------
# Helper
# --------------------------------------------------

def safe_money(val):
    if not val:
        return 0.0
    s = re.sub(r"[EUR\u20ac%\s]", "", str(val))
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0

def to_ita(f_val):
    return f"{f_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------
# Fix logica
# --------------------------------------------------

def fix_preventivo(prev):
    """
    Analizza e corregge un singolo preventivo.
    Ritorna (bool_modificato, str_motivo).
    """
    stato = prev.stato or ""
    stato_pag = prev.stato_pagamento_globale or ""
    pagamenti = list(prev.pagamenti or [])

    changes = []

    # 1. Aggiungi PAY ID mancanti (migrazione retrocompatibilita')
    pags_aggiornati = False
    for pag in pagamenti:
        if "id" not in pag and "pay_id" not in pag:
            pag["id"] = f"PAY-{uuid.uuid4().hex[:8].upper()}"
            pags_aggiornati = True
    if pags_aggiornati:
        prev.pagamenti = pagamenti
        changes.append("aggiunto PAY ID a pagamenti orfani")

    # 2. Preventivo "Chiuso" deve essere "Saldato"
    if stato == "Chiuso" and stato_pag != "Saldato":
        prev.stato_pagamento_globale = "Saldato"
        changes.append(f"Chiuso => Saldato (era: '{stato_pag}')")

    # 3. Gia' "Saldato" senza pagamenti registrati + stato attivo
    #    = vecchio preventivo V2 saldato prima dei PAY ID — nessun cambio necessario,
    #    ma loghiamo per conferma
    stati_attivi = {"Confermato", "In Lavorazione", "Chiuso"}
    if (stato_pag == "Saldato"
            and not pagamenti
            and stato in stati_attivi):
        changes.append("confermato Saldato V2 (pagamenti vuoti, stato attivo)")

    # 4. Caso critico: "Da Saldare" ma i pagamenti coprono il totale
    #    (errore di parsing formato numerico nella migrazione)
    if stato_pag == "Da Saldare" and stato in {"Confermato", "In Lavorazione"}:
        totale_dovuto = safe_money(prev.totale or "0")
        raw_no_iva = prev.no_iva
        is_no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")
        if is_no_iva:
            totale_dovuto = safe_money(prev.tot_imponibile_cliente or prev.totale or "0")

        totale_pagato = sum(
            safe_money(p.get("importo", "0"))
            for p in pagamenti
            if not p.get("is_scheduled")
        )
        da_saldare = totale_dovuto - totale_pagato
        if da_saldare <= 0.05:
            prev.stato_pagamento_globale = "Saldato"
            changes.append(f"ricalcolo: {totale_pagato:.2f}>={totale_dovuto:.2f} => Saldato")

    return bool(changes), " | ".join(changes)


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    print("=" * 70)
    print("FIX PAGAMENTI V2->V3 - Riallineamento DB")
    print("=" * 70)

    session = SessionLocal()
    try:
        prevs = session.query(Preventivo).all()
        print(f"Preventivi nel DB: {len(prevs)}")

        n_fixed = 0
        n_ok = 0
        log_fixed = []

        for prev in prevs:
            modified, motivo = fix_preventivo(prev)
            if modified:
                n_fixed += 1
                log_fixed.append((prev.numero, prev.cliente or "", prev.stato or "", motivo))
            else:
                n_ok += 1

        if n_fixed > 0:
            session.commit()
            print(f"\nFIX APPLICATI: {n_fixed} preventivi corretti\n")
            print(f"  {'Numero':<20} {'Cliente':<25} {'Stato':<18} Motivo")
            print(f"  {'-'*20} {'-'*25} {'-'*18} {'-'*30}")
            for num, cli, st, mot in log_fixed:
                cli_short = cli[:23]
                print(f"  {num:<20} {cli_short:<25} {st:<18} {mot}")
        else:
            print(f"\nNessun preventivo da correggere. DB gia' allineato.")

        print(f"\nPreventivi OK (invariati): {n_ok}")
        print(f"Preventivi corretti:       {n_fixed}")
        print("\nFix completato con successo.")

    except Exception as e:
        session.rollback()
        print(f"\nERRORE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()

    print("=" * 70)


if __name__ == "__main__":
    main()
