"""Transactional entitlements. No subscription state controls home operation."""
import calendar
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet


ACTIVATION_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_months(value, months):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("A timezone is required")
    year, month = divmod(date.year * 12 + date.month - 1 + months, 12)
    return date.replace(year=year, month=month + 1,
                        day=min(date.day, calendar.monthrange(year, month + 1)[1])).astimezone(timezone.utc).isoformat(timespec="seconds")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def activation_code():
    payload = "".join(secrets.choice(ACTIVATION_ALPHABET) for _ in range(16))
    return "EYZ-" + "-".join(payload[index:index + 4] for index in range(0, 16, 4))


def activation_code_candidates(value):
    upper = value.strip().upper()
    candidates = [upper]
    compact = "".join(character for character in upper if character not in "- \t\r\n")
    if not compact.startswith("EYZ"):
        return candidates
    payload = compact[3:]
    if len(payload) == 16 and all(character in ACTIVATION_ALPHABET for character in payload):
        candidates.append("EYZ-" + "-".join(payload[index:index + 4] for index in range(0, 16, 4)))
    elif len(payload) == 32 and all(character in "0123456789ABCDEF" for character in payload):
        candidates.append("EYZ-" + payload)
    return list(dict.fromkeys(candidates))


class Store:
    def __init__(self, directory, data_key):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = Fernet(data_key.encode())
        self.path = self.root / "subscriptions.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entitlements (
                    id TEXT PRIMARY KEY, customer_id TEXT, email TEXT NOT NULL,
                    plan TEXT NOT NULL, kind TEXT NOT NULL, months INTEGER NOT NULL,
                    created_at TEXT NOT NULL, activated_at TEXT, expires_at TEXT,
                    installation_id TEXT UNIQUE, credential_hash TEXT, code_hash TEXT UNIQUE,
                    encrypted_code TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS payments (
                    id TEXT PRIMARY KEY, entitlement_id TEXT NOT NULL, at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inbox (
                    id TEXT PRIMARY KEY, topic TEXT NOT NULL, payload TEXT NOT NULL,
                    received_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
                    error TEXT);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, entitlement_id TEXT NOT NULL, email TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT);
                CREATE TABLE IF NOT EXISTS review (
                    id TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                    resolved_at TEXT);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS releases (
                    version TEXT PRIMARY KEY, published_at TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, action TEXT NOT NULL, target TEXT NOT NULL, at TEXT NOT NULL);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, db, email, plan, kind="paid", months=12, customer_id=None):
        if plan not in {"core", "home"} or kind not in {"paid", "included", "beta"}:
            raise ValueError("Unknown plan or grant type")
        if not 1 <= months <= 120 or "@" not in email or len(email) > 254 or any(c in email for c in "\r\n"):
            raise ValueError("Invalid grant")
        ident = str(uuid4())
        code = activation_code()
        db.execute("""INSERT INTO entitlements
            (id,customer_id,email,plan,kind,months,created_at,code_hash,encrypted_code)
            VALUES (?,?,?,?,?,?,?,?,?)""", (ident, customer_id, email.lower(), plan, kind, months,
                now(), digest(code), self.cipher.encrypt(code.encode()).decode()))
        db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)",
                   (str(uuid4()), ident, email.lower(), "activation", now()))
        db.execute("INSERT INTO audit(action,target,at) VALUES ('grant',?,?)", (ident, now()))
        return ident

    def launch_beta(self, date):
        date = datetime.fromisoformat(date.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("A timezone is required")
        date = date.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self.db() as db:
            previous = db.execute("SELECT value FROM settings WHERE key='beta_launch'").fetchone()
            if previous and previous[0] != date:
                raise ValueError("Beta launch already set; changing it needs an explicit migration")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('beta_launch',?)", (date,))
            for row in db.execute("SELECT * FROM entitlements WHERE kind='beta'").fetchall():
                expiry = add_months(date, row["months"])
                # Never shorten access purchased after the beta grant.
                if not row["expires_at"] or row["expires_at"] < expiry:
                    db.execute("UPDATE entitlements SET expires_at=? WHERE id=?", (expiry, row["id"]))

    def activate(self, code, installation_id, credential):
        with self.db() as db:
            row = None
            for candidate in activation_code_candidates(code):
                row = db.execute("SELECT * FROM entitlements WHERE code_hash=?", (digest(candidate),)).fetchone()
                if row:
                    break
            if not row or row["revoked"]:
                raise ValueError("This activation code could not be verified. Check it or contact EyZEE.")
            if row["installation_id"]:
                if row["installation_id"] != installation_id or not hmac.compare_digest(row["credential_hash"], digest(credential)):
                    raise ValueError("This code is already activated. Contact EyZEE to move it to another system.")
                return self.public(row)
            if db.execute("SELECT 1 FROM entitlements WHERE installation_id=?", (installation_id,)).fetchone():
                raise ValueError("This installation is already activated. Contact EyZEE to change its plan.")
            at = row["activated_at"] or now()
            expiry = row["expires_at"]
            if row["kind"] == "beta":
                launch = db.execute("SELECT value FROM settings WHERE key='beta_launch'").fetchone()
                expiry = expiry or (add_months(launch[0], row["months"]) if launch else None)
            else:
                expiry = expiry or add_months(at, row["months"])
            db.execute("""UPDATE entitlements SET activated_at=?,expires_at=?,installation_id=?,credential_hash=?
                WHERE id=?""", (at, expiry, installation_id, digest(credential), row["id"]))
            db.execute("INSERT INTO audit(action,target,at) VALUES ('activate',?,?)", (row["id"], at))
            return self.public(db.execute("SELECT * FROM entitlements WHERE id=?", (row["id"],)).fetchone())

    def transfer(self, ident):
        """Invalidate the old installation and send a new code without resetting expiry."""
        with self.db() as db:
            row = db.execute("SELECT * FROM entitlements WHERE id=?", (ident,)).fetchone()
            if not row:
                raise ValueError("Entitlement not found")
            code = activation_code()
            db.execute("UPDATE entitlements SET installation_id=NULL,credential_hash=NULL,code_hash=?,encrypted_code=? WHERE id=?",
                (digest(code), self.cipher.encrypt(code.encode()).decode(), ident))
            db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)", (str(uuid4()), ident, row["email"], "activation", now()))
            db.execute("INSERT INTO audit(action,target,at) VALUES ('transfer',?,?)", (ident, now()))

    def authenticate(self, installation_id, credential):
        with self.db() as db:
            row = db.execute("SELECT * FROM entitlements WHERE installation_id=?", (installation_id,)).fetchone()
        if not row or not row["credential_hash"] or not hmac.compare_digest(row["credential_hash"], digest(credential)):
            raise PermissionError("Installation credentials could not be verified.")
        return dict(row)

    def public(self, row):
        active = bool(row["activated_at"]) and not row["revoked"] and (
            row["expires_at"] is None or row["expires_at"] > now())
        return {"entitlement_id": row["id"], "plan": row["plan"], "kind": row["kind"],
                "expires_at": row["expires_at"], "active": active,
                "status": "revoked" if row["revoked"] else "active" if active else "expired" if row["activated_at"] else "unactivated"}

    def renew(self, db, row, months, payment_id):
        if db.execute("SELECT 1 FROM payments WHERE id=?", (payment_id,)).fetchone():
            return
        if row["revoked"]:
            raise ValueError("Revoked entitlement needs review")
        if row["activated_at"]:
            expiry = add_months(max(row["expires_at"] or now(), now()), months)
            db.execute("UPDATE entitlements SET expires_at=? WHERE id=?", (expiry, row["id"]))
        else:
            db.execute("UPDATE entitlements SET months=months+? WHERE id=?", (months, row["id"]))
        db.execute("INSERT INTO payments VALUES (?,?,?)", (payment_id, row["id"], now()))
        db.execute("INSERT INTO audit(action,target,at) VALUES ('renew',?,?)", (row["id"], now()))

    def receive(self, ident, topic, payload):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO inbox(id,topic,payload,received_at) VALUES (?,?,?,?)",
                       (ident, topic, self.cipher.encrypt(json.dumps(payload).encode()).decode(), now()))

    def process_inbox(self, variants):
        with self.db() as db:
            events = db.execute("SELECT * FROM inbox WHERE processed=0 ORDER BY received_at,id LIMIT 100").fetchall()
            for event in events:
                order = json.loads(self.cipher.decrypt(event["payload"].encode()))
                db.execute("SAVEPOINT event")
                try:
                    if event["topic"] == "orders/paid":
                        self.process_order(db, order, variants)
                    else:
                        # Refund/cancellation review never switches off a home or erases paid time.
                        db.execute("INSERT OR IGNORE INTO review VALUES (?,?,?,NULL)",
                                   (event["id"], "Refund or order cancellation requires review: " + str(order.get("order_id", order.get("id", "unknown"))), now()))
                    db.execute("UPDATE inbox SET processed=1,error=NULL WHERE id=?", (event["id"],))
                    db.execute("RELEASE event")
                except (ValueError, KeyError, TypeError):
                    db.execute("ROLLBACK TO event")
                    db.execute("RELEASE event")
                    db.execute("UPDATE inbox SET error='Order mapping requires review',processed=1 WHERE id=?", (event["id"],))
                    db.execute("INSERT OR IGNORE INTO review VALUES (?,?,?,NULL)", (event["id"], "Order mapping requires review", now()))

    def process_order(self, db, order, variants):
        if order.get("test") or order.get("financial_status") != "paid" or order.get("cancelled_at"):
            return
        email = (order.get("email") or order.get("contact_email") or "").lower()
        customer_id = str((order.get("customer") or {}).get("id") or "")
        for line in order.get("line_items", []):
            spec = variants.get(str(line.get("variant_id")))
            if not spec:
                continue
            if "@" not in email or not customer_id:
                raise ValueError("Paid order has no customer identity")
            quantity = line.get("quantity", 0)
            if type(quantity) is not int or not 1 <= quantity <= 100:
                raise ValueError("Invalid quantity")
            for unit in range(quantity):
                payment_id = f'{order["id"]}:{line["id"]}:{unit}'
                if db.execute("SELECT 1 FROM payments WHERE id=?", (payment_id,)).fetchone():
                    continue
                plan, action = spec["plan"], spec["action"]
                months = spec.get("months", 12)
                if action in {"renewal", "subscription"}:
                    properties = {p["name"]: str(p.get("value", "")) for p in line.get("properties", [])}
                    ident = properties.get("_eyzee_entitlement_id")
                    rows = db.execute("SELECT * FROM entitlements WHERE customer_id=? AND plan=?" +
                        (" AND id=?" if ident else ""), (customer_id, plan, ident) if ident else (customer_id, plan)).fetchall()
                    if action == "subscription" and not rows and not ident and quantity == 1:
                        ident = self.create(db, email, plan, "paid", months, customer_id)
                        db.execute("INSERT INTO payments VALUES (?,?,?)", (payment_id, ident, now()))
                        continue
                    if len(rows) != 1 or quantity != 1:
                        raise ValueError("Renewal must identify exactly one installation")
                    self.renew(db, rows[0], months, payment_id)
                elif action in {"activation", "included"}:
                    ident = self.create(db, email, plan, "included" if action == "included" else "paid", months, customer_id)
                    db.execute("INSERT INTO payments VALUES (?,?,?)", (payment_id, ident, now()))
                else:
                    raise ValueError("Unknown product action")
