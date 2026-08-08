"""
A tiny Firestore-compatible document store backed by a SQL database.

Why this exists
---------------
The app was written against Cloud Firestore, whose Python client needs grpcio -
a package with no prebuilt wheel for the ARMv6 Raspberry Pi it is deployed on.
This module re-implements just the slice of the Firestore API the app actually
uses (collection / document / get / set / update / delete / stream / where) on
top of an ordinary SQL table, so every existing call site keeps working while
the data now lives in MariaDB (pure-Python PyMySQL, which installs fine on the
Pi). SQLite is supported too, purely so the suite can run with no server.

Storage model
-------------
One table, `fs_documents(coll, doc_id, data)`, where `data` is a JSON string of
the document. Firestore has no fixed schema and this preserves that. Queries
load a collection and filter in Python - the app's collections are small
(users, resumes, job_posts, applications: hundreds of rows) and it uses only
equality filters, so this is both simple and dialect-independent.

Configuration
-------------
DATABASE_URL selects the backend:
    mysql://user:pass@host:3306/dbname      (MariaDB / MySQL, via PyMySQL)
    sqlite:////absolute/path/to/file.db     (local / tests)
Unset -> connect() returns None and the app runs in its no-database mode.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote


# --- Firestore-compatible sentinels & helpers ------------------------------

class _ServerTimestamp:
    """Stand-in for firestore.SERVER_TIMESTAMP; resolved to now() on write."""
    def __repr__(self):
        return "SERVER_TIMESTAMP"


SERVER_TIMESTAMP = _ServerTimestamp()


class FieldFilter:
    """Mirror of google.cloud.firestore_v1.base_query.FieldFilter."""
    def __init__(self, field, op, value):
        self.field, self.op, self.value = field, op, value


def _json_default(obj):
    # datetimes round-trip as a tagged object so a created_at written as a
    # SERVER_TIMESTAMP comes back as a real datetime (adminstore sorts on it).
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return {"__dt__": obj.isoformat()}
    raise TypeError(f"Cannot serialise {type(obj).__name__} for the datastore")


def _json_object_hook(d):
    if len(d) == 1 and "__dt__" in d:
        return datetime.fromisoformat(d["__dt__"])
    return d


def _dumps(data):
    return json.dumps(data, default=_json_default)


def _loads(text):
    return json.loads(text, object_hook=_json_object_hook)


def _resolve_sentinels(value):
    """Replace every SERVER_TIMESTAMP in a payload with the current UTC time."""
    now = datetime.now(timezone.utc)

    def walk(v):
        if isinstance(v, _ServerTimestamp):
            return now
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value)


_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a is not None and a > b,
    ">=": lambda a, b: a is not None and a >= b,
    "<": lambda a, b: a is not None and a < b,
    "<=": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
    "array_contains": lambda a, b: isinstance(a, list) and b in a,
}


def _matches(data, field, op, value):
    fn = _OPS.get(op)
    if fn is None:
        raise ValueError(f"Unsupported query operator: {op!r}")
    return fn(data.get(field), value)


# --- Firestore-compatible view objects -------------------------------------

class DocumentSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data  # dict, or None when the document does not exist

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None

    def get(self, field, default=None):
        return (self._data or {}).get(field, default)


class DocumentReference:
    def __init__(self, client, coll, doc_id):
        self._client = client
        self._coll = coll
        self.id = doc_id

    def get(self):
        raw = self._client._read(self._coll, self.id)
        return DocumentSnapshot(self.id, _loads(raw) if raw is not None else None)

    def set(self, data, merge=False):
        data = _resolve_sentinels(data)
        if merge:
            raw = self._client._read(self._coll, self.id)
            base = _loads(raw) if raw is not None else {}
            base.update(data)
            data = base
        self._client._write(self._coll, self.id, _dumps(data))

    def update(self, data):
        # Firestore's update merges top-level keys into an existing document.
        data = _resolve_sentinels(data)
        raw = self._client._read(self._coll, self.id)
        base = _loads(raw) if raw is not None else {}
        base.update(data)
        self._client._write(self._coll, self.id, _dumps(base))

    def delete(self):
        self._client._delete(self._coll, self.id)


class Query:
    def __init__(self, client, coll, filters=None):
        self._client = client
        self._coll = coll
        self._filters = filters or []

    def where(self, field=None, op=None, value=None, filter=None):
        if filter is not None:
            field, op, value = filter.field, filter.op, filter.value
        return Query(self._client, self._coll, self._filters + [(field, op, value)])

    def stream(self):
        for doc_id, raw in self._client._read_all(self._coll):
            data = _loads(raw)
            if all(_matches(data, f, o, v) for (f, o, v) in self._filters):
                yield DocumentSnapshot(doc_id, data)


class CollectionReference(Query):
    def document(self, doc_id=None):
        return DocumentReference(self._client, self._coll, doc_id or uuid.uuid4().hex)


# --- the SQL-backed client -------------------------------------------------

class Client:
    """The object the app treats as `db`. All access goes through one locked
    connection - fine for a single gunicorn worker with a handful of threads."""

    def __init__(self, conn, backend):
        self._conn = conn
        self._backend = backend            # 'mysql' | 'sqlite'
        self._ph = "%s" if backend == "mysql" else "?"
        self._lock = threading.RLock()
        self._ensure_table()

    def _sql(self, text):
        # SQL is written with '?' placeholders; MySQL wants '%s'.
        return text.replace("?", self._ph) if self._ph != "?" else text

    def _cursor(self):
        if self._backend == "mysql":
            self._conn.ping(reconnect=True)
        return self._conn.cursor()

    def _ensure_table(self):
        if self._backend == "mysql":
            ddl = (
                "CREATE TABLE IF NOT EXISTS fs_documents ("
                " coll VARCHAR(190) NOT NULL,"
                " doc_id VARCHAR(190) NOT NULL,"
                " data LONGTEXT NOT NULL,"
                " PRIMARY KEY (coll, doc_id)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            )
        else:
            ddl = (
                "CREATE TABLE IF NOT EXISTS fs_documents ("
                " coll TEXT NOT NULL, doc_id TEXT NOT NULL, data TEXT NOT NULL,"
                " PRIMARY KEY (coll, doc_id))"
            )
        with self._lock:
            cur = self._cursor()
            cur.execute(ddl)
            self._conn.commit()

    def collection(self, name):
        return CollectionReference(self, name)

    # --- storage primitives used by the view objects ---
    def _read(self, coll, doc_id):
        with self._lock:
            cur = self._cursor()
            cur.execute(self._sql(
                "SELECT data FROM fs_documents WHERE coll=? AND doc_id=?"), (coll, doc_id))
            row = cur.fetchone()
            return row[0] if row else None

    def _read_all(self, coll):
        with self._lock:
            cur = self._cursor()
            cur.execute(self._sql(
                "SELECT doc_id, data FROM fs_documents WHERE coll=?"), (coll,))
            return list(cur.fetchall())

    def _write(self, coll, doc_id, data_json):
        with self._lock:
            cur = self._cursor()
            # Dialect-agnostic upsert: try update, insert if nothing was updated.
            cur.execute(self._sql(
                "UPDATE fs_documents SET data=? WHERE coll=? AND doc_id=?"),
                (data_json, coll, doc_id))
            if cur.rowcount == 0:
                cur.execute(self._sql(
                    "INSERT INTO fs_documents (coll, doc_id, data) VALUES (?, ?, ?)"),
                    (coll, doc_id, data_json))
            self._conn.commit()

    def _delete(self, coll, doc_id):
        with self._lock:
            cur = self._cursor()
            cur.execute(self._sql(
                "DELETE FROM fs_documents WHERE coll=? AND doc_id=?"), (coll, doc_id))
            self._conn.commit()


# --- connection / configuration --------------------------------------------

def _connect_from_url(url):
    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0]  # mysql+pymysql -> mysql

    if scheme == "sqlite":
        import sqlite3
        # sqlite:///rel or sqlite:////abs or sqlite:///:memory:
        path = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ":memory:"
        conn = sqlite3.connect(path, check_same_thread=False)
        return conn, "sqlite"

    if scheme in ("mysql", "mariadb"):
        import pymysql
        conn = pymysql.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=(parsed.path or "/").lstrip("/"),
            charset="utf8mb4",
            # autocommit is essential: with a long-lived connection and InnoDB's
            # default REPEATABLE READ, a non-autocommit read transaction keeps a
            # frozen snapshot and never sees rows another connection commits
            # (e.g. the seed script, or a second worker). autocommit makes every
            # statement its own transaction, so reads always see latest-committed.
            autocommit=True,
        )
        return conn, "mysql"

    raise ValueError(f"Unsupported DATABASE_URL scheme: {scheme!r}")


def connect():
    """Build a Client from DATABASE_URL, or None when it is not configured.

    Mirrors the old _init_firestore contract: never raises on a missing config
    (the app runs read-only without a DB); a bad/unreachable URL prints a
    warning and also returns None, so one route can report it rather than the
    whole process failing to import.
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None
    try:
        conn, backend = _connect_from_url(url)
        return Client(conn, backend)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Database not available ({url.split('@')[-1]}): {e}")
        return None


# Compatibility alias: some call sites did `firestore.client()`.
def client():
    return connect()
