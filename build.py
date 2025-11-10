# In build.py

import os
import re
import uuid
import subprocess
import shutil

# ... (tutte le definizioni di file e le funzioni rimangono invariate) ...
VERSION_FILE = "version.txt"
PYTHON_FILES_TO_UPDATE = ["gestionale.py"]
INNO_SETUP_FILE = "crea_installer.iss"
FOLDERS_TO_CLEAN = ["dist", "build", "userdesktop"]

def clean_previous_builds():
    # ...
    print("--- Pulizia delle build precedenti ---")
    for folder in FOLDERS_TO_CLEAN:
        if os.path.exists(folder):
            shutil.rmtree(folder)

# ... (tutte le altre funzioni come get_current_version, update_file etc. sono invariate)
def get_current_version():
    with open(VERSION_FILE, "r") as f: return f.read().strip()
def get_next_version(current_version, bump_type):
    major, minor, patch = map(int, current_version.split('.'))
    if bump_type == 'major': major += 1; minor = 0; patch = 0
    elif bump_type == 'minor': minor += 1; patch = 0
    else: patch += 1
    return f"{major}.{minor}.{patch}"
def update_file(filepath, pattern, replacement):
    with open(filepath, "r", encoding="utf-8") as f: content = f.read()
    new_content = re.sub(pattern, replacement, content, count=1)
    with open(filepath, "w", encoding="utf-8") as f: f.write(new_content)


if __name__ == "__main__":
    # ... (tutta la parte di richiesta versione e aggiornamento file rimane uguale) ...
    clean_previous_builds()
    current_version = get_current_version()
    print(f"Versione attuale: {current_version}")
    while True:
        bump = input("Che tipo di aggiornamento è? (major, minor, patch): ").lower()
        if bump in ['major', 'minor', 'patch']: break
    new_version = get_next_version(current_version, bump)
    print(f"Nuova versione sarà: {new_version}")
    new_guid = str(uuid.uuid4())
    print(f"Nuovo GUID generato: {new_guid}")
    print("\n--- Aggiornamento dei file di progetto ---")
    for py_file in PYTHON_FILES_TO_UPDATE:
        update_file(py_file, r'APP_VERSION\s*=\s*".*?"', f'APP_VERSION = "{new_version}"')
    update_file(INNO_SETUP_FILE, r'(#define\s+MyAppVersion\s+)".*?"', f'\\1"{new_version}"')
    update_file(INNO_SETUP_FILE, r'(AppId\s*=\s*\{\{).*?(\}\})', fr'\g<1>{new_guid}\g<2>')
    with open(VERSION_FILE, "w") as f: f.write(new_version)
    print("\n✅ Tutti i file sono stati aggiornati con successo!")

    run_compilers = input("Vuoi eseguire PyInstaller e Inno Setup ora? (s/n): ").lower()
    if run_compilers == 's':
        try:
            print("\n--- 1/2: Compilazione di Gestionale.exe ---")
            # Compiliamo un solo eseguibile che contiene tutto
            subprocess.run(["pyinstaller", "gestionale.spec", "--noconfirm"], check=True)

            print("\n--- 2/2: Creazione dell'installer con Inno Setup ---")
            inno_compiler_path = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
            if os.path.exists(inno_compiler_path):
                subprocess.run([inno_compiler_path, INNO_SETUP_FILE])
            else:
                print("ATTENZIONE: Compilatore Inno Setup non trovato.")

            print("\n🚀 Build completata!")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"\n!!! ERRORE: La compilazione è fallita: {e}")