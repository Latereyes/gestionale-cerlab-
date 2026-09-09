import os
with open('routes/ordini.py', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace("ALLEGATI_DIR = BASE_DIR / 'data' / 'preventivi'", "import os\nALLEGATI_DIR = os.path.join(BASE_DIR, 'data', 'preventivi')")
with open('routes/ordini.py', 'w', encoding='utf-8') as f:
    f.write(text)

with open('utils.py', 'r', encoding='utf-8') as f:
    u_text = f.read()
u_text = u_text.replace("CLIENTI_DIR = BASE_DIR / 'data' / 'clienti'", "import os\n    CLIENTI_DIR = os.path.join(BASE_DIR, 'data', 'clienti')")
u_text = u_text.replace("file_path = CLIENTI_DIR / f'{client_id}.json'", "file_path = os.path.join(CLIENTI_DIR, f'{client_id}.json')")
u_text = u_text.replace("if not file_path.exists():", "if not os.path.exists(file_path):")
with open('utils.py', 'w', encoding='utf-8') as f:
    f.write(u_text)
