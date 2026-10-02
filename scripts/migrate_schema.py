import sqlite3, os
db_path = os.path.join("data", "gestionale.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(preventivi)")
existing_cols = {row[1] for row in cursor.fetchall()}
print("Colonne esistenti preventivi:", sorted(existing_cols))

new_cols = [
    ("data_conferma", "TEXT"),
    ("no_iva", "INTEGER DEFAULT 0"),
    ("tipo_preventivo", "TEXT DEFAULT standard"),
    ("codice_univoco", "TEXT"),
    ("iva_pct", "TEXT"),
    ("righe_edili", "JSON"),
    ("sezioni_edili", "JSON"),
]

for col_name, col_type in new_cols:
    if col_name not in existing_cols:
        sql = f"ALTER TABLE preventivi ADD COLUMN {col_name} {col_type}"
        cursor.execute(sql)
        print(f"Aggiunta colonna preventivi.{col_name}")
    else:
        print(f"Gia presente: preventivi.{col_name}")

cursor.execute("PRAGMA table_info(ordini)")
ordini_cols = {row[1] for row in cursor.fetchall()}
if "allegati" not in ordini_cols:
    cursor.execute("ALTER TABLE ordini ADD COLUMN allegati JSON")
    print("Aggiunta colonna ordini.allegati")

# Crea nuove tabelle se non esistono (le V3)
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = {row[0] for row in cursor.fetchall()}
print("Tabelle presenti:", sorted(tables))

conn.commit()
conn.close()
print("Schema aggiornato con successo.")
