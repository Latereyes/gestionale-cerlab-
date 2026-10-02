#!/usr/bin/env python3
"""
migrate_v3_installer.py
=======================
Script di migrazione ONE-SHOT per GESTIONALE CERLAB V3.
Viene eseguito dal primo installer sul PC del cliente per migrare
tutti i dati da file JSON flat al database SQLite unificato.

Percorso sorgente dati: %APPDATA%\Roaming\gestionalepreventivi\
Percorso DB destinazione: stesso percorso / gestionale.db

IDEMPOTENTE: se un record esiste gia, viene saltato (safe to re-run).
"""

import os
import sys
import json
import glob
import uuid
from pathlib import Path

# =============================================
# RILEVAMENTO PERCORSO DATI CLIENTE
# =============================================
def get_data_dir() -> Path:
    """Rileva la cartella dati del cliente."""
    # Priorita 1: argomento da linea di comando
    if len(sys.argv) > 1:
        custom_path = Path(sys.argv[1])
        if custom_path.exists():
            print(f"INFO: Uso percorso custom: {custom_path}")
            return custom_path
        else:
            print(f"ATTENZIONE: Percorso custom non trovato: {custom_path}")

    # Priorita 2: AppData standard Windows
    appdata = os.environ.get("APPDATA", "")
    standard_path = Path(appdata) / "gestionalepreventivi"
    if standard_path.exists():
        print(f"INFO: Percorso dati rilevato: {standard_path}")
        return standard_path

    # Priorita 3: cartella data/ locale (per sviluppo/test)
    local_path = Path(__file__).parent / "data"
    if local_path.exists():
        print(f"INFO: Uso cartella data/ locale (modalita test): {local_path}")
        return local_path

    raise FileNotFoundError(
        f"Cartella dati non trovata. Controlla che il gestionale sia stato installato correttamente."
        f"\nPercorso cercato: {standard_path}"
    )


# =============================================
# SETUP DB (usa models.py dello stesso progetto)
# =============================================
# Aggiungiamo la directory dello script al path per importare models.py
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from models import (
    SessionLocal, init_db,
    Cliente, Preventivo, Ordine, Bolla,
    Utente, Task, AdminTask, Message, TagboxEntry,
    Notification, ConfigMargini
)


# =============================================
# CONTATORI E LOG
# =============================================
class MigrationReport:
    def __init__(self):
        self.counts = {}
        self.errors = []
        self.skipped = {}

    def add(self, entity: str, n: int = 1):
        self.counts[entity] = self.counts.get(entity, 0) + n

    def skip(self, entity: str, n: int = 1):
        self.skipped[entity] = self.skipped.get(entity, 0) + n

    def error(self, msg: str):
        self.errors.append(msg)
        print(f"  [ERRORE] {msg}")

    def print_summary(self):
        print("\n" + "="*60)
        print("RIEPILOGO MIGRAZIONE")
        print("="*60)
        for entity, count in sorted(self.counts.items()):
            skipped = self.skipped.get(entity, 0)
            print(f"  {entity:30s} +{count:4d} inseriti  ({skipped} gia presenti)")
        if self.errors:
            print(f"\n  ERRORI: {len(self.errors)}")
            for e in self.errors[:10]:
                print(f"    - {e}")
            if len(self.errors) > 10:
                print(f"    ... e altri {len(self.errors)-10} errori")
        else:
            print("\n  Nessun errore riscontrato.")
        print("="*60)


report = MigrationReport()


