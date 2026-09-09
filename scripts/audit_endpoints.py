import glob, re

# All known blueprint endpoints that need a prefix
blueprint_endpoints = {
    'preventivi': [
        'nuovo_preventivo_edile', 'editor_preventivo_edile', 'salva_righe_edili',
        'nuovo_preventivo', 'editor_preventivo', 'salva_righe',
        'clona_preventivo', 'sblocca_preventivo', 'segna_inviato', 'segna_confermato',
        'annulla_preventivo', 'segna_annullato', 'analisi_preventivo'
    ],
    'ordini': [
        'route_dashboard_ordini', 'conferma_ordine', 'salva_ordine',
        'modifica_ordine', 'svincola_articolo', 'aggiungi_a_ordine',
        'elimina_ordine', 'allega_a_ordine'
    ],
    'consegne': [
        'route_dashboard_consegne', 'gestione_consegna', 'marca_pronto',
        'marca_consegnato', 'annulla_stato_consegna', 'crea_bolla', 'export_bolla_pdf'
    ]
}

files = glob.glob('templates/**/*.html', recursive=True) + glob.glob('routes/*.py') + ['gestionale.py']

print("=== Looking for unqualified endpoint references ===")
for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for blueprint, endpoints in blueprint_endpoints.items():
            for ep in endpoints:
                # Look for url_for('ep' or url_for("ep" WITHOUT the blueprint prefix
                patterns = [f"url_for('{ep}'", f'url_for("{ep}"', f"url_for('{ep},", f'url_for("{ep},']
                for pat in patterns:
                    # Only if NOT already prefixed
                    prefixed = f"url_for('{blueprint}.{ep}'"
                    prefixed2 = f'url_for("{blueprint}.{ep}"'
                    if pat in content and prefixed not in content and prefixed2 not in content:
                        print(f"  {filepath}: '{ep}' (should be '{blueprint}.{ep}')")
                        break
    except Exception as e:
        print(f'Error on {filepath}: {e}')
