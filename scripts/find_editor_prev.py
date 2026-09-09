import glob, re

pattern = re.compile(r"url_for\(['\"]editor_preventivo['\"]")

files = glob.glob('templates/**/*.html', recursive=True) + glob.glob('routes/*.py') + ['gestionale.py']

for filepath in files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    print(f'{filepath}:{i}: {line.rstrip()}')
    except Exception as e:
        print(f'Error {filepath}: {e}')