# =============================================
# 1. CLIENTI
# =============================================
def migrate_clienti(session, data_dir: Path):
    print("\n[1/9] Migrazione Clienti...")
    clienti_dir = data_dir / "clienti"
    if not clienti_dir.exists():
        print("  Cartella clienti/ non trovata, skip.")
        return

    files = list(clienti_dir.glob("*.json"))
    print(f"  Trovati {len(files)} file JSON clienti.")

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            id_cliente = data.get("id_cliente")
            if not id_cliente:
                report.error(f"clienti/{file_path.name}: id_cliente mancante")
                continue
            if session.query(Cliente).filter_by(id_cliente=id_cliente).first():
                report.skip("clienti")
                continue
            session.add(Cliente(
                id_cliente=id_cliente,
                cliente=data.get("cliente", ""),
                telefono=data.get("telefono", ""),
                email=data.get("email", ""),
                regione_nome=data.get("regione_nome", ""),
                provincia=data.get("provincia", ""),
                comune=data.get("comune", ""),
                cap=data.get("cap", ""),
                indirizzo=data.get("indirizzo", ""),
                p_iva=data.get("p_iva", ""),
                rag_sociale=data.get("rag_sociale", ""),
                has_ci=bool(data.get("has_ci", False)),
                has_privacy=bool(data.get("has_privacy", False)),
                has_contratto=bool(data.get("has_contratto", False)),
                documenti_anagrafici=data.get("documenti_anagrafici", [])
            ))
            report.add("clienti")
        except Exception as e:
            report.error(f"clienti/{file_path.name}: {e}")

    session.commit()
    print(f"  OK: {report.counts.get('clienti', 0)} clienti migrati.")


# =============================================
# 2. PREVENTIVI (PREV-* e EDIL-*)
# =============================================
def _extract_ordini_bolle(session, data: dict, numero: str):
    """Estrae e migra ordini e bolle embedded nel JSON del preventivo."""
    # Ordini (ordini_fornitore)
    for ordine in data.get("ordini_fornitore", []):
        ordine_id = ordine.get("ordine_id")
        if not ordine_id:
            ordine_id = str(uuid.uuid4())[:8].upper()
        if session.query(Ordine).filter_by(ordine_id=ordine_id).first():
            continue
        session.add(Ordine(
            ordine_id=ordine_id,
            preventivo_id=numero,
            data_ordine=ordine.get("data_ordine", ""),
            azienda=ordine.get("azienda", ""),
            numero_conferma=ordine.get("numero_conferma", ""),
            importo=str(ordine.get("importo", "")),
            importo_articoli=str(ordine.get("importo_articoli", "")),
            importo_trasporto=str(ordine.get("importo_trasporto", "")),
            iva_ordine=float(ordine.get("iva_ordine", 0) or 0),
            data_arrivo=ordine.get("data_arrivo", ""),
            indici_righe=ordine.get("indici_righe", []),
            allegati=ordine.get("allegati", [])
        ))

    # Bolle
    for bolla in data.get("bolle", []):
        bolla_id = bolla.get("id")
        if not bolla_id:
            continue
        # Le bolle non hanno una PK univoca naturale, usiamo combinazione preventivo+id
        existing = session.query(Bolla).filter_by(
            preventivo_id=numero, id=bolla_id
        ).first()
        if existing:
            continue
        session.add(Bolla(
            id=bolla_id,
            preventivo_id=numero,
            data=bolla.get("data", ""),
            indirizzo_cantiere_id=bolla.get("indirizzo_cantiere_id", ""),
            indici_righe=bolla.get("indici_righe", [])
        ))


