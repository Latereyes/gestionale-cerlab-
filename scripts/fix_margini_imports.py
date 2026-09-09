with open('gestionale.py', 'r', encoding='utf-8') as f:
    g_content = f.read()

# Add DEFAULT_MARGINI and load_margini_config to the utils import block
if 'from utils import (' in g_content:
    g_content = g_content.replace('from utils import (', 'from utils import (\n    DEFAULT_MARGINI, load_margini_config,')

with open('gestionale.py', 'w', encoding='utf-8') as f:
    f.write(g_content)

with open('routes/preventivi.py', 'r', encoding='utf-8') as f:
    p_content = f.read()

# Replace local import from gestionale with import from utils
p_content = p_content.replace('from gestionale import load_margini_config', 'from utils import load_margini_config')

with open('routes/preventivi.py', 'w', encoding='utf-8') as f:
    f.write(p_content)
