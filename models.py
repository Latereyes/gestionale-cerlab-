import os
from sqlalchemy import create_engine, Column, String, Boolean, ForeignKey, JSON, Integer, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.types import Float

# Path al database
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "gestionale.db")

# Configurazione Engine per SQLite
# check_same_thread=False e necessario per SQLite con Waitress (multithreading)
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False
)

Base = declarative_base()

class Cliente(Base):
    __tablename__ = "clienti"

    id_cliente = Column(String, primary_key=True)
    cliente = Column(String)  # Nome/Cognome
    telefono = Column(String)
    email = Column(String)
    regione_nome = Column(String)
    provincia = Column(String)
    comune = Column(String)
    cap = Column(String)
    indirizzo = Column(String)
    p_iva = Column(String)
    rag_sociale = Column(String)

    # Campi documenti anagrafici
    has_ci = Column(Boolean, default=False)
    has_privacy = Column(Boolean, default=False)
    has_contratto = Column(Boolean, default=False)
    documenti_anagrafici = Column(JSON, default=list)

    # Note interne libere sul cliente (pannello "Note Cliente", visibili da tutti i suoi preventivi)
    note_interne = Column(Text, default="")

    # Relazione con i preventivi
    preventivi = relationship("Preventivo", back_populates="cliente_rel")

    def __repr__(self):
        return f"<Cliente(id_cliente='{self.id_cliente}', cliente='{self.cliente}')>"

    def to_dict(self):
        return {
            "id_cliente": self.id_cliente,
            "cliente": self.cliente,
            "telefono": self.telefono,
            "email": self.email,
            "regione_nome": self.regione_nome,
            "provincia": self.provincia,
            "comune": self.comune,
            "cap": self.cap,
            "indirizzo": self.indirizzo,
            "p_iva": self.p_iva,
            "rag_sociale": self.rag_sociale,
            "has_ci": self.has_ci or False,
            "has_privacy": self.has_privacy or False,
            "has_contratto": self.has_contratto or False,
            "documenti_anagrafici": self.documenti_anagrafici or []
        }


class Preventivo(Base):
    __tablename__ = "preventivi"

    numero = Column(String, primary_key=True)
    data = Column(String)
    venditore = Column(String)
    cliente = Column(String)
    regione = Column(String)
    regione_nome = Column(String)
    indirizzo = Column(String)
    email = Column(String)
    telefono = Column(String)
    referente = Column(String)
    fee_pct = Column(String)
    totale = Column(String)
    comune = Column(String)
    provincia = Column(String)
    rag_sociale = Column(String)
    p_iva = Column(String)
    cap = Column(String)
    stato = Column(String)
    is_locked = Column(Boolean, default=False)

    # --- Colonne aggiunte in V3 ---
    data_conferma = Column(String)
    no_iva = Column(Boolean, default=False)
    tipo_preventivo = Column(String, default="standard")
    codice_univoco = Column(String)
    iva_pct = Column(String)
    righe_edili = Column(JSON, default=list)
    sezioni_edili = Column(JSON, default=list)

    # Relazione Foreign Key verso Cliente
    id_cliente = Column(String, ForeignKey("clienti.id_cliente"))
    cliente_rel = relationship("Cliente", back_populates="preventivi")

    # Relazioni verso Ordini e Bolle
    ordini_rel = relationship("Ordine", back_populates="preventivo_rel", cascade="all, delete-orphan")
    bolle_rel = relationship("Bolla", back_populates="preventivo_rel", cascade="all, delete-orphan")

    # Campi calcolati e globali
    tot_imponibile_negozio = Column(String)
    tot_imponibile_cliente = Column(String)
    tot_iva = Column(String)
    ricarico_medio_pct = Column(String)
    stato_consegna_globale = Column(String)
    stato_pagamento_globale = Column(String)
    stato_fattura = Column(String)
    data_chiusura = Column(String)

    # Strutture dati annidate
    righe = Column(JSON, default=list)
    imponibili_iva = Column(JSON, default=dict)
    tot_iva_dettaglio = Column(JSON, default=dict)
    storico_pdf = Column(JSON, default=list)
    pagamenti = Column(JSON, default=list)
    fatture_allegate = Column(JSON, default=list)

    def __repr__(self):
        return f"<Preventivo(numero='{self.numero}', cliente='{self.cliente}')>"

    def to_dict(self):
        return {
            "numero": self.numero,
            "data": self.data,
            "venditore": self.venditore,
            "cliente": self.cliente,
            "regione": self.regione,
            "regione_nome": self.regione_nome,
            "indirizzo": self.indirizzo,
            "email": self.email,
            "telefono": self.telefono,
            "referente": self.referente,
            "fee_pct": self.fee_pct,
            "totale": self.totale,
            "comune": self.comune,
            "provincia": self.provincia,
            "rag_sociale": self.rag_sociale,
            "p_iva": self.p_iva,
            "cap": self.cap,
            "stato": self.stato,
            "is_locked": self.is_locked,
            "id_cliente": self.id_cliente,
            "data_conferma": self.data_conferma,
            "no_iva": self.no_iva or False,
            "tipo_preventivo": self.tipo_preventivo or "standard",
            "codice_univoco": self.codice_univoco or "",
            "iva_pct": self.iva_pct or "",
            "righe_edili": self.righe_edili or [],
            "sezioni_edili": self.sezioni_edili or [],
            "tot_imponibile_negozio": self.tot_imponibile_negozio,
            "tot_imponibile_cliente": self.tot_imponibile_cliente,
            "tot_iva": self.tot_iva,
            "ricarico_medio_pct": self.ricarico_medio_pct,
            "stato_consegna_globale": self.stato_consegna_globale,
            "stato_pagamento_globale": self.stato_pagamento_globale,
            "stato_fattura": self.stato_fattura,
            "data_chiusura": self.data_chiusura,
            "righe": self.righe or [],
            "ordini_fornitore": [o.to_dict() for o in self.ordini_rel] if self.ordini_rel else [],
            "imponibili_iva": self.imponibili_iva or {},
            "tot_iva_dettaglio": self.tot_iva_dettaglio or {},
            "storico_pdf": self.storico_pdf or [],
            "pagamenti": self.pagamenti or [],
            "bolle": [b.to_dict() for b in self.bolle_rel] if self.bolle_rel else [],
            "fatture_allegate": self.fatture_allegate or []
        }

