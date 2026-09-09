import os, glob

replacements = {
    "url_for('dashboard_ordini')": "url_for('ordini.route_dashboard_ordini')",
    "url_for('conferma_ordine'": "url_for('ordini.conferma_ordine'",
    "url_for('salva_ordine'": "url_for('ordini.salva_ordine'",
    "url_for('modifica_ordine'": "url_for('ordini.modifica_ordine'",
    "url_for('svincola_articolo'": "url_for('ordini.svincola_articolo'",
    "url_for('aggiungi_a_ordine'": "url_for('ordini.aggiungi_a_ordine'",
    "url_for('elimina_ordine'": "url_for('ordini.elimina_ordine'",
    "url_for('allega_a_ordine'": "url_for('ordini.allega_a_ordine'",
    
    "url_for('dashboard_consegne')": "url_for('consegne.route_dashboard_consegne')",
    "url_for('gestione_consegna'": "url_for('consegne.gestione_consegna'",
    "url_for('marca_pronto'": "url_for('consegne.marca_pronto'",
    "url_for('marca_consegnato'": "url_for('consegne.marca_consegnato'",
    "url_for('annulla_stato_consegna'": "url_for('consegne.annulla_stato_consegna'",
    "url_for('crea_bolla'": "url_for('consegne.crea_bolla'"
}

templates = glob.glob('templates/**/*.html', recursive=True)
for filepath in templates:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    modified = False
    for old, new in replacements.items():
        if old in content:
            content = content.replace(old, new)
            modified = True
            
    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated {filepath}')
