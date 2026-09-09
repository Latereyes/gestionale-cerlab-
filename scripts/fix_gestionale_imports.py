import os

with open("gestionale.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add the import at the top after from utils import ...
# Let's find "from utils import ("
if "from utils import (" in content:
    content = content.replace(
        "from utils import (", 
        "from utils import (\n    _to_num,"
    )
else:
    # fallback
    content = "from utils import _to_num\n" + content

with open("gestionale.py", "w", encoding="utf-8") as f:
    f.write(content)
