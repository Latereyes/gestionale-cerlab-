#!/usr/bin/env python3
"""
migrate_v3_installer.py
=======================
Migrazione ONE-SHOT dei dati da file JSON (V2) al database SQLite (V3).
Viene eseguita dall'installer (Gestionale.exe --run-migration) e, in mancanza, all'avvio dell'app.

Percorso sorgente dati: %APPDATA%\\GestionalePreventivi\\
Percorso DB destinazione: variabile GESTIONALE_DB_PATH (impostata da gestionale.py),
altrimenti <cartella dati>\\gestionale_v3.db

UNA SOLA VOLTA: a migrazione riuscita scrive 'migration_v3_done.flag' nella cartella dati.
Le esecuzioni successive (es. aggiornamenti futuri) non fanno nulla, cosi' i JSON V2 ormai
vecchi non possono reintrodurre preventivi cancellati o modificati in V3.

Non migrati per scelta: messages.json e tagbox.json (azzerati in V3).
"""

import os
import sys
import json
from pathlib import Path

SENTINEL_NAME = "migration_v3_done.flag"


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
    standard_path = Path(appdata) / "GestionalePreventivi"
    if standard_path.exists():
        print(f"INFO: Percorso dati rilevato: {standard_path}")
        return standard_path

    raise FileNotFoundError(
        f"Cartella dati non trovata. Controlla che il gestionale sia stato installato correttamente."
        f"\nPercorso cercato: {standard_path}"
    )


# =============================================
# CONTATORI E LOG
# =============================================
class MigrationReport:
    def __init__(self):
        self.counts = {}
        self.errors = []      # problemi su singoli file/record: la migrazione prosegue
        self.fatal = []       # un intero passo e' fallito: la migrazione non va considerata completa
        self.skipped = {}

    def add(self, entity: str, n: int = 1):
        self.counts[entity] = self.counts.get(entity, 0) + n

    def skip(self, entity: str, n: int = 1):
        self.skipped[entity] = self.skipped.get(entity, 0) + n

    def error(self, msg: str):
        self.errors.append(msg)
        print(f"  [ERRORE] {msg}")

    def print_summary(self):
        print("\n" + "=" * 60)
        print("RIEPILOGO MIGRAZIONE")
        print("=" * 60)
        for entity in sorted(set(self.counts) | set(self.skipped)):
            print(f"  {entity:30s} +{self.counts.get(entity, 0):4d} inseriti  ({self.skipped.get(entity, 0)} gia presenti)")
        if self.errors:
            print(f"\n  Record non migrati / avvisi: {len(self.errors)}")
            for e in self.errors:
                print(f"    - {e}")
        if self.fatal:
            print(f"\n  PASSI FALLITI: {len(self.fatal)}")
            for e in self.fatal:
                print(f"    - {e}")
        if not self.errors and not self.fatal:
            print("\n  Nessun errore riscontrato.")
        print("=" * 60)


report = MigrationReport()


