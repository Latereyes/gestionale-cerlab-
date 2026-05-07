import pandas as pd
import json
import os
from pathlib import Path
import math

# Importiamo le funzioni che abbiamo già creato in gestionale.py
# In questo modo, usiamo la stessa logica per creare gli ID e salvare i file.
try:
    from gestionale import get_new_client_id, save_client, CLIENTS_DIR
except ImportError:
    print("ERRORE: Assicurati che 'importa_clienti.py' si trovi nella stessa cartella di 'gestionale.py'")
    exit()

# --- CONFIGURAZIONE ---
EXCEL_FILE_PATH = "clienti.xlsx"
# Mappatura tra i nomi delle colonne in Excel (in MAIUSCOLO) e le chiavi nel nostro JSON.
COLUMN_MAPPING = {
    'CLIENTE': 'cliente',
    'TELEFONO': 'telefono',
    'EMAIL': 'email',
    'REGIONE': 'regione_nome', # Salviamo il nome, non il codice
    'PROVINCIA': 'provincia',
    'COMUNE': 'comune',
    'CAP': 'cap',
    'INDIRIZZO': 'indirizzo',
    'P.IVA': 'p_iva'
}

def import_clients():
    print("--- Avvio dello script di importazione clienti ---")

    # 1. Controlla se il file Excel esiste
    if not os.path.exists(EXCEL_FILE_PATH):
        print(f"ERRORE: File '{EXCEL_FILE_PATH}' non trovato. Assicurati che sia nella stessa cartella dello script.")
        return

    # 2. Leggi il file Excel con Pandas
    try:
        # Usiamo 'str' come tipo di dato per evitare che Pandas interpreti male CAP o P.IVA
        df = pd.read_excel(EXCEL_FILE_PATH, dtype=str)
        print(f"Trovate {len(df)} righe nel file Excel.")
    except Exception as e:
        print(f"ERRORE durante la lettura del file Excel: {e}")
        return

    # 3. Scorri ogni riga e crea un file JSON per ogni cliente
    imported_count = 0
    skipped_count = 0

    for index, row in df.iterrows():
        # Prepara la struttura dati per il nuovo cliente
        client_data = {}
        
        # Mappa i dati dall'Excel al nostro formato JSON
        for excel_col, json_key in COLUMN_MAPPING.items():
            value = row.get(excel_col)
            # Pulisce i dati: se un valore è "NaN" (Not a Number), lo trasforma in stringa vuota
            if pd.isna(value):
                client_data[json_key] = ""
            else:
                client_data[json_key] = str(value).strip()

        # Controlla se il campo obbligatorio 'cliente' è presente
        if not client_data.get('cliente'):
            print(f"ATTENZIONE: Riga {index + 2} saltata perché il campo 'CLIENTE' è vuoto.")
            skipped_count += 1
            continue

        # Applica la regola di business: se c'è P.IVA, ragione sociale = cliente
        if client_data.get('p_iva'):
            client_data['rag_sociale'] = client_data['cliente']
        else:
            client_data['rag_sociale'] = "" # Altrimenti lascialo vuoto

        # Genera un nuovo ID univoco per il cliente
        new_id = get_new_client_id()
        client_data['id_cliente'] = new_id

        # Salva il file JSON
        try:
            save_client(new_id, client_data)
            imported_count += 1
        except Exception as e:
            print(f"ERRORE nel salvare il cliente alla riga {index + 2}: {e}")
            skipped_count += 1

    print("\n--- Importazione completata! ---")
    print(f"Clienti importati con successo: {imported_count}")
    print(f"Righe saltate (errori o dati mancanti): {skipped_count}")
    print(f"I nuovi file JSON sono stati creati nella cartella '{CLIENTS_DIR}'.")

# Esegui la funzione di importazione
if __name__ == "__main__":
    import_clients()