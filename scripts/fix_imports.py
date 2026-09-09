import os
import re

with open("utils.py", "a", encoding="utf-8") as f:
    f.write('''

import re

def _to_num(x, default=0.0):
    if x is None: return float(default)
    s = re.sub(r"[€%\s]", "", str(x))
    if not s: return float(default)
    if "," in s and "." in s: s = s.replace(".", "") if s.rfind(".") < s.rfind(",") else s.replace(",", "")
    s = s.replace(",", ".")
    try: return float(s)
    except ValueError: return float(default)

def _get_ordine_costo_effettivo_netto(ordine):
    importo_articoli_lordo_salvato = _to_num(ordine.get("importo_articoli"))
    importo_trasporto_lordo_salvato = _to_num(ordine.get("importo_trasporto"))
    importo_totale_lordo_salvato = _to_num(ordine.get("importo"))
    
    if "importo_articoli" in ordine and ordine["importo_articoli"]:
        trasporto_incluso = ordine.get("trasporto_incluso", True)
        if trasporto_incluso:
            return importo_articoli_lordo_salvato / 1.22
        else:
            return (importo_articoli_lordo_salvato / 1.22) + (importo_trasporto_lordo_salvato / 1.22)
    else:
        return importo_totale_lordo_salvato / 1.22

def _get_netto_ordine(ordine):
    return _get_ordine_costo_effettivo_netto(ordine)

import json
def get_indirizzi_cantiere(client_id):
    from utils import BASE_DIR
    CLIENTI_DIR = BASE_DIR / "data" / "clienti"
    file_path = CLIENTI_DIR / f"{client_id}.json"
    if not file_path.exists(): return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            c = json.load(f)
            return c.get("indirizzi_cantiere", [])
    except: return []
''')

# Now fix ordini.py to import them from utils instead of gestionale
with open("routes/ordini.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("from gestionale import (", "# from gestionale import (")
content = content.replace("_to_num, _get_ordine_costo_effettivo_netto, _get_netto_ordine, money_ui, ALLEGATI_DIR", "# removed imports")
content = content.replace(")", "# )")

content = content.replace(
    "from utils import (", 
    "from utils import (\n    _to_num, _get_ordine_costo_effettivo_netto, _get_netto_ordine, get_indirizzi_cantiere,"
)
content = content.replace("from gestionale import _to_num, get_indirizzi_cantiere", "")

# Add ALLEGATI_DIR definition to ordini.py
content = content.replace("from pathlib import Path", "from pathlib import Path\nfrom utils import BASE_DIR\nALLEGATI_DIR = BASE_DIR / 'data' / 'preventivi'")

with open("routes/ordini.py", "w", encoding="utf-8") as f:
    f.write(content)

# Fix consegne.py imports
with open("routes/consegne.py", "r", encoding="utf-8") as f:
    c_content = f.read()

c_content = c_content.replace("from gestionale import _to_num, get_indirizzi_cantiere", "")
c_content = c_content.replace(
    "from utils import (", 
    "from utils import (\n    _to_num, get_indirizzi_cantiere,"
)

with open("routes/consegne.py", "w", encoding="utf-8") as f:
    f.write(c_content)