def load_json(path: Path, default):
    """Legge un file JSON. File assente -> None; file vuoto -> default; JSON rovinato -> errore e None."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        report.error(f"{path.name}: lettura fallita ({e})")
        return None
    if not text.strip():
        print(f"  {path.name} vuoto, nulla da migrare.")
        return default
    try:
        return json.loads(text)
    except Exception as e:
        report.error(f"{path.parent.name}/{path.name}: JSON illeggibile ({e})")
        return None


# =============================================
# 1. CLIENTI
# =============================================
def migrate_clienti(session, data_dir: Path, M):
    print("\n[1/7] Migrazione Clienti...")
    clienti_dir = data_dir / "clienti"
    if not clienti_dir.exists():
        print("  Cartella clienti/ non trovata, skip.")
        return

    files = sorted(clienti_dir.glob("*.json"))
    print(f"  Trovati {len(files)} file JSON clienti.")
    campi_cliente = set(M.Cliente.__table__.columns.keys())

    for file_path in files:
        data = load_json(file_path, None)
        if not data:
            continue
        id_cliente = data.get("id_cliente")
        if not id_cliente:
            report.error(f"clienti/{file_path.name}: id_cliente mancante")
            continue
        if session.query(M.Cliente).filter_by(id_cliente=id_cliente).first():
            report.skip("clienti")
            continue
        session.add(M.Cliente(
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
            documenti_anagrafici=data.get("documenti_anagrafici", []),
            note_interne=data.get("note_interne", ""),
            extra=M.campi_extra(data, campi_cliente)
        ))
        report.add("clienti")

    session.commit()


# =============================================
# 2. PREVENTIVI (PREV-* e EDIL-*) con ordini e bolle
# =============================================
def _extract_ordini_bolle(session, data: dict, numero: str, M):
    """Migra ordini e bolle contenuti nel JSON del preventivo."""
    campi_ordine = set(M.Ordine.__table__.columns.keys())
    campi_bolla = set(M.Bolla.__table__.columns.keys())

    for idx, ordine in enumerate(data.get("ordini_fornitore", []) or [], start=1):
        ordine_id = ordine.get("ordine_id")
        if not ordine_id:
            # Id stabile (non casuale), cosi' una seconda esecuzione produce lo stesso risultato
            ordine_id = f"{numero}-ORD{idx}"
        existing = session.get(M.Ordine, ordine_id)
        if existing is not None:
            if existing.preventivo_id == numero:
                report.skip("ordini")
                continue
            report.error(f"ordine {ordine_id} di {numero}: id gia usato da {existing.preventivo_id}, rinominato")
            ordine_id = f"{ordine_id}-{numero}"
        session.add(M.Ordine(
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
            allegati=ordine.get("allegati", []),
            extra=M.campi_extra(ordine, campi_ordine)
        ))
        session.flush()
        report.add("ordini")

    for bolla in data.get("bolle", []) or []:
        bolla_id = bolla.get("id")
        if not bolla_id:
            report.error(f"bolla senza id in {numero}: non migrata")
            continue
        if session.query(M.Bolla).filter_by(preventivo_id=numero, id=bolla_id).first():
            report.skip("bolle")
            continue
        session.add(M.Bolla(
            id=bolla_id,
            preventivo_id=numero,
            data=bolla.get("data", ""),
            indirizzo_cantiere_id=bolla.get("indirizzo_cantiere_id", ""),
            indici_righe=bolla.get("indici_righe", []),
            extra=M.campi_extra(bolla, campi_bolla)
        ))
        report.add("bolle")


def migrate_preventivi(session, data_dir: Path, M):
    print("\n[2/7] Migrazione Preventivi (PREV + EDIL)...")
    prev_dir = data_dir / "preventivi"
    if not prev_dir.exists():
        print("  Cartella preventivi/ non trovata, skip.")
        return

    files = sorted(prev_dir.glob("*.json"))
    print(f"  Trovati {len(files)} file JSON preventivi.")
    campi_preventivo = set(M.Preventivo.__table__.columns.keys()) | {"ordini_fornitore", "bolle"}

    for file_path in files:
        data = load_json(file_path, None)
        if not data:
            continue
        numero = data.get("numero")
        if not numero:
            report.error(f"preventivi/{file_path.name}: campo 'numero' mancante")
            continue
        if session.get(M.Preventivo, numero) is not None:
            report.skip("preventivi")
            continue

        raw_no_iva = data.get("no_iva", False)
        no_iva = (raw_no_iva is True) or (str(raw_no_iva).lower() == "true")

        try:
            session.add(M.Preventivo(
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
                is_locked=bool(data.get("is_locked", False)),
                id_cliente=data.get("id_cliente"),
                data_conferma=data.get("data_conferma"),
                no_iva=no_iva,
                tipo_preventivo=data.get("tipo_preventivo", "standard"),
                codice_univoco=data.get("codice_univoco", ""),
                iva_pct=data.get("iva_pct", ""),
                righe_edili=data.get("righe_edili", []),
                sezioni_edili=data.get("sezioni_edili", []),
                tot_imponibile_negozio=str(data.get("tot_imponibile_negozio", "")),
                tot_imponibile_cliente=str(data.get("tot_imponibile_cliente", "")),
                tot_iva=str(data.get("tot_iva", "")),
                ricarico_medio_pct=str(data.get("ricarico_medio_pct", "")),
                stato_consegna_globale=data.get("stato_consegna_globale", ""),
                stato_pagamento_globale=data.get("stato_pagamento_globale", ""),
                stato_fattura=data.get("stato_fattura", ""),
                data_chiusura=data.get("data_chiusura", ""),
                righe=data.get("righe", []),
                imponibili_iva=data.get("imponibili_iva", {}),
                tot_iva_dettaglio=data.get("tot_iva_dettaglio", {}),
                storico_pdf=data.get("storico_pdf", []),
                pagamenti=data.get("pagamenti", []),
                fatture_allegate=data.get("fatture_allegate", []),
                extra=M.campi_extra(data, campi_preventivo)
            ))
            session.flush()
            _extract_ordini_bolle(session, data, numero, M)
            session.commit()
            report.add("preventivi")
        except Exception as e:
            session.rollback()
            report.error(f"preventivi/{file_path.name}: {e}")


# =============================================
# 3-7. FILE SINGOLI (utenti, task, admin task, notifiche, margini)
# =============================================
def migrate_utenti(session, data_dir: Path, M):
    print("\n[3/7] Migrazione Utenti (users.json)...")
    for u in load_json(data_dir / "users.json", []) or []:
        username = u.get("username")
        if not username:
            continue
        if session.get(M.Utente, username) is not None:
            report.skip("utenti")
            continue
        session.add(M.Utente(
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


def migrate_tasks(session, data_dir: Path, M):
    print("\n[4/7] Migrazione Tasks (tasks.json)...")
    for t in load_json(data_dir / "tasks.json", []) or []:
        tid = t.get("id")
        if not tid:
            continue
        if session.get(M.Task, tid) is not None:
            report.skip("tasks")
            continue
        session.add(M.Task(
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


def migrate_admin_tasks(session, data_dir: Path, M):
    print("\n[5/7] Migrazione Admin Tasks (admin_tasks.json)...")
    for t in load_json(data_dir / "admin_tasks.json", []) or []:
        tid = t.get("id")
        if not tid:
            continue
        if session.get(M.AdminTask, tid) is not None:
            report.skip("admin_tasks")
            continue
        session.add(M.AdminTask(
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


def migrate_notifications(session, data_dir: Path, M):
    print("\n[6/7] Migrazione Notifiche (notifications.json)...")
    for idx, n in enumerate(load_json(data_dir / "notifications.json", []) or [], start=1):
        nid = n.get("id") or f"MIG-NOTIF-{idx}"
        if session.get(M.Notification, nid) is not None:
            report.skip("notifications")
            continue
        session.add(M.Notification(
            id=nid,
            target_user=n.get("target_user", n.get("user", n.get("user_id", "all"))),
            text=n.get("text", ""),
            link=n.get("link", ""),
            timestamp=n.get("timestamp", ""),
            read=n.get("read", False),
            notif_type=n.get("type", "info")
        ))
        report.add("notifications")
    session.commit()


def migrate_config_margini(session, data_dir: Path, M):
    print("\n[7/7] Migrazione Configurazione Margini (config_margini.json)...")
    cfg = load_json(data_dir / "config_margini.json", {}) or {}
    for fascia in cfg.get("fasce", []):
        key = fascia.get("key")
        if not key:
            continue
        if session.get(M.ConfigMargini, key) is not None:
            report.skip("config_margini")
            continue
        pallini = fascia.get("pallini", {})
        regole = fascia.get("regole_colore", {})
        session.add(M.ConfigMargini(
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


# =============================================
# MAIN
# =============================================
def main() -> int:
    """Esegue la migrazione. Ritorna 0 se completata (o gia' fatta), 1 se un passo e' fallito."""
    print("=" * 60)
    print("GESTIONALE CERLAB V3 - Script di Migrazione Dati")
    print("=" * 60)

    try:
        data_dir = get_data_dir()
    except FileNotFoundError as e:
        print(f"\nERRORE FATALE: {e}")
        return 1

    sentinel = data_dir / SENTINEL_NAME
    if sentinel.exists():
        print(f"\nMigrazione gia eseguita ({sentinel}). Nulla da fare.")
        return 0

    # Il DB va nella cartella dati, salvo che il chiamante (gestionale.py) l'abbia gia' indicato
    os.environ.setdefault("GESTIONALE_DB_PATH", str(data_dir / "gestionale_v3.db"))
    sys.path.insert(0, str(Path(__file__).parent))
    import models as M

    print(f"\nPercorso sorgente: {data_dir}")
    print(f"Database: {M.DB_PATH}")
    M.init_db()

    print("\nmessages.json e tagbox.json: non migrati (azzerati in V3).")

    session = M.SessionLocal()
    try:
        for step in (migrate_clienti, migrate_preventivi, migrate_utenti, migrate_tasks,
                     migrate_admin_tasks, migrate_notifications, migrate_config_margini):
            try:
                step(session, data_dir, M)
            except Exception as e:
                session.rollback()
                report.fatal.append(f"{step.__name__}: {e}")
                print(f"  [PASSO FALLITO] {step.__name__}: {e}")
    finally:
        session.close()

    report.print_summary()
    if report.fatal:
        print("\nMigrazione INCOMPLETA: verra' ritentata al prossimo avvio/installazione.")
        return 1

    sentinel.write_text("ok", encoding="utf-8")
    print("\nMigrazione completata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
