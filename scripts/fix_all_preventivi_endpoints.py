import glob

# All endpoint -> blueprint.endpoint mappings for preventivi blueprint
replacements = {
    "url_for('annulla_preventivo'": "url_for('preventivi.annulla_preventivo'",
    'url_for("annulla_preventivo"': 'url_for("preventivi.annulla_preventivo"',
    "url_for('sblocca_preventivo'": "url_for('preventivi.sblocca_preventivo'",
    'url_for("sblocca_preventivo"': 'url_for("preventivi.sblocca_preventivo"',
    "url_for('clona_preventivo'": "url_for('preventivi.clona_preventivo'",
    'url_for("clona_preventivo"': 'url_for("preventivi.clona_preventivo"',
    "url_for('segna_inviato'": "url_for('preventivi.segna_inviato'",
    'url_for("segna_inviato"': 'url_for("preventivi.segna_inviato"',
    "url_for('segna_confermato'": "url_for('preventivi.segna_confermato'",
    'url_for("segna_confermato"': 'url_for("preventivi.segna_confermato"',
    "url_for('segna_annullato'": "url_for('preventivi.segna_annullato'",
    'url_for("segna_annullato"': 'url_for("preventivi.segna_annullato"',
    "url_for('salva_righe'": "url_for('preventivi.salva_righe'",
    'url_for("salva_righe"': 'url_for("preventivi.salva_righe"',
    "url_for('salva_righe_edili'": "url_for('preventivi.salva_righe_edili'",
    'url_for("salva_righe_edili"': 'url_for("preventivi.salva_righe_edili"',
    "url_for('analisi_preventivo'": "url_for('preventivi.analisi_preventivo'",
    'url_for("analisi_preventivo"': 'url_for("preventivi.analisi_preventivo"',
    "url_for('nuovo_preventivo'": "url_for('preventivi.nuovo_preventivo'",
    'url_for("nuovo_preventivo"': 'url_for("preventivi.nuovo_preventivo"',
    "url_for('nuovo_preventivo_edile'": "url_for('preventivi.nuovo_preventivo_edile'",
    'url_for("nuovo_preventivo_edile"': 'url_for("preventivi.nuovo_preventivo_edile"',
}

files = glob.glob('templates/**/*.html', recursive=True) + glob.glob('routes/*.py') + ['gestionale.py']

for filepath in files:
    try:
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
            print(f'Updated: {filepath}')
    except Exception as e:
        print(f'Error on {filepath}: {e}')