class Ordine(Base):
    __tablename__ = "ordini"

    ordine_id = Column(String, primary_key=True)
    preventivo_id = Column(String, ForeignKey("preventivi.numero"))
    data_ordine = Column(String)
    azienda = Column(String)
    numero_conferma = Column(String)
    importo = Column(String)
    importo_articoli = Column(String)
    importo_trasporto = Column(String)
    iva_ordine = Column(Float)
    data_arrivo = Column(String)
    indici_righe = Column(JSON, default=list)
    allegati = Column(JSON, default=list)

    preventivo_rel = relationship("Preventivo", back_populates="ordini_rel")

    def to_dict(self):
        return {
            "ordine_id": self.ordine_id,
            "preventivo_id": self.preventivo_id,
            "data_ordine": self.data_ordine,
            "azienda": self.azienda,
            "numero_conferma": self.numero_conferma,
            "importo": self.importo,
            "importo_articoli": self.importo_articoli,
            "importo_trasporto": self.importo_trasporto,
            "iva_ordine": self.iva_ordine,
            "data_arrivo": self.data_arrivo,
            "indici_righe": self.indici_righe or [],
            "allegati": self.allegati or []
        }

class Bolla(Base):
    __tablename__ = "bolle"

    db_id = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String)
    preventivo_id = Column(String, ForeignKey("preventivi.numero"))
    data = Column(String)
    indirizzo_cantiere_id = Column(String)
    indici_righe = Column(JSON, default=list)

    preventivo_rel = relationship("Preventivo", back_populates="bolle_rel")

    def to_dict(self):
        return {
            "id": self.id,
            "preventivo_id": self.preventivo_id,
            "data": self.data,
            "indirizzo_cantiere_id": self.indirizzo_cantiere_id,
            "indici_righe": self.indici_righe or []
        }


# ============================================================
# NUOVE TABELLE V3 - Migrazione da file JSON flat
# ============================================================

class Utente(Base):
    """Sostituisce data/users.json"""
    __tablename__ = "utenti"

    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    role = Column(String)
    sigla = Column(String)
    force_password_reset = Column(Boolean, default=False)
    last_seen_version = Column(String)

    def __repr__(self):
        return f"<Utente(username='{self.username}', role='{self.role}')>"

    def to_dict(self):
        return {
            "username": self.username,
            "password_hash": self.password_hash,
            "full_name": self.full_name,
            "role": self.role,
            "sigla": self.sigla,
            "force_password_reset": self.force_password_reset or False,
            "last_seen_version": self.last_seen_version or ""
        }


class Task(Base):
    """Sostituisce data/tasks.json"""
    __tablename__ = "tasks"

    id = Column(String, primary_key=True)
    created_by = Column(String)
    created_by_name = Column(String)
    description = Column(Text)
    assigned_to = Column(JSON, default=list)
    status = Column(String, default="open")
    is_private_admin = Column(Boolean, default=False)
    timestamp = Column(String)
    comments = Column(JSON, default=list)

    def __repr__(self):
        return f"<Task(id='{self.id}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "created_by": self.created_by,
            "created_by_name": self.created_by_name,
            "description": self.description,
            "assigned_to": self.assigned_to or [],
            "status": self.status,
            "is_private_admin": self.is_private_admin or False,
            "timestamp": self.timestamp,
            "comments": self.comments or []
        }


