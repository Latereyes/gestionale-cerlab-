with open('routes/preventivi.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix blueprint-internal url_for calls that need the blueprint prefix
replacements = {
    "url_for(\"editor_preventivo_edile\"": "url_for(\"preventivi.editor_preventivo_edile\"",
    "url_for('editor_preventivo_edile'": "url_for('preventivi.editor_preventivo_edile'",
    "url_for(\"editor_preventivo\"": "url_for(\"preventivi.editor_preventivo\"",
    "url_for('editor_preventivo'": "url_for('preventivi.editor_preventivo'",
}

for old, new in replacements.items():
    content = content.replace(old, new)

with open('routes/preventivi.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
