import sys
sys.argv = ["gestionale.py", "--debug"]

from models import SessionLocal, Preventivo, Cliente, Utente, ConfigMargini, Task, TagboxEntry, Notification
from sqlalchemy import func

db = SessionLocal()

# Test 1: get_all_quotes
q = db.query(Preventivo.numero, Preventivo.data, Preventivo.cliente, Preventivo.totale, Preventivo.stato)
results = q.order_by(Preventivo.numero.desc()).limit(3).all()
print("=== Test get_all_quotes (top 3) ===")
for r in results:
    print(f"  {r.numero} | {r.cliente} | {r.stato}")

# Test 2: load_quote
primo = results[0].numero
prev = db.query(Preventivo).filter_by(numero=primo).first()
data = prev.to_dict() if prev else None
print(f"\n=== Test load_quote({primo}) ===")
if data:
    print(f"  tipo: {data['tipo_preventivo']}")
    print(f"  no_iva: {data['no_iva']}")
    print(f"  ordini: {len(data['ordini_fornitore'])}")
    print(f"  bolle: {len(data['bolle'])}")

# Test 3: clienti search
term = "%cost%"
clients = db.query(Cliente).filter(
    (func.lower(Cliente.cliente).like(term)) | (func.lower(Cliente.rag_sociale).like(term))
).limit(3).all()
print(f"\n=== Test find_clients_by_term('cost') ===")
for c in clients:
    print(f"  {c.id_cliente}: {c.cliente}")

# Test 4: utenti
utenti = db.query(Utente).all()
print(f"\n=== Utenti in DB: {len(utenti)} ===")
for u in utenti:
    print(f"  {u.username}: {u.role} ({u.sigla})")

# Test 5: config margini
fasce = db.query(ConfigMargini).all()
print(f"\n=== Config Margini: {len(fasce)} fasce ===")
for f in fasce:
    print(f"  {f.key}: max_costo={f.max_costo}")

# Test 6: tasks
tasks = db.query(Task).all()
print(f"\n=== Tasks: {len(tasks)} ===")

# Test 7: tagbox
tagbox = db.query(TagboxEntry).all()
print(f"=== Tagbox: {len(tagbox)} voci ===")

# Test 8: notifiche
notifs = db.query(Notification).all()
print(f"=== Notifiche: {len(notifs)} ===")

db.close()
print("\nTutti i test superati!")
