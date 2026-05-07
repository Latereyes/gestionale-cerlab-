from werkzeug.security import generate_password_hash
import sys
#import getpass # Per nascondere l'input della password

# Chiede la password in modo sicuro senza mostrarla a schermo
try:
    password = input("Inserisci la password da codificare: ")
except Exception as error:
    print('ERRORE', error)
    sys.exit(1)

if not password:
    print("La password non può essere vuota.")
else:
    hash_generato = generate_password_hash(password)
    print("\nCopia e incolla questo hash nel tuo file users.json:")
    print("----------------------------------------------------")
    print(hash_generato)
    print("----------------------------------------------------")