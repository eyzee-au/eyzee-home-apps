import base64
import hashlib
import hmac
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eyzee_setup"))
sys.path.insert(0, str(ROOT))
from subscription_service.app import create_app
from subscription_service.store import ACTIVATION_ALPHABET, activation_code, activation_code_candidates, add_months, digest, now
from subscription_service.worker import deliver, reconcile, queue_reminders
from subscription import SubscriptionClient, SubscriptionError
from tools.build_release import build
from installer import Installer, sha


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.settings = {"EYZEE_DATA_DIR": str(self.root / "service"), "EYZEE_DATA_KEY": Fernet.generate_key().decode(),
            "EYZEE_SIGNING_KEY": base64.b64encode(self.key.private_bytes_raw()).decode(),
            "EYZEE_SHOPIFY_SECRET": "test-only-shopify-secret", "EYZEE_SHOP_DOMAIN": "eyzee-test.myshopify.com",
            "EYZEE_ADMIN_TOKEN": "test-only-admin-token-with-more-than-32-characters",
            "EYZEE_VARIANTS": json.dumps({"11": {"plan": "core", "action": "subscription"},
                "12": {"plan": "home", "action": "included"}, "13": {"plan": "home", "action": "subscription"}})}
        self.app = create_app(self.settings)
        self.http = TestClient(self.app)
        self.addCleanup(self.http.close)
        self.store = self.app.state.store
        self.client = SubscriptionClient(self.root / "client", "https://updates.example.test",
            base64.b64encode(self.key.public_key().public_bytes_raw()).decode(), self.transport)

    def transport(self, path, body=None, binary=False):
        headers = {}
        if self.client.state.get("credential"):
            headers["Authorization"] = "Bearer " + self.client.state["installation_id"] + ":" + self.client.state["credential"]
        response = self.http.post(path, json=body, headers=headers) if body is not None else self.http.get(path, headers=headers)
        if response.status_code >= 400:
            raise SubscriptionError(str(response.status_code))
        return response.content if binary else response.json()

    def grant(self, plan="core", kind="paid", customer_id="123"):
        with self.store.db() as db:
            ident = self.store.create(db, "ian@example.test", plan, kind, customer_id=customer_id)
            row = db.execute("SELECT * FROM entitlements WHERE id=?", (ident,)).fetchone()
        return ident, self.store.cipher.decrypt(row["encrypted_code"].encode()).decode()

    def order(self, order_id=100, variant=11, customer_id=123, quantity=1):
        return {"id": order_id, "email": "ian@example.test", "financial_status": "paid", "test": False,
            "customer": {"id": customer_id}, "line_items": [{"id": order_id + 1000, "variant_id": variant, "quantity": quantity, "properties": []}]}

    def webhook(self, order, ident="delivery-1", signature=None, domain=None, topic="orders/paid"):
        body = json.dumps(order).encode()
        signature = signature or base64.b64encode(hmac.new(self.settings["EYZEE_SHOPIFY_SECRET"].encode(), body, hashlib.sha256).digest()).decode()
        return self.http.post("/webhooks/shopify", content=body, headers={"X-Shopify-Hmac-Sha256": signature,
            "X-Shopify-Shop-Domain": domain or self.settings["EYZEE_SHOP_DOMAIN"], "X-Shopify-Webhook-Id": ident,
            "X-Shopify-Topic": topic})

    def process(self):
        self.store.process_inbox(json.loads(self.settings["EYZEE_VARIANTS"]))

    def publish(self, version="1.0.0", payload=None):
        payload = payload or self.root / "payload"
        integration = payload / "config/custom_components/eyzee_dashboard/__init__.py"
        integration.parent.mkdir(parents=True, exist_ok=True)
        if not integration.exists():
            integration.write_text("# new EyZEE application\n")
        state = payload / "config/eyzee/state/rooms.yaml"
        state.parent.mkdir(parents=True, exist_ok=True)
        if not state.exists():
            state.write_text("rooms: []\n")
        output = self.root / (version + ".zip")
        build(payload, output, version)
        data = output.read_bytes()
        directory = self.store.root / "releases"
        directory.mkdir(exist_ok=True)
        (directory / (version + ".zip")).write_bytes(data)
        with self.store.db() as db:
            db.execute("INSERT INTO releases(version,published_at,sha256,size) VALUES (?,?,?,?)",
                (version, now(), sha(data), len(data)))
        return output

    def test_paid_order_to_activation_to_signed_release_download(self):
        self.assertEqual(200, self.webhook(self.order()).status_code)
        self.process()
        with self.store.db() as db:
            row = db.execute("SELECT * FROM entitlements").fetchone()
        code = self.store.cipher.decrypt(row["encrypted_code"].encode()).decode()
        self.assertIsNone(row["expires_at"])
        self.assertTrue(self.client.activate(code)["active"])
        self.publish()
        manifest = self.client.release()
        stage, metadata = self.client.download(manifest)
        self.assertEqual("1.0.0", metadata["version"])
        self.assertTrue((stage / "payload/config/custom_components/eyzee_dashboard/__init__.py").is_file())
        self.assertNotIn("eyzee/state/rooms.yaml", metadata["update_files"])

    def test_official_service_defaults_survive_beta13_empty_options(self):
        data = self.root / "upgraded-addon-data"
        data.mkdir()
        (data / "options.json").write_text("{}")
        client = SubscriptionClient.configured(data)
        self.assertEqual("https://subscriptions.eyzee.au", client.url)
        self.assertTrue(client.configured_ok())

    def test_friendly_activation_code_format_and_input(self):
        code = activation_code()
        groups = code.split("-")
        self.assertEqual([3, 4, 4, 4, 4], [len(group) for group in groups])
        self.assertEqual("EYZ", groups[0])
        self.assertTrue(all(character in ACTIVATION_ALPHABET for character in "".join(groups[1:])))
        ident, stored = self.grant()
        friendly_input = stored.lower().replace("-", " ")
        response = self.http.post("/v1/activate", json={"code": friendly_input,
            "installation_id": str(uuid4()), "credential": "x" * 50})
        self.assertEqual(200, response.status_code)

    def test_legacy_long_activation_codes_remain_valid(self):
        legacy = "EYZ-0123456789ABCDEF0123456789ABCDEF"
        self.assertIn(legacy, activation_code_candidates(legacy.lower().replace("-", "")))
        with self.store.db() as db:
            ident = str(uuid4())
            db.execute("""INSERT INTO entitlements
                (id,email,plan,kind,months,created_at,code_hash,encrypted_code)
                VALUES (?,?,?,?,?,?,?,?)""", (ident, "legacy@example.test", "core", "paid", 12,
                    now(), digest(legacy), self.store.cipher.encrypt(legacy.encode()).decode()))
        response = self.http.post("/v1/activate", json={"code": legacy.lower().replace("-", ""),
            "installation_id": str(uuid4()), "credential": "x" * 50})
        self.assertEqual(200, response.status_code)

    def test_duplicate_deliveries_and_different_ids_do_not_double_extend(self):
        ident, code = self.grant()
        self.client.activate(code)
        before = self.client.check()["expires_at"]
        order = self.order()
        for delivery in ["same", "same", "different"]:
            self.webhook(order, delivery)
            self.process()
        after = self.client.check()["expires_at"]
        self.assertEqual(add_months(before, 12), after)
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM payments").fetchone()[0])

    def test_invalid_signature_and_unknown_store_rejected(self):
        self.assertEqual(401, self.webhook(self.order(), signature="fake").status_code)
        self.assertEqual(401, self.webhook(self.order(), domain="other.myshopify.com").status_code)
        with self.store.db() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM inbox").fetchone()[0])

    def test_activation_retry_after_lost_response_is_idempotent(self):
        ident, code = self.grant()
        first = self.client.activate(code)
        self.assertEqual(first["expires_at"], self.client.activate(code)["expires_at"])
        self.assertEqual(0o600, self.client.path.stat().st_mode & 0o777)
        reloaded = SubscriptionClient(self.client.data, self.client.url, self.client.public_key, self.transport)
        self.assertEqual(self.client.state["credential"], reloaded.state["credential"])

    def test_second_installation_cannot_redeem_used_code(self):
        ident, code = self.grant()
        self.client.activate(code)
        response = self.http.post("/v1/activate", json={"code": code, "installation_id": str(uuid4()), "credential": "x" * 50})
        self.assertEqual(409, response.status_code)

    def test_unique_installation_id_cannot_claim_another_code(self):
        first, code = self.grant()
        self.client.activate(code)
        second, other = self.grant()
        # Service should refuse a second entitlement on an already bound identity.
        response = self.http.post("/v1/activate", json={"code": other, "installation_id": self.client.state["installation_id"], "credential": self.client.state["credential"]})
        self.assertEqual(409, response.status_code)

    def test_first_year_starts_at_activation_not_purchase(self):
        with patch("subscription_service.store.now", return_value="2026-01-01T00:00:00+00:00"):
            ident, code = self.grant("home", "included")
        with patch("subscription_service.store.now", return_value="2026-03-01T00:00:00+00:00"):
            self.assertEqual("2027-03-01T00:00:00+00:00", self.client.activate(code)["expires_at"])

    def test_beta_runs_through_testing_then_twelve_months_from_launch(self):
        ident, code = self.grant(kind="beta")
        self.assertIsNone(self.client.activate(code)["expires_at"])
        self.assertTrue(self.client.summary()["active"])
        self.store.launch_beta("2027-02-01T00:00:00+00:00")
        self.assertEqual("2028-02-01T00:00:00+00:00", self.client.check()["expires_at"])
        with self.assertRaises(ValueError):
            self.store.launch_beta("2027-03-01T00:00:00+00:00")

    def test_leap_year_renewal_uses_calendar_year(self):
        self.assertEqual("2029-02-28T10:00:00+00:00", add_months("2028-02-29T10:00:00+00:00", 12))

    def test_expired_customer_can_recover_old_release_but_not_new(self):
        ident, code = self.grant()
        self.client.activate(code)
        self.publish("1.0.0")
        self.publish("1.1.0")
        with self.store.db() as db:
            db.execute("UPDATE entitlements SET expires_at='2025-06-01T00:00:00+00:00' WHERE id=?", (ident,))
            db.execute("UPDATE releases SET published_at='2025-01-01T00:00:00+00:00' WHERE version='1.0.0'")
        self.assertFalse(self.client.check()["active"])
        self.assertEqual("1.0.0", self.client.release()["version"])
        with self.assertRaises(SubscriptionError):
            self.transport("/v1/download/1.1.0", binary=True)

    def test_wrong_credentials_cannot_download(self):
        self.publish()
        self.assertEqual(401, self.http.get("/v1/download/1.0.0").status_code)
        ident, code = self.grant()
        self.client.activate(code)
        self.client.state["credential"] = "wrong"
        with self.assertRaises(SubscriptionError):
            self.client.release()

    def test_tampered_signature_or_download_is_rejected(self):
        ident, code = self.grant()
        self.client.activate(code)
        self.publish()
        original = self.transport
        def altered(path, body=None, binary=False):
            result = original(path, body, binary)
            if path.endswith("latest"):
                result["manifest"]["version"] = "fake"
            return result
        self.client.transport = altered
        with self.assertRaisesRegex(SubscriptionError, "signature"):
            self.client.release()
        self.client.transport = original
        manifest = self.client.release()
        self.client.transport = lambda *a, **k: b"altered package"
        with self.assertRaisesRegex(SubscriptionError, "verified"):
            self.client.download(manifest)

    def test_traversal_archive_rejected_even_with_valid_download_hash(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("payload/../escape", "bad")
            archive.writestr("payload-hashes.json", "{}")
            archive.writestr("release.json", '{"version":"1.0.0"}')
        body = output.getvalue()
        self.client.transport = lambda *a, **k: body
        with self.assertRaises(SubscriptionError):
            self.client.download({"download_path": "/v1/download/1.0.0", "size": len(body), "sha256": sha(body), "version": "1.0.0"})
        self.assertFalse((self.client.data / "escape").exists())

    def test_no_subscription_network_check_on_existing_home_startup(self):
        config = self.root / "config"
        integration = config / "custom_components/eyzee_dashboard/__init__.py"
        integration.parent.mkdir(parents=True)
        integration.write_text("# installed")
        self.client.transport = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Must not contact subscription service"))
        installer = Installer(config, self.root / "data", subscription=self.client)
        self.assertTrue(installer.status()["installed"])
        installer.prepare()
        self.assertEqual("# installed", integration.read_text())

    def test_fresh_install_authorisation_fails_before_home_mutations(self):
        from unittest.mock import Mock
        api = Mock()
        installer = Installer(self.root / "config", self.root / "data", api=api, subscription=self.client)
        with self.assertRaises(SubscriptionError):
            installer.prepare()
        api.call.assert_not_called()
        self.assertFalse(installer.config.exists())

    def test_test_orders_and_unrelated_products_do_not_create_access(self):
        for index, order in enumerate([dict(self.order(), test=True), self.order(variant=99), dict(self.order(), financial_status="pending")]):
            self.webhook(order, str(index))
        self.process()
        with self.store.db() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM entitlements").fetchone()[0])

    def test_ambiguous_multi_installation_renewal_enters_review(self):
        self.grant()
        self.grant()
        self.webhook(self.order())
        self.process()
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM review").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM payments").fetchone()[0])

    def test_explicit_renewal_identity_selects_correct_installation(self):
        first, code = self.grant()
        second, _ = self.grant()
        self.client.activate(code)
        before = self.client.check()["expires_at"]
        order = self.order()
        order["line_items"][0]["properties"] = [{"name": "_eyzee_entitlement_id", "value": first}]
        self.webhook(order)
        self.process()
        self.assertEqual(add_months(before, 12), self.client.check()["expires_at"])

    def test_refund_notification_never_disables_existing_home_or_paid_time(self):
        ident, code = self.grant()
        before = self.client.activate(code)["expires_at"]
        self.webhook({"id": 100, "order_id": 200}, topic="refunds/create")
        self.process()
        self.assertEqual(before, self.client.check()["expires_at"])
        self.assertTrue(self.client.summary()["active"])
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM review").fetchone()[0])

    def test_admin_portal_requires_key_and_does_not_return_codes_or_tokens(self):
        ident, code = self.grant()
        self.client.activate(code)
        self.assertEqual(401, self.http.get("/admin/overview").status_code)
        response = self.http.get("/admin/overview", headers={"Authorization": "Bearer " + self.settings["EYZEE_ADMIN_TOKEN"]})
        self.assertEqual(200, response.status_code)
        self.assertNotIn(code, response.text)
        self.assertNotIn(self.client.state["credential"], response.text)
        self.assertEqual("no-store", response.headers["cache-control"])

    def test_order_processing_rolls_back_entire_event_on_ambiguous_line(self):
        self.grant()
        self.grant()
        order = self.order()
        order["line_items"].insert(0, {"id": 999, "variant_id": 12, "quantity": 1})
        self.webhook(order)
        self.process()
        with self.store.db() as db:
            self.assertEqual(2, db.execute("SELECT count(*) FROM entitlements").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM payments").fetchone()[0])

    def make_installer(self):
        self.grant_id, code = self.grant()
        self.client.activate(code)
        self.publish()
        config = self.root / "config"
        path = config / "custom_components/eyzee_dashboard/__init__.py"
        path.parent.mkdir(parents=True)
        path.write_text("# original\n")
        state = config / "eyzee/state/rooms.yaml"
        state.parent.mkdir(parents=True)
        state.write_text("rooms: [Ian's kitchen]\n")
        from unittest.mock import Mock
        api = Mock()
        api.call.return_value = {"slug": "full-backup"}
        installer = Installer(config, self.root / "setup-data", api=api, subscription=self.client)
        installer.state["files"]["custom_components/eyzee_dashboard/__init__.py"] = sha(path.read_bytes())
        installer.state["installation_complete"] = True
        installer.state["installed_release"] = "0.9.0"
        installer.save()
        return installer, path, state

    def test_update_backs_up_preserves_rooms_and_requests_restart(self):
        installer, path, state = self.make_installer()
        installer.apply_update()
        self.assertEqual("# new EyZEE application\n", path.read_text())
        self.assertEqual("rooms: [Ian's kitchen]\n", state.read_text())
        self.assertEqual("1.0.0", installer.state["installed_release"])
        self.assertTrue(any(c.args[0] == "/core/restart" for c in installer.api.call.call_args_list))

    def test_modified_local_file_is_preserved_before_backup(self):
        installer, path, state = self.make_installer()
        path.write_text("# Ian's local fix\n")
        with self.assertRaisesRegex(SubscriptionError, "local EyZEE"):
            installer.apply_update()
        installer.api.call.assert_not_called()
        self.assertEqual("# Ian's local fix\n", path.read_text())

    def test_failed_update_validation_restores_files_and_never_restarts(self):
        installer, path, state = self.make_installer()
        def call(route, *args, **kwargs):
            if route == "/core/check":
                raise ValueError("Invalid configuration")
            return {"slug": "full-backup"}
        installer.api.call.side_effect = call
        with self.assertRaisesRegex(SubscriptionError, "restored"):
            installer.apply_update()
        self.assertEqual("# original\n", path.read_text())
        self.assertEqual("0.9.0", installer.state["installed_release"])
        self.assertFalse(any(c.args[0] == "/core/restart" for c in installer.api.call.call_args_list))

    def test_interrupted_file_write_is_recovered_on_next_setup_start(self):
        installer, path, state = self.make_installer()
        directory = installer.data / "rollback"
        original = directory / "custom_components/eyzee_dashboard/__init__.py"
        original.parent.mkdir(parents=True)
        original.write_bytes(path.read_bytes())
        saved = {"phase": "writing", "directory": str(directory), "originals": {"custom_components/eyzee_dashboard/__init__.py": True},
            "tracked_files": installer.state["files"], "installed_release": "0.9.0"}
        (installer.data / "update-journal.json").write_text(json.dumps(saved))
        path.write_text("# interrupted partial update\n")
        restarted = Installer(installer.config, installer.data, api=installer.api, subscription=self.client)
        self.assertEqual("# original\n", path.read_text())
        self.assertEqual("0.9.0", restarted.state["installed_release"])
        self.assertFalse((installer.data / "update-journal.json").exists())

    def test_hardware_transfer_invalidates_old_credentials_without_new_free_year(self):
        ident, code = self.grant("home", "included")
        before = self.client.activate(code)["expires_at"]
        self.store.transfer(ident)
        with self.assertRaises(SubscriptionError):
            self.client.check()
        with self.store.db() as db:
            row = db.execute("SELECT * FROM entitlements WHERE id=?", (ident,)).fetchone()
        replacement = self.store.cipher.decrypt(row["encrypted_code"].encode()).decode()
        result = self.store.activate(replacement, str(uuid4()), "replacement-credential" * 3)
        self.assertEqual(before, result["expires_at"])
        self.assertNotEqual(code, replacement)

    def test_email_failure_stays_queued_and_retry_sends_same_activation(self):
        ident, code = self.grant()
        config = {**self.settings, "EYZEE_SMTP_HOST": "smtp.example.test", "EYZEE_EMAIL_FROM": "support@example.test"}
        from unittest.mock import MagicMock
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.send_message.side_effect = OSError("temporary SMTP outage")
        with patch("subscription_service.worker.smtplib.SMTP", return_value=smtp):
            with self.assertRaises(OSError):
                deliver(self.store, config)
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0])
        smtp.send_message.side_effect = None
        with patch("subscription_service.worker.smtplib.SMTP", return_value=smtp):
            self.assertEqual(1, deliver(self.store, config))
        smtp.starttls.assert_called()
        self.assertIn(code, smtp.send_message.call_args.args[0].get_content())
        self.assertEqual(0, deliver(self.store, config))

    def test_renewal_reminders_are_queued_once_and_disabled_without_url(self):
        ident, code = self.grant()
        self.client.activate(code)
        with self.store.db() as db:
            expiry = (datetime.now(timezone.utc) + timedelta(days=6, hours=12)).isoformat(timespec="seconds")
            db.execute("UPDATE entitlements SET expires_at=? WHERE id=?", (expiry, ident))
        queue_reminders(self.store, self.settings)
        with self.store.db() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM outbox WHERE kind LIKE 'reminder:%'").fetchone()[0])
        config = {**self.settings, "EYZEE_RENEWAL_URL_CORE": "https://store.example.test/core-renewal"}
        queue_reminders(self.store, config)
        queue_reminders(self.store, config)
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM outbox WHERE kind='reminder:7'").fetchone()[0])

    def test_reconciliation_catches_missed_payment_without_recrediting(self):
        order = {"id": "gid://shopify/Order/100", "email": "ian@example.test", "test": False,
            "cancelledAt": None, "displayFinancialStatus": "PAID", "updatedAt": now(),
            "customer": {"id": "gid://shopify/Customer/123"}, "lineItems": {"pageInfo": {"hasNextPage": False},
                "nodes": [{"id": "gid://shopify/LineItem/1100", "quantity": 1,
                    "variant": {"id": "gid://shopify/ProductVariant/11"}, "customAttributes": []}]}}
        page = {"data": {"orders": {"nodes": [order], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        config = {**self.settings, "EYZEE_SHOPIFY_ACCESS_TOKEN": "test-read-orders-token"}
        with patch("subscription_service.worker.urlopen", return_value=io.BytesIO(json.dumps(page).encode())):
            self.assertTrue(reconcile(self.store, config))
        self.process()
        self.webhook(self.order())
        self.process()
        with self.store.db() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM entitlements").fetchone()[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM payments").fetchone()[0])

    def test_full_fresh_install_from_service_package_preserves_onboarding(self):
        import installer as module
        from test_installer import FakeAPI, CARD_BYTES
        ident, code = self.grant()
        self.client.activate(code)
        self.publish(payload=ROOT / "eyzee_setup/payload")
        config = self.root / "full-config"
        config.mkdir()
        (config / "configuration.yaml").write_text("default_config:\n")
        api = FakeAPI(config)
        installer = Installer(config, self.root / "full-data", api=api, sleeper=lambda n: None, subscription=self.client)
        with patch.object(module, "urlopen", return_value=io.BytesIO(CARD_BYTES)), patch.object(module, "CARD_HASH", sha(CARD_BYTES)), patch.object(module, "mqtt_snapshot", return_value={}):
            installer.prepare()
        self.assertTrue((config / "custom_components/eyzee_dashboard/__init__.py").is_file())
        self.assertTrue((config / "eyzee/state/rooms.yaml").is_file())
        self.assertEqual("choose_gateway", installer.status()["phase"])
        self.assertEqual("1.0.0", installer.state["installed_release"])

    def test_activation_bruteforce_is_rate_limited(self):
        for index in range(10):
            self.http.post("/v1/activate", json={"code": "invalid-code", "installation_id": str(uuid4()), "credential": "x" * 50})
        self.assertEqual(429, self.http.post("/v1/activate", json={}).status_code)

    def test_converter_update_restarts_zigbee_and_checks_loaded_names(self):
        installer, path, state = self.make_installer()
        converter = self.root / "payload/device-support/zigbee2mqtt/external_converters/new-device.js"
        converter.parent.mkdir(parents=True)
        converter.write_text("// approved new device converter\n")
        self.publish("1.1.0")
        import installer as module
        snapshot = {'zigbee2mqtt/bridge/state': {'state': 'online'},
                    'zigbee2mqtt/bridge/converters': [{'name': 'new-device.js'}]}
        with patch.object(module, 'mqtt_snapshot', return_value=snapshot):
            installer.apply_update()
        self.assertTrue((installer.config/'zigbee2mqtt/external_converters/new-device.js').is_file())
        self.assertTrue(any('/restart' in c.args[0] and 'zigbee2mqtt' in c.args[0] for c in installer.api.call.call_args_list))
        self.assertIn('new-device.js', installer.state['expected_converters'])

    def test_converter_load_failure_restores_original_application_files(self):
        installer, path, state = self.make_installer()
        converter = self.root / "payload/device-support/zigbee2mqtt/external_converters/new-device.js"
        converter.parent.mkdir(parents=True)
        converter.write_text("// converter that does not load\n")
        self.publish("1.1.0")
        with patch.object(installer, 'wait', side_effect=SubscriptionError('converter not loaded')):
            with self.assertRaisesRegex(SubscriptionError, 'restored'):
                installer.apply_update()
        self.assertEqual('# original\n', path.read_text())
        self.assertFalse((installer.config/'zigbee2mqtt/external_converters/new-device.js').exists())
        self.assertFalse(any(c.args[0]=='/core/restart' for c in installer.api.call.call_args_list))

    def test_setup_status_never_contains_installation_credentials(self):
        ident, code = self.grant()
        self.client.activate(code)
        installer = Installer(self.root/'config', self.root/'data', subscription=self.client)
        status = json.dumps(installer.status())
        self.assertNotIn(code, status)
        self.assertNotIn(self.client.state['credential'], status)


if __name__ == "__main__":
    unittest.main()
