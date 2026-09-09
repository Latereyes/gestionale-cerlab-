import os

input_file = "gestionale.py"
utils_file = "utils.py"

with open(input_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

def get_block(start_line, end_line):
    # 1-indexed to 0-indexed
    return "".join(lines[start_line-1:end_line])

utils_content = """import datetime
import uuid
import re
from functools import wraps
from flask import session, redirect, url_for, flash, request
from models import SessionLocal, Cliente, Preventivo
from jinja2.runtime import Undefined

# ---- FUNZIONI DB E STATI ----
"""

# Extract blocks
utils_content += get_block(5218, 5263) + "\n" # get_flat_righe_edili
utils_content += get_block(645, 1031) + "\n"  # get_all_quotes to find_clients_by_term
utils_content += get_block(1088, 1109) + "\n" # login_required and role_required

with open(utils_file, "w", encoding="utf-8") as f:
    f.write(utils_content)

# Now remove the extracted blocks from gestionale.py
# We must delete from bottom to top to preserve line numbers during deletion!
to_delete = [
    (5218, 5263),
    (1088, 1109),
    (645, 1031)
]

for start, end in to_delete:
    del lines[start-1:end]

# Insert import at the top (after other imports)
import_line = "from utils import get_flat_righe_edili, get_all_quotes, get_new_quote_id, load_quote, save_quote, aggiorna_stato_consegna_globale, aggiorna_stato_pagamento_globale, aggiorna_stato_avanzamento, get_new_client_id, load_client, save_client, find_clients_by_term, login_required, role_required\n"
lines.insert(12, import_line) # Insert around line 12

with open(input_file, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Estrazione utils completata con successo!")
