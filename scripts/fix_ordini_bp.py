import os

with open("routes/ordini.py", "r", encoding="utf-8") as f:
    content = f.read()

# We need to add `from werkzeug.utils import secure_filename` 
# and `ALLEGATI_DIR` and `Path` if `allega_a_ordine` needs it.
# Actually `allega_a_ordine` should save allegati. Where do they save it? `ALLEGATI_DIR`.
# `Ordine.allegati` is NOT in `models.py`! Wait! 
# Let's check `models.py` to see if `Ordine.allegati` exists. No it doesn't!
# We might need to add it to `Ordine` or we just leave it in JSON column? 
# Wait, let's just add `allegati = Column(JSON, default=list)` to `Ordine` in `models.py`!