def migrate_preventivi(session, data_dir: Path):
    print("\n[2/9] Migrazione Preventivi (PREV + EDIL)...")
    prev_dir = data_dir / "preventivi"
    if not prev_dir.exists():
        print("  Cartella preventivi/ non trovata, skip.")
        return

    files = list(prev_dir.glob("*.json"))
    print(f"  Trovati {len(files)} file JSON preventivi.")

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            numero = data.get("numero")
            if not numero:
                report.error(f"preventivi/{file_path.name}: campo 'numero' mancante")
                continue

            if session.query(Preventivo).filter_by(numero=numero).first():
                report.skip("preventivi")
                continue

            # Determina tipo
            tipo = data.get("tipo_preventivo", "standard")

            # Gestione no_iva: puo essere bool o stringa
            raw_no_iva = data.get("no_iva", False)
            no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")

            prev = Preventivo(
                numero=numero,
                data=data.get("data", ""),
                venditore=data.get("venditore", ""),
                cliente=data.get("cliente", ""),
                regione=str(data.get("regione", "")),
                regione_nome=data.get("regione_nome", ""),
                indirizzo=data.get("indirizzo", ""),
                email=data.get("email", ""),
                telefono=data.get("telefono", ""),
                referente=data.get("referente", ""),
                fee_pct=str(data.get("fee_pct", "")),
                totale=str(data.get("totale", "")),
                comune=data.get("comune", ""),
                provincia=data.get("provincia", ""),
                rag_sociale=data.get("rag_sociale", ""),
                p_iva=data.get("p_iva", ""),
                cap=data.get("cap", ""),
                stato=data.get("stato", "Bozza"),
                is_locked=data.get("is_locked", False),
                id_cliente=data.get("id_cliente"),
                # V3
                data_conferma=data.get("data_conferma"),
                no_iva=no_iva,
                tipo_preventivo=tipo,
                codice_univoco=data.get("codice_univoco", ""),
                iva_pct=data.get("iva_pct", ""),
                righe_edili=data.get("righe_edili", []),
                sezioni_edili=data.get("sezioni_edili", []),
                # Calcolati
                tot_imponibile_negozio=str(data.get("tot_imponibile_negozio", "")),
                tot_imponibile_cliente=str(data.get("tot_imponibile_cliente", "")),
                tot_iva=str(data.get("tot_iva", "")),
                ricarico_medio_pct=str(data.get("ricarico_medio_pct", "")),
                stato_consegna_globale=data.get("stato_consegna_globale", ""),
                stato_pagamento_globale=data.get("stato_pagamento_globale", ""),
                stato_fattura=data.get("stato_fattura", ""),
                data_chiusura=data.get("data_chiusura", ""),
                # JSON annidati
                righe=data.get("righe", []),
                imponibili_iva=data.get("imponibili_iva", {}),
                tot_iva_dettaglio=data.get("tot_iva_dettaglio", {}),
                storico_pdf=data.get("storico_pdf", []),
                pagamenti=data.get("pagamenti", []),
                fatture_allegate=data.get("fatture_allegate", [])
            )
            session.add(prev)
            session.flush()  # Ottieni l'ID per le FK

            # Migra ordini e bolle embedded
            _extract_ordini_bolle(session, data, numero)

            report.add("preventivi")
        except Exception as e:
            report.error(f"preventivi/{file_path.name}: {e}")

    session.commit()
    print(f"  OK: {report.counts.get('preventivi', 0)} preventivi migrati.")


# =============================================
# 3. UTENTI (users.json)
# =============================================
def migrate_utenti(session, data_dir: Path):
    print("\n[3/9] Migrazione Utenti (users.json)...")
    users_file = data_dir / "users.json"
    if not users_file.exists():
        print("  users.json non trovato, skip.")
        return

    with open(users_file, "r", encoding="utf-8") as f:
        users = json.load(f)

    for u in users:
        username = u.get("username")
        if not username:
            continue
        if session.query(Utente).filter_by(username=username).first():
            report.skip("utenti")
            continue
        session.add(Utente(
            username=username,
            password_hash=u.get("password_hash", ""),
            full_name=u.get("full_name", ""),
            role=u.get("role", "venditore"),
            sigla=u.get("sigla", ""),
            force_password_reset=u.get("force_password_reset", False),
            last_seen_version=u.get("last_seen_version", "")
        ))
        report.add("utenti")

    session.commit()
    print(f"  OK: {report.counts.get('utenti', 0)} utenti migrati.")