class AdminTask(Base):
    """Sostituisce data/admin_tasks.json"""
    __tablename__ = "admin_tasks"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    user_name = Column(String)
    created_by = Column(String)
    created_by_name = Column(String)
    description = Column(Text)
    assigned_to = Column(JSON, default=list)
    status = Column(String, default="LOGGED_ONLY")
    is_private_admin = Column(Boolean, default=True)
    timestamp = Column(String)
    comments = Column(JSON, default=list)

    def __repr__(self):
        return f"<AdminTask(id='{self.id}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "created_by": self.created_by,
            "created_by_name": self.created_by_name,
            "description": self.description,
            "assigned_to": self.assigned_to or [],
            "status": self.status,
            "is_private_admin": self.is_private_admin if self.is_private_admin is not None else True,
            "timestamp": self.timestamp,
            "comments": self.comments or []
        }


class Message(Base):
    """Sostituisce data/messages.json"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user = Column(String)
    from_name = Column(String)
    to_user = Column(String)
    text = Column(Text, default="")
    attachment = Column(String)
    original_filename = Column(String)
    timestamp = Column(String)
    read = Column(Boolean, default=False)

    def __repr__(self):
        return f"<Message(from='{self.from_user}', to='{self.to_user}')>"

    def to_dict(self):
        return {
            "from": self.from_user,
            "from_name": self.from_name,
            "to": self.to_user,
            "text": self.text or "",
            "attachment": self.attachment or "",
            "original_filename": self.original_filename or "",
            "timestamp": self.timestamp,
            "read": self.read or False
        }


class TagboxEntry(Base):
    """Sostituisce data/tagbox.json"""
    __tablename__ = "tagbox"

    id = Column(String, primary_key=True)
    user = Column(String)
    user_id = Column(String)
    text = Column(Text)
    timestamp = Column(String)
    pinned = Column(Boolean, default=False)

    def __repr__(self):
        return f"<TagboxEntry(id='{self.id}', user='{self.user}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user,
            "user_id": self.user_id,
            "text": self.text,
            "timestamp": self.timestamp,
            "pinned": self.pinned or False
        }


class Notification(Base):
    """Sostituisce data/notifications.json"""
    __tablename__ = "notifications"

    id = Column(String, primary_key=True)
    target_user = Column(String)
    text = Column(Text)
    link = Column(String)
    timestamp = Column(String)
    read = Column(Boolean, default=False)
    notif_type = Column(String)

    def __repr__(self):
        return f"<Notification(id='{self.id}', target='{self.target_user}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "target_user": self.target_user,
            "text": self.text,
            "link": self.link or "",
            "timestamp": self.timestamp,
            "read": self.read or False,
            "type": self.notif_type or "info"
        }


class ConfigMargini(Base):
    """Sostituisce data/config_margini.json"""
    __tablename__ = "config_margini"

    key = Column(String, primary_key=True)
    descrizione = Column(String)
    max_costo = Column(Float)
    pallino_verde = Column(Float)
    pallino_arancione = Column(Float)
    pallino_rosso = Column(Float)
    verde_min = Column(Float)
    verde_max = Column(Float)
    arancione_min1 = Column(Float)
    arancione_max1 = Column(Float)
    arancione_min2 = Column(Float)
    arancione_max2 = Column(Float)

    def __repr__(self):
        return f"<ConfigMargini(key='{self.key}', max_costo={self.max_costo})>"

    def to_dict(self):
        return {
            "key": self.key,
            "descrizione": self.descrizione,
            "max_costo": self.max_costo,
            "pallini": {
                "verde": self.pallino_verde,
                "arancione": self.pallino_arancione,
                "rosso": self.pallino_rosso
            },
            "regole_colore": {
                "verde_min": self.verde_min,
                "verde_max": self.verde_max,
                "arancione_min1": self.arancione_min1,
                "arancione_max1": self.arancione_max1,
                "arancione_min2": self.arancione_min2,
                "arancione_max2": self.arancione_max2
            }
        }


# Factory per creare sessioni al DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Crea le tabelle nel database se non esistono."""
    Base.metadata.create_all(bind=engine)
    _apply_schema_migrations()

def _apply_schema_migrations():
    """
    Applica migrazioni incrementali idempotenti per DB gia' esistenti sul campo.
    Aggiunge le colonne mancanti senza toccare i dati esistenti.
    Sicuro da rieseguire piu' volte (controlla prima se la colonna esiste).
    """
    import sqlite3
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Mappa: nome_tabella -> lista di (nome_colonna, definizione_sql)
    migrations = {
        "clienti": [
            ("has_ci",               "INTEGER DEFAULT 0"),
            ("has_privacy",          "INTEGER DEFAULT 0"),
            ("has_contratto",        "INTEGER DEFAULT 0"),
            ("documenti_anagrafici", "TEXT DEFAULT '[]'"),
            ("note_interne",         "TEXT DEFAULT ''"),
        ]
    }

    for table, columns in migrations.items():
        existing_cols = {row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
        for col_name, col_def in columns:
            if col_name not in existing_cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                print(f"[migrate] Aggiunta colonna '{col_name}' a tabella '{table}'")

    con.commit()
    con.close()

if __name__ == "__main__":
    init_db()
    print(f"Database V3 inizializzato con successo in: {DB_PATH}")
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Tabelle presenti: {tables}")
