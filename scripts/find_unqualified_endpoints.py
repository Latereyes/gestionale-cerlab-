import glob, re

# All blueprint endpoints (any that are NOT already prefixed with blueprint.)
blueprint_endpoints = [
    'editor_preventivo', 'editor_preventivo_edile',
    'nuovo_preventivo', 'nuovo_preventivo_edile',
    'salva_righe', 'salva_righe_edili',
    'clona_preventivo', 'sblocca_preventivo',
    'segna_inviato', 'segna_confermato', 'annulla_preventivo', 'segna_annullato',
    'analisi_preventivo', 'invia_preventivo', 'conferma_preventivo',
    'route_dashboard_ordini', 'conferma_ordine', 'salva_ordine',
    'modifica_ordine', 'svincola_articolo', 'aggiungi_a_ordine',
    'elimina_ordine', 'allega_a_ordine',
    'route_dashboard_consegne', 'gestione_consegna',
    'marca_pronto', 'marca_consegnato', 'annulla_stato_consegna', 'crea_bolla',
]

files = (
    glob.glob('templates/**/*.html', recursive=True) + 
    glob.glob('routes/*.py') + 
    ['gestionale.py']
)

found_any = False
for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        for ep in blueprint_endpoints:
            # Match url_for('ep' or url_for("ep" NOT preceded by a dot
            for m in re.finditer(r"url_for\(['\"](" + re.escape(ep) + r")['\"]", content):
                # check the char before 'ep' in the string to ensure no dot prefix
                start = m.start(1)
                before = content[max(0, start-3):start]
                if '.' not in before:
                    line_no = content[:m.start()].count('\n') + 1
                    line = content.split('\n')[line_no-1].strip()
                    print(f'{filepath}:{line_no}: {line}')
                    found_any = True
    except Exception as e:
        print(f'Error {filepath}: {e}')

if not found_any:
    print('All clean!')
