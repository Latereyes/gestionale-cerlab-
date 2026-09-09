import os

# Move money_ui from gestionale.py to utils.py
with open("gestionale.py", "r", encoding="utf-8") as f:
    g_content = f.read()

# We can just append money_ui to utils.py and remove it from routes/ordini.py and routes/consegne.py
# Actually, wait, it's easier to just put money_ui in utils.py manually.
money_ui_code = """
from jinja2.runtime import Undefined
def money_ui(value):
    if value is None or isinstance(value, Undefined) or str(value).strip() == "": return ""
    try:
        val = float(value)
        return f"€ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return value
"""

with open("utils.py", "a", encoding="utf-8") as f:
    f.write(money_ui_code)

# Remove `from gestionale import money_ui` from routes/ordini.py
with open("routes/ordini.py", "r", encoding="utf-8") as f:
    o_content = f.read()
o_content = o_content.replace("from gestionale import money_ui", "")
# It is used in template so we actually pass it to context or just leave it since jinja filters are global.
# `money_ui` is a template filter in gestionale.py: `app.jinja_env.filters['money_ui'] = money_ui`.
# We don't need to import it in `routes/ordini.py` unless it's explicitly called.
# Is it explicitly called? Let's check.
if "money_ui(" in o_content:
    o_content = o_content.replace("from utils import (", "from utils import (\n    money_ui,")
with open("routes/ordini.py", "w", encoding="utf-8") as f:
    f.write(o_content)

# We also need to fix `gestionale.py` to use `from utils import money_ui` instead of defining it.
# Actually if we define it in `utils.py` and import it in `gestionale.py` it's perfect.
