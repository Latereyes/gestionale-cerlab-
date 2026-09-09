import os
import json
import glob
from models import SessionLocal, init_db, Cliente, Preventivo

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CLIENTI_DIR = os.path.join(BASE_DIR, 'data', 'clienti')
PREVENTIVI_DIR = os.path.join(BASE_DIR, 'data', 'preventivi')

def migrate():
    # Inizializza il database (crea le tabelle)
    init_db()
    
    session = SessionLocal()
    
    print("Inizio migrazione Clienti...")
    clienti_files = glob.glob(os.path.join(CLIENTI_DIR, "*.json"))
    clienti_aggiunti = 0
    
    for file_path in clienti_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Verifica se il cliente esiste già
                id_cliente = data.get('id_cliente')
                if not id_cliente:
                    continue
                    
                cliente = session.query(Cliente).filter_by(id_cliente=id_cliente).first()
                if not cliente:
                    cliente = Cliente(
                        id_cliente=id_cliente,
                        cliente=data.get('cliente', ''),
                        telefono=data.get('telefono', ''),
                        email=data.get('email', ''),
                        regione_nome=data.get('regione_nome', ''),
                        provincia=data.get('provincia', ''),
                        comune=data.get('comune', ''),
                        cap=data.get('cap', ''),
                        indirizzo=data.get('indirizzo', ''),
                        p_iva=data.get('p_iva', ''),
                        rag_sociale=data.get('rag_sociale', '')
                    )
                    session.add(cliente)
                    clienti_aggiunti += 1
        except Exception as e:
            print(f"Errore durante l'importazione del cliente {file_path}: {e}")
            
    session.commit()
    print(f"Migrati {clienti_aggiunti} clienti con successo.")
    
    print("\nInizio migrazione Preventivi...")
    preventivi_files = glob.glob(os.path.join(PREVENTIVI_DIR, "*.json"))
    preventivi_aggiunti = 0
    
    for file_path in preventivi_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                numero = data.get('numero')
                if not numero:
                    continue
                    
                preventivo = session.query(Preventivo).filter_by(numero=numero).first()
                if not preventivo:
                    preventivo = Preventivo(
                        numero=numero,
                        data=data.get('data', ''),
                        venditore=data.get('venditore', ''),
                        cliente=data.get('cliente', ''),
                        regione=str(data.get('regione', '')),
                        regione_nome=data.get('regione_nome', ''),
                        indirizzo=data.get('indirizzo', ''),
                        email=data.get('email', ''),
                        telefono=data.get('telefono', ''),
                        referente=data.get('referente', ''),
                        fee_pct=str(data.get('fee_pct', '')),
                        totale=str(data.get('totale', '')),
                        comune=data.get('comune', ''),
                        provincia=data.get('provincia', ''),
                        rag_sociale=data.get('rag_sociale', ''),
                        p_iva=data.get('p_iva', ''),
                        cap=data.get('cap', ''),
                        stato=data.get('stato', ''),
                        is_locked=data.get('is_locked', False),
                        id_cliente=data.get('id_cliente'),
                        
                        # Campi calcolati/aggregati
                        tot_imponibile_negozio=str(data.get('tot_imponibile_negozio', '')),
                        tot_imponibile_cliente=str(data.get('tot_imponibile_cliente', '')),
                        tot_iva=str(data.get('tot_iva', '')),
                        ricarico_medio_pct=str(data.get('ricarico_medio_pct', '')),
                        stato_consegna_globale=data.get('stato_consegna_globale', ''),
                        stato_pagamento_globale=data.get('stato_pagamento_globale', ''),
                        stato_fattura=data.get('stato_fattura', ''),
                        data_chiusura=data.get('data_chiusura', ''),
                        
                        # Campi JSON annidati
                        righe=data.get('righe', []),
                        ordini_fornitore=data.get('ordini_fornitore', []),
                        imponibili_iva=data.get('imponibili_iva', {}),
                        tot_iva_dettaglio=data.get('tot_iva_dettaglio', {}),
                        storico_pdf=data.get('storico_pdf', []),
                        pagamenti=data.get('pagamenti', []),
                        bolle=data.get('bolle', []),
                        fatture_allegate=data.get('fatture_allegate', [])
                    )
                    session.add(preventivo)
                    preventivi_aggiunti += 1
        except Exception as e:
            print(f"Errore durante l'importazione del preventivo {file_path}: {e}")
            
    session.commit()
    print(f"Migrati {preventivi_aggiunti} preventivi con successo.")
    
    session.close()
    print("\nMigrazione completata! I dati sono ora in data/gestionale.db")

if __name__ == '__main__':
    migrate()