# =============================================
# 4. TASKS (tasks.json)
# =============================================
def migrate_tasks(session, data_dir: Path):
    print("\n[4/9] Migrazione Tasks (tasks.json)...")
    tasks_file = data_dir / "tasks.json"
    if not tasks_file.exists():
        print("  tasks.json non trovato, skip.")
        return

    with open(tasks_file, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    for t in tasks:
        tid = t.get("id")
        if not tid:
            continue
        if session.query(Task).filter_by(id=tid).first():
            report.skip("tasks")
            continue
        session.add(Task(
            id=tid,
            created_by=t.get("created_by", ""),
            created_by_name=t.get("created_by_name", ""),
            description=t.get("description", ""),
            assigned_to=t.get("assigned_to", []),
            status=t.get("status", "open"),
            is_private_admin=t.get("is_private_admin", False),
            timestamp=t.get("timestamp", ""),
            comments=t.get("comments", [])
        ))
        report.add("tasks")

    session.commit()
    print(f"  OK: {report.counts.get('tasks', 0)} tasks migrati.")


# =============================================
# 5. ADMIN TASKS (admin_tasks.json)
# =============================================
def migrate_admin_tasks(session, data_dir: Path):
    print("\n[5/9] Migrazione Admin Tasks (admin_tasks.json)...")
    admin_file = data_dir / "admin_tasks.json"
    if not admin_file.exists():
        print("  admin_tasks.json non trovato, skip.")
        return

    with open(admin_file, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    for t in tasks:
        tid = t.get("id")
        if not tid:
            continue
        if session.query(AdminTask).filter_by(id=tid).first():
            report.skip("admin_tasks")
            continue
        session.add(AdminTask(
            id=tid,
            user_id=t.get("user_id"),
            user_name=t.get("user_name"),
            created_by=t.get("created_by"),
            created_by_name=t.get("created_by_name"),
            description=t.get("description", ""),
            assigned_to=t.get("assigned_to", []),
            status=t.get("status", "LOGGED_ONLY"),
            is_private_admin=t.get("is_private_admin", True),
            timestamp=t.get("timestamp", ""),
            comments=t.get("comments", [])
        ))
        report.add("admin_tasks")

    session.commit()
    print(f"  OK: {report.counts.get('admin_tasks', 0)} admin tasks migrati.")


# =============================================
# 6. MESSAGGI (messages.json)
# =============================================
def migrate_messages(session, data_dir: Path):
    print("\n[6/9] Migrazione Messaggi (messages.json)...")
    msg_file = data_dir / "messages.json"
    if not msg_file.exists():
        print("  messages.json non trovato, skip.")
        return

    with open(msg_file, "r", encoding="utf-8") as f:
        messages = json.load(f)

    for m in messages:
        session.add(Message(
            from_user=m.get("from", ""),
            from_name=m.get("from_name", ""),
            to_user=m.get("to", ""),
            text=m.get("text", ""),
            attachment=m.get("attachment", ""),
            original_filename=m.get("original_filename", ""),
            timestamp=m.get("timestamp", ""),
            read=m.get("read", False)
        ))
        report.add("messages")

    session.commit()
    print(f"  OK: {report.counts.get('messages', 0)} messaggi migrati.")


# =============================================
# 7. TAGBOX (tagbox.json)
# =============================================
def migrate_tagbox(session, data_dir: Path):
    print("\n[7/9] Migrazione Tagbox (tagbox.json)...")
    tag_file = data_dir / "tagbox.json"
    if not tag_file.exists():
        print("  tagbox.json non trovato, skip.")
        return

    with open(tag_file, "r", encoding="utf-8") as f:
        entries = json.load(f)

    for e in entries:
        eid = e.get("id")
        if not eid:
            continue
        if session.query(TagboxEntry).filter_by(id=eid).first():
            report.skip("tagbox")
            continue
        session.add(TagboxEntry(
            id=eid,
            user=e.get("user", ""),
            user_id=e.get("user_id", ""),
            text=e.get("text", ""),
            timestamp=e.get("timestamp", ""),
            pinned=e.get("pinned", False)
        ))
        report.add("tagbox")

    session.commit()
    print(f"  OK: {report.counts.get('tagbox', 0)} voci tagbox migrate.")


# =============================================
# 8. NOTIFICHE (notifications.json)
# =============================================
def migrate_notifications(session, data_dir: Path):
    print("\n[8/9] Migrazione Notifiche (notifications.json)...")
    notif_file = data_dir / "notifications.json"
    if not notif_file.exists():
        print("  notifications.json non trovato, skip.")
        return

    with open(notif_file, "r", encoding="utf-8") as f:
        notifs = json.load(f)

    for n in notifs:
        nid = n.get("id")
        if not nid:
            nid = str(uuid.uuid4())[:8]
        if session.query(Notification).filter_by(id=nid).first():
            report.skip("notifications")
            continue
        session.add(Notification(
            id=nid,
            target_user=n.get("target_user", n.get("user", "all")),
            text=n.get("text", ""),
            link=n.get("link", ""),
            timestamp=n.get("timestamp", ""),
            read=n.get("read", False),
            notif_type=n.get("type", "info")
        ))
        report.add("notifications")

    session.commit()
    print(f"  OK: {report.counts.get('notifications', 0)} notifiche migrate.")


# =============================================
# 9. CONFIG MARGINI (config_margini.json)
# =============================================
def migrate_config_margini(session, data_dir: Path):
    print("\n[9/9] Migrazione Configurazione Margini (config_margini.json)...")
    cfg_file = data_dir / "config_margini.json"
    if not cfg_file.exists():
        print("  config_margini.json non trovato, skip.")
        return

    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    for fascia in cfg.get("fasce", []):
        key = fascia.get("key")
        if not key:
            continue
        if session.query(ConfigMargini).filter_by(key=key).first():
            report.skip("config_margini")
            continue
        pallini = fascia.get("pallini", {})
        regole = fascia.get("regole_colore", {})
        session.add(ConfigMargini(
            key=key,
            descrizione=fascia.get("descrizione", ""),
            max_costo=float(fascia.get("max_costo", 0)),
            pallino_verde=float(pallini.get("verde", 0)),
            pallino_arancione=float(pallini.get("arancione", 0)),
            pallino_rosso=float(pallini.get("rosso", 0)),
            verde_min=float(regole.get("verde_min", 0)),
            verde_max=float(regole.get("verde_max", 0)),
            arancione_min1=float(regole.get("arancione_min1", 0)),
            arancione_max1=float(regole.get("arancione_max1", 0)),
            arancione_min2=float(regole.get("arancione_min2", 0)),
            arancione_max2=float(regole.get("arancione_max2", 0))
        ))
        report.add("config_margini")

    session.commit()
    print(f"  OK: {report.counts.get('config_margini', 0)} fasce margini migrate.")


# =============================================
# MAIN
# =============================================
def main():
    print("=" * 60)
    print("GESTIONALE CERLAB V3 - Script di Migrazione Dati")
    print("=" * 60)

    try:
        data_dir = get_data_dir()
    except FileNotFoundError as e:
        print(f"\nERRORE FATALE: {e}")
        sys.exit(1)

    print(f"\nPercorso sorgente: {data_dir}")

    # Inizializza DB (crea tabelle se non esistono)
    print("\nInizializzazione database...")
    init_db()
    print("OK: Schema DB pronto.")

    session = SessionLocal()
    try:
        migrate_clienti(session, data_dir)
        migrate_preventivi(session, data_dir)
        migrate_utenti(session, data_dir)
        migrate_tasks(session, data_dir)
        migrate_admin_tasks(session, data_dir)
        migrate_messages(session, data_dir)
        migrate_tagbox(session, data_dir)
        migrate_notifications(session, data_dir)
        migrate_config_margini(session, data_dir)
    except Exception as e:
        session.rollback()
        report.error(f"Errore critico durante la migrazione: {e}")
        raise
    finally:
        session.close()

    report.print_summary()
    print("\nMigrazione completata.")


if __name__ == "__main__":
    main()
