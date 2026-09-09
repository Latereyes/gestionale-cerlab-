with open('gestionale.py', 'r', encoding='utf-8') as f:
    content = f.read()
replacements = {
    "url_for('dashboard_ordini')": "url_for('ordini.route_dashboard_ordini')",
    "url_for('conferma_ordine'": "url_for('ordini.conferma_ordine'",
    "url_for('dashboard_consegne')": "url_for('consegne.route_dashboard_consegne')",
    "url_for('gestione_consegna'": "url_for('consegne.gestione_consegna'"
}
for old, new in replacements.items():
    content = content.replace(old, new)
with open('gestionale.py', 'w', encoding='utf-8') as f:
    f.write(content)
