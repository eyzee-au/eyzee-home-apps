"""HTTPS-facing API. Run behind a TLS reverse proxy; never on the HAOS host."""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from subscription_service.store import Store, now


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Activation(BaseModel):
    code: str = Field(min_length=10, max_length=100)
    installation_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    credential: str = Field(min_length=40, max_length=128)


def create_app(settings=None):
    config = dict(os.environ if settings is None else settings)
    required = ["EYZEE_DATA_KEY", "EYZEE_SIGNING_KEY", "EYZEE_SHOPIFY_SECRET", "EYZEE_SHOP_DOMAIN"]
    if any(not config.get(k) for k in required):
        raise RuntimeError("Configure the data key, signing key, Shopify secret and store domain before starting")
    domain = config["EYZEE_SHOP_DOMAIN"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", domain):
        raise RuntimeError("Use the actual Shopify myshopify.com domain")
    store = Store(config.get("EYZEE_DATA_DIR", "/data"), config["EYZEE_DATA_KEY"])
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(config["EYZEE_SIGNING_KEY"]))
    variants = json.loads(config.get("EYZEE_VARIANTS", "{}"))
    for variant, spec in variants.items():
        if (not variant.isdigit() or spec.get("plan") not in {"core", "home"} or
            spec.get("action") not in {"activation", "included", "subscription", "renewal"} or
            type(spec.get("months", 12)) is not int or not 1 <= spec.get("months", 12) <= 120):
            raise RuntimeError("Invalid Shopify variant mapping")
    app = FastAPI(title="EyZEE Updates & Support", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.config = store, config
    attempts = defaultdict(deque)

    @app.middleware("http")
    async def limits(request, call_next):
        # At the reverse proxy also enforce IP limits and 1 MiB body limits.
        if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 1_048_576:
            return JSONResponse({"error": "Request too large"}, status_code=413)
        if request.url.path == "/v1/activate":
            client = request.client.host
            recent = attempts[client]
            current = time.monotonic()
            while recent and recent[0] < current - 60:
                recent.popleft()
            if len(recent) >= 10:
                return JSONResponse({"error": "Please wait a minute before trying again."}, status_code=429)
            recent.append(current)
            if len(attempts) > 10000:
                for address in list(attempts):
                    if not attempts[address] or attempts[address][-1] < current - 60:
                        del attempts[address]
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"error": str(error)}, status_code=409)

    def customer(request):
        try:
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                raise ValueError()
            ident, secret = header[7:].split(":", 1)
            return store.authenticate(ident, secret)
        except (ValueError, PermissionError):
            raise HTTPException(401, "Reopen EyZEE activation or contact support.") from None

    def eligible(row, release):
        return bool(row["activated_at"]) and not row["revoked"] and (
            row["expires_at"] is None or release["published_at"] <= row["expires_at"])

    def admin(request):
        token = config.get("EYZEE_ADMIN_TOKEN", "")
        if len(token) < 32 or not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Administrator sign-in required")

    @app.get("/admin")
    def admin_page():
        from fastapi.responses import HTMLResponse
        return HTMLResponse((Path(__file__).parent / "admin.html").read_text(), headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer"})

    @app.get("/admin/overview")
    def overview(request: Request):
        admin(request)
        with store.db() as db:
            return {"customers": [{"email": row["email"], **store.public(row)} for row in db.execute("SELECT * FROM entitlements ORDER BY created_at DESC LIMIT 500")],
                    "review": [dict(r) for r in db.execute("SELECT * FROM review WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 100")],
                    "pending_emails": db.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0]}

    @app.post("/admin/grants")
    async def grant(request: Request):
        admin(request)
        body = await request.json()
        with store.db() as db:
            ident = store.create(db, body["email"], body["plan"], body.get("kind", "beta"), int(body.get("months", 12)))
        return {"entitlement_id": ident, "email_queued": True}

    @app.post("/admin/resend/{ident}")
    def resend(ident: str, request: Request):
        admin(request)
        from uuid import uuid4
        with store.db() as db:
            row = db.execute("SELECT * FROM entitlements WHERE id=?", (ident,)).fetchone()
            if not row:
                raise HTTPException(404)
            db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,NULL)", (str(uuid4()), ident, row["email"], "activation", now()))
        return {"email_queued": True}

    @app.post("/admin/transfer/{ident}")
    async def transfer(ident: str, request: Request):
        admin(request)
        body = await request.json()
        if body.get("confirm") is not True:
            raise HTTPException(400, "Confirm the hardware transfer")
        store.transfer(ident)
        return {"email_queued": True}

    @app.post("/admin/review/{ident:path}/resolve")
    async def resolve(ident: str, request: Request):
        admin(request)
        body = await request.json()
        if body.get("action") not in {"retry", "dismiss"}:
            raise HTTPException(400, "Choose retry or dismiss")
        with store.db() as db:
            if body["action"] == "retry":
                db.execute("UPDATE inbox SET processed=0,error=NULL WHERE id=?", (ident,))
            db.execute("UPDATE review SET resolved_at=? WHERE id=?", (now(), ident))
        return {"accepted": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/v1/activate")
    def activate(body: Activation):
        return store.activate(body.code, body.installation_id, body.credential)

    @app.get("/v1/entitlement")
    def entitlement(request: Request):
        return store.public(customer(request))

    @app.get("/v1/releases/latest")
    def latest(request: Request):
        row = customer(request)
        with store.db() as db:
            releases = db.execute("SELECT * FROM releases WHERE enabled=1 ORDER BY published_at DESC,version DESC").fetchall()
        release = next((r for r in releases if eligible(row, r)), None)
        if not release:
            raise HTTPException(404, "No authorised release is available. Contact EyZEE support.")
        manifest = {k: release[k] for k in ("version", "sha256", "size", "published_at")}
        manifest["download_path"] = "/v1/download/" + release["version"]
        return {"manifest": manifest, "signature": base64.b64encode(key.sign(canonical(manifest))).decode(),
                "entitlement": store.public(row)}

    @app.get("/v1/download/{version}")
    def download(version: str, request: Request):
        row = customer(request)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
            raise HTTPException(404)
        with store.db() as db:
            release = db.execute("SELECT * FROM releases WHERE version=? AND enabled=1", (version,)).fetchone()
        if not release or not eligible(row, release):
            raise HTTPException(403, "This release requires an active updates subscription.")
        path = store.root / "releases" / (version + ".zip")
        if not path.is_file():
            raise HTTPException(503, "Download temporarily unavailable. Please retry later.")
        return FileResponse(path, media_type="application/zip", filename="EyZEE-" + version + ".zip")

    @app.post("/webhooks/shopify")
    async def shopify(request: Request):
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 1_048_576:
                raise HTTPException(413)
        expected = base64.b64encode(hmac.new(config["EYZEE_SHOPIFY_SECRET"].encode(), bytes(body), hashlib.sha256).digest()).decode()
        if not hmac.compare_digest(expected, request.headers.get("x-shopify-hmac-sha256", "")):
            raise HTTPException(401, "Invalid signature")
        if request.headers.get("x-shopify-shop-domain") != domain:
            raise HTTPException(401, "Unknown store")
        topic = request.headers.get("x-shopify-topic")
        if topic not in {"orders/paid", "orders/cancelled", "refunds/create"}:
            raise HTTPException(400, "Unsupported topic")
        ident = request.headers.get("x-shopify-webhook-id", "")
        if not ident or len(ident) > 200:
            raise HTTPException(400, "Missing delivery ID")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON") from None
        store.receive(ident, topic, payload)
        # Durable receipt first. A separate worker processes and emails; webhook
        # response latency never depends on SMTP or entitlement provisioning.
        return {"received": True}

    return app
