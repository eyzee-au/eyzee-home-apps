"""Durable order processing, retryable emails, and order reconciliation."""
import json
import os
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.request import Request, urlopen

from subscription_service.store import Store, now


def queue_reminders(store, config):
    current = datetime.fromisoformat(now())
    with store.db() as db:
        for row in db.execute("SELECT * FROM entitlements WHERE activated_at IS NOT NULL AND expires_at IS NOT NULL AND revoked=0").fetchall():
            url = config.get("EYZEE_RENEWAL_URL_" + row["plan"].upper(), "")
            if not url.startswith("https://"):
                continue
            remaining = (datetime.fromisoformat(row["expires_at"]) - current).total_seconds() / 86400
            for days in (0, 1, 7, 30):
                if days - 1 < remaining <= days or (days == 0 and -1 < remaining <= 0):
                    ident = f'reminder:{row["id"]}:{row["expires_at"]}:{days}'
                    db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?,?,?,NULL)",
                        (ident, row["id"], row["email"], "reminder:" + str(days), now()))
                    break


def deliver(store, config):
    if not config.get("EYZEE_SMTP_HOST") or not config.get("EYZEE_EMAIL_FROM"):
        return 0
    with store.db() as db:
        messages = db.execute("""SELECT o.*,e.encrypted_code,e.plan FROM outbox o
            JOIN entitlements e ON e.id=o.entitlement_id WHERE sent_at IS NULL LIMIT 25""").fetchall()
    count = 0
    for row in messages:
        email = EmailMessage()
        email["From"] = config["EYZEE_EMAIL_FROM"]
        email["To"] = row["email"]
        email["Message-ID"] = "<" + hashlib_id(row["id"]) + "@" + config["EYZEE_SHOP_DOMAIN"] + ">"
        if row["kind"].startswith("reminder:"):
            email["Subject"] = "Your EyZEE updates and support subscription"
            email.set_content("Your EyZEE updates and support access is approaching expiry or has just expired.\n\n"
                "Your installed home keeps working. Renew to continue receiving new EyZEE updates and direct support.\n"
                "Renewal information: " + config["EYZEE_RENEWAL_URL_" + row["plan"].upper()] + "\n\n"
                "If you have already arranged automatic renewal, please check your Shopify account before making another purchase.\n"
                "Help and guides: https://eyzee.au/eyzee-home/support/\n")
        else:
            code = store.cipher.decrypt(row["encrypted_code"].encode()).decode()
            email["Subject"] = "Your EyZEE " + row["plan"].title() + " activation code"
            email.set_content("Welcome to EyZEE.\n\nYour activation code is:\n" + code +
                "\n\nEnter this code in EyZEE Setup on your Home Assistant system.\n"
                "Installation guide: https://eyzee.au/eyzee-core/downloads/\n\n"
                "Your subscription provides software updates and support. Your installed system keeps working if you do not renew.\n"
                "Public help: https://eyzee.au/eyzee-home/support/\n")
        # SMTP is deliberately outside the DB transaction. A crash after SMTP may
        # resend the SAME code, but cannot grant a second subscription.
        with smtplib.SMTP(config["EYZEE_SMTP_HOST"], int(config.get("EYZEE_SMTP_PORT", "587")), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if config.get("EYZEE_SMTP_USER"):
                smtp.login(config["EYZEE_SMTP_USER"], config["EYZEE_SMTP_PASSWORD"])
            smtp.send_message(email)
        with store.db() as db:
            db.execute("UPDATE outbox SET sent_at=? WHERE id=?", (now(), row["id"]))
        count += 1
    return count


def hashlib_id(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


QUERY = """query PaidOrders($after:String,$query:String!) {
  orders(first:25,after:$after,query:$query,sortKey:UPDATED_AT) {
    pageInfo {hasNextPage endCursor}
    nodes { id email test cancelledAt displayFinancialStatus updatedAt
      customer { id }
      lineItems(first:100) { pageInfo {hasNextPage} nodes {
        id quantity variant {id} customAttributes {key value}
      }}
    }
  }
}"""


def reconcile(store, config):
    """Read-only Shopify API backfill. Same payment IDs as webhook processing."""
    if not config.get("EYZEE_SHOPIFY_ACCESS_TOKEN"):
        return False
    with store.db() as db:
        checkpoint = db.execute("SELECT value FROM settings WHERE key='reconciled_at'").fetchone()
    started = now()
    since = (datetime.fromisoformat(checkpoint[0]) - timedelta(days=2) if checkpoint else
             datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    after = None
    for _ in range(100):
        request = Request("https://" + config["EYZEE_SHOP_DOMAIN"] + "/admin/api/2026-10/graphql.json",
            data=json.dumps({"query": QUERY, "variables": {"after": after, "query": "updated_at:>=" + since}}).encode(),
            headers={"Content-Type": "application/json", "X-Shopify-Access-Token": config["EYZEE_SHOPIFY_ACCESS_TOKEN"]})
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read(4_000_000))
        if result.get("errors"):
            raise RuntimeError("Shopify reconciliation failed; check API access")
        orders = result["data"]["orders"]
        for order in orders["nodes"]:
            if order["lineItems"]["pageInfo"]["hasNextPage"]:
                with store.db() as db:
                    db.execute("INSERT OR IGNORE INTO review VALUES (?,?,?,NULL)",
                        (order["id"], "Order has over 100 lines; reconcile separately", now()))
                continue
            payload = {"id": order["id"].split("/")[-1], "email": order["email"],
                       "test": order["test"], "cancelled_at": order["cancelledAt"],
                       "financial_status": order["displayFinancialStatus"].lower(),
                       "customer": {"id": (order["customer"] or {}).get("id", "").split("/")[-1]},
                       "line_items": [{"id": line["id"].split("/")[-1], "quantity": line["quantity"],
                         "variant_id": (line["variant"] or {}).get("id", "").split("/")[-1],
                         "properties": [{"name": p["key"], "value": p["value"]} for p in line["customAttributes"]]}
                         for line in order["lineItems"]["nodes"]]}
            topic = "orders/cancelled" if order["cancelledAt"] else "refunds/create" if "REFUND" in order["displayFinancialStatus"] else "orders/paid"
            store.receive("reconcile:" + order["id"] + ":" + order["updatedAt"], topic, payload)
        if not orders["pageInfo"]["hasNextPage"]:
            with store.db() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES ('reconciled_at',?)", (started,))
            return True
        after = orders["pageInfo"]["endCursor"]
    raise RuntimeError("Reconciliation page limit reached; checkpoint not advanced")


def main():
    config = dict(os.environ)
    store = Store(config.get("EYZEE_DATA_DIR", "/data"), config["EYZEE_DATA_KEY"])
    last_reconcile = 0
    while True:
        if time.monotonic() - last_reconcile > 3600:
            try:
                reconcile(store, config)
                last_reconcile = time.monotonic()
            except Exception:
                print("Shopify reconciliation needs retry; webhook processing continues", flush=True)
        try:
            store.process_inbox(json.loads(config.get("EYZEE_VARIANTS", "{}")))
            queue_reminders(store, config)
            deliver(store, config)
        except Exception:
            # Never log customer payloads, activation codes, secrets or credentials.
            print("EyZEE worker retry required; check configuration and operator review queue", flush=True)
        time.sleep(15)


if __name__ == "__main__":
    main()
