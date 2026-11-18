"""Operator commands. Run on the service host with its environment loaded."""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from subscription_service.store import Store, now
from subscription_service.worker import deliver, reconcile


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keys")
    grant = sub.add_parser("grant")
    grant.add_argument("--email", required=True)
    grant.add_argument("--plan", choices=["core", "home"], required=True)
    grant.add_argument("--kind", choices=["paid", "included", "beta"], default="beta")
    grant.add_argument("--months", type=int, default=12)
    launch = sub.add_parser("launch-beta")
    launch.add_argument("--date", required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("archive", type=Path)
    sub.add_parser("list")
    sub.add_parser("process")
    sub.add_parser("reconcile")
    resend = sub.add_parser("resend")
    resend.add_argument("entitlement_id")
    transfer = sub.add_parser("transfer")
    transfer.add_argument("entitlement_id")
    args = parser.parse_args()
    if args.command == "keys":
        key = Ed25519PrivateKey.generate()
        print("EYZEE_DATA_KEY=" + Fernet.generate_key().decode())
        print("EYZEE_SIGNING_KEY=" + base64.b64encode(key.private_bytes_raw()).decode())
        print("EYZEE_RELEASE_PUBLIC_KEY=" + base64.b64encode(key.public_key().public_bytes_raw()).decode())
        print("EYZEE_ADMIN_TOKEN=" + secrets.token_urlsafe(40))
        return
    config = dict(os.environ)
    store = Store(config.get("EYZEE_DATA_DIR", "/data"), config["EYZEE_DATA_KEY"])
    if args.command == "grant":
        with store.db() as db:
            ident = store.create(db, args.email, args.plan, args.kind, args.months)
        print(json.dumps({"entitlement_id": ident, "email_queued": True}))
    elif args.command == "launch-beta":
        store.launch_beta(args.date)
        print("Founding Beta launch date recorded")
    elif args.command == "publish":
        data = args.archive.read_bytes()
        if len(data) > 50_000_000:
            raise ValueError("Release exceeds the 50 MB limit")
        with zipfile.ZipFile(args.archive) as archive:
            manifest = json.loads(archive.read("release.json"))
        version = manifest["version"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
            raise ValueError("Invalid release version")
        directory = store.root / "releases"
        directory.mkdir(exist_ok=True, mode=0o700)
        target = directory / (version + ".zip")
        # Version numbers are immutable; accidentally reusing one must fail.
        with store.db() as db:
            if target.exists() or db.execute("SELECT 1 FROM releases WHERE version=?", (version,)).fetchone():
                raise ValueError("Release version already exists")
            with target.open("xb") as output:
                output.write(data)
            target.chmod(0o600)
            db.execute("INSERT INTO releases(version,published_at,sha256,size) VALUES (?,?,?,?)",
                       (version, now(), hashlib.sha256(data).hexdigest(), len(data)))
        print("Published " + version)
    elif args.command == "list":
        with store.db() as db:
            result = {"customers": [dict(r) for r in db.execute("SELECT id,email,plan,kind,expires_at,installation_id,revoked FROM entitlements")],
                "review": [dict(r) for r in db.execute("SELECT * FROM review WHERE resolved_at IS NULL")],
                "pending_emails": db.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0]}
        print(json.dumps(result, indent=2))
    elif args.command in {"resend", "transfer"}:
        if args.command == "transfer":
            store.transfer(args.entitlement_id)
            print("Replacement activation email queued; paid expiry unchanged")
            return
        with store.db() as db:
            row = db.execute("SELECT * FROM entitlements WHERE id=?", (args.entitlement_id,)).fetchone()
            if not row:
                raise ValueError("Entitlement not found")
            db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)",
                (secrets.token_hex(16), row["id"], row["email"], "activation", now()))
            db.execute("INSERT INTO audit(action,target,at) VALUES (?,?,?)", (args.command, row["id"], now()))
        print("Activation email queued")
    elif args.command == "reconcile":
        print("Reconciled" if reconcile(store, config) else "Configure the Shopify read-orders access token")
    elif args.command == "process":
        store.process_inbox(json.loads(config.get("EYZEE_VARIANTS", "{}")))
        print(json.dumps({"emails_sent": deliver(store, config)}))


if __name__ == "__main__":
    main()
