import os
import sys

# Aggiungiamo la root del progetto al PYTHONPATH per poter importare models
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models import SessionLocal, Preventivo, Ordine, Bolla

def migrate_ordini_and_bolle():
    session = SessionLocal()
    preventivi = session.query(Preventivo).all()
    ordini_aggiunti = 0
    bolle_aggiunte = 0

    print(f"Trovati {len(preventivi)} preventivi nel DB.")

    for p in preventivi:
        # Migra Ordini
        ordini_json = p.ordini_fornitore or []
        for o_dict in ordini_json:
            # Controlla se esiste già
            if o_dict.get("ordine_id") and not session.query(Ordine).filter_by(ordine_id=o_dict["ordine_id"]).first():
                nuovo_ordine = Ordine(
                    ordine_id=o_dict["ordine_id"],
                    preventivo_id=p.numero,
                    data_ordine=o_dict.get("data_ordine", ""),
                    azienda=o_dict.get("azienda", ""),
                    numero_conferma=o_dict.get("numero_conferma", ""),
                    importo=o_dict.get("importo", ""),
                    importo_articoli=o_dict.get("importo_articoli", ""),
                    importo_trasporto=o_dict.get("importo_trasporto", ""),
                    iva_ordine=o_dict.get("iva_ordine", 0.0),
                    data_arrivo=o_dict.get("data_arrivo", ""),
                    indici_righe=o_dict.get("indici_righe", [])
                )
                session.add(nuovo_ordine)
                ordini_aggiunti += 1
        
        # Migra Bolle
        bolle_json = p.bolle or []
        for b_dict in bolle_json:
            if b_dict.get("id") and not session.query(Bolla).filter_by(id=b_dict["id"]).first():
                nuova_bolla = Bolla(
                    id=b_dict["id"],
                    preventivo_id=p.numero,
                    data=b_dict.get("data", ""),
                    indirizzo_cantiere_id=b_dict.get("indirizzo_cantiere_id", ""),
                    indici_righe=b_dict.get("indici_righe", [])
                )
                session.add(nuova_bolla)
                bolle_aggiunte += 1

    try:
        session.commit()
        print(f"Migrazione completata con successo! Aggiunti {ordini_aggiunti} ordini e {bolle_aggiunte} bolle.")
    except Exception as e:
        session.rollback()
        print(f"Errore durante la migrazione: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    migrate_ordini_and_bolle()
