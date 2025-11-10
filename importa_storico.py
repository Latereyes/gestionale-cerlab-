import pandas as pd
import json
import os
from pathlib import Path

# --- CONFIGURAZIONE ---
EXCEL_FILE_PATH = "storico.xlsx"
OUTPUT_JSON_PATH = Path("data") / "storico_ceo.json"

def import_historical_data():
    """
    Legge i dati storici sul fatturato da un file Excel
    e li salva in un file JSON ottimizzato per la dashboard CEO.
    Versione aggiornata per gestire nomi di colonna con spazi extra.
    """
    print("--- Avvio importazione dati storici per Dashboard CEO ---")

    if not os.path.exists(EXCEL_FILE_PATH):
        print(f"ERRORE: File '{EXCEL_FILE_PATH}' non trovato.")
        return

    OUTPUT_JSON_PATH.parent.mkdir(exist_ok=True)

    try:
        # Leggiamo il file senza forzare i nomi delle colonne
        df = pd.read_excel(EXCEL_FILE_PATH)
        
        # NUOVA LOGICA: Pulisce tutti i nomi delle colonne da spazi bianchi iniziali e finali
        df.columns = df.columns.str.strip()
        
        print(f"Trovate {len(df)} righe nel file Excel. Colonne identificate: {list(df.columns)}")

        # Controlliamo se le colonne necessarie esistono dopo la pulizia
        required_cols = ["PREVENTIVO", "TOT."]
        if not all(col in df.columns for col in required_cols):
            print(f"ERRORE: Una o più colonne richieste ({required_cols}) non sono state trovate nel file.")
            return

    except Exception as e:
        print(f"ERRORE durante la lettura del file Excel: {e}")
        return

    historical_entries = []
    for index, row in df.iterrows():
        if pd.isna(row["PREVENTIVO"]) or pd.isna(row["TOT."]):
            continue

        try:
            data_corretta = pd.to_datetime(row["PREVENTIVO"]).strftime('%Y-%m-%d')
            totale_float = float(row["TOT."])

            historical_entries.append({
                "data": data_corretta,
                "totale": totale_float
            })
        except (ValueError, TypeError) as e:
            print(f"ATTENZIONE: Riga {index + 2} saltata per dati non validi. Errore: {e}")
            continue

    try:
        with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(historical_entries, f, ensure_ascii=False, indent=2)
        print(f"\n--- Importazione completata con successo! ---")
        print(f"Creato il file '{OUTPUT_JSON_PATH}' con {len(historical_entries)} voci storiche.")
    except Exception as e:
        print(f"ERRORE durante il salvataggio del file JSON: {e}")


if __name__ == "__main__":
    import_historical_data()