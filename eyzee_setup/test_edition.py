"""Edition, managed-update scope and LiteSpeed client tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import edition
import installer
import subscription
import update_engine

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"
MENU = "config/eyzee/ui/living/eyzee-main-menu.yaml"
DASHBOARDS = "config/eyzee/dashboards.yaml"
THEME = "config/eyzee/themes/eyzee_home.yaml"
PRODUCTION_INGRESS = "/config/app/eba672c4_eyzee_setup/ingress"


class FakeSubscription:
    def __init__(self, plan):
        self.state = {"entitlement": {"plan": plan, "active": True}}

    def summary(self):
        return {"configured": True, "activated": True, **self.state["entitlement"]}


def payload_text(relative):
    return (PAYLOAD / relative).read_text(encoding="utf-8")


def release_manifest():
    for candidate in (HERE.parent / "release/release.json", HERE.parent.parent / "release/release.json"):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


class EditionTests(unittest.TestCase):
    def test_setup_page_links_to_live_software_licence_safely(self):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        licence = (
            '<a href="https://eyzee.au/eyzee-core/licence/" '
            'target="_blank" rel="noopener noreferrer"'
        )
        self.assertIn(licence, page)
        self.assertIn(">Software licence</a>", page)

    def test_beta14_inline_sidebar_registration_migrates_to_core_only(self):
        source = (
            "# homeowner comment\n"
            "lovelace:\n"
            "  dashboards:\n"
            "    eyzee-main-menu:\n"
            "      mode: yaml\n"
            "      title: EyZEE® Home\n"
            "      icon: mdi:home-heart\n"
            "      show_in_sidebar: true\n"
            "      require_admin: false\n"
            "      filename: eyzee/ui/living/eyzee-main-menu.yaml\n"
            "    customer-dashboard:\n"
            "      mode: yaml\n"
            "      title: Family\n"
            "      filename: family.yaml\n"
        )
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / "config"
            config.mkdir()
            target = config / "configuration.yaml"
            target.write_text(source, encoding="utf-8")
            install = installer.Installer(config=config, data=root / "data", api=object())
            migration = update_engine._configuration_edition_migration(install, edition.CORE)
            self.assertIsNotNone(migration)
            rendered = migration["rendered"].decode("utf-8")
            self.assertIn("# homeowner comment", rendered)
            self.assertIn("title: EyZEE® Core", rendered)
            self.assertIn("title: Family", rendered)
            self.assertEqual(
                update_engine.hashlib.sha256(migration["current"]).hexdigest(),
                migration["verified_hash"],
            )
            self.assertIsNone(update_engine._configuration_edition_migration(install, edition.HOME))

    def test_custom_inline_sidebar_title_is_preserved(self):
        source = (
            "lovelace:\n  dashboards:\n    eyzee-main-menu:\n"
            "      mode: yaml\n      title: Smith Family\n"
            "      filename: eyzee/ui/living/eyzee-main-menu.yaml\n"
        )
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / "config"
            config.mkdir()
            (config / "configuration.yaml").write_text(source, encoding="utf-8")
            install = installer.Installer(config=config, data=root / "data", api=object())
            self.assertIsNone(
                update_engine._configuration_edition_migration(install, edition.CORE)
            )

    def test_update_rollback_restores_inline_sidebar_registration(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / "config"
            data = root / "data"
            backup = data / "update-backups/beta15"
            config.mkdir()
            backup.mkdir(parents=True)
            original = b"lovelace:\n  dashboards:\n    eyzee-main-menu:\n      title: EyZEE\xc2\xae Home\n"
            migrated = original.replace(b"Home", b"Core")
            (config / "configuration.yaml").write_bytes(migrated)
            (backup / "configuration.yaml").write_bytes(original)
            install = installer.Installer(config=config, data=data, api=object())
            update_engine.rollback(
                install,
                {
                    "directory": str(backup),
                    "originals": {},
                    "tracked_files": {},
                    "installed_release": "0.1.0-beta.14",
                    "configuration_changed": True,
                },
            )
            self.assertEqual(original, (config / "configuration.yaml").read_bytes())
            self.assertEqual("0.1.0-beta.14", install.state["installed_release"])

    def test_core_migration_accepts_exact_signed_home_source_only(self):
        signed_source = b"title: EyZEE Home\n"
        rendered = b"title: EyZEE Core\n"
        self.assertTrue(
            update_engine._safe_existing_file(
                "eyzee/dashboards.yaml", signed_source, rendered,
                signed_source, expected_hash=None
            )
        )
        self.assertTrue(
            update_engine._safe_existing_file(
                "eyzee/dashboards.yaml", rendered, rendered,
                signed_source, expected_hash=None
            )
        )
        self.assertFalse(
            update_engine._safe_existing_file(
                "eyzee/dashboards.yaml", b"customer edit\n", rendered,
                signed_source, expected_hash=None
            )
        )

    def test_beta14_main_menu_is_the_only_trusted_predecessor_exception(self):
        beta14_menu = b"official beta14 menu"
        beta14_hash = update_engine.hashlib.sha256(beta14_menu).hexdigest()
        relative = "eyzee/ui/living/eyzee-main-menu.yaml"
        with patch.dict(
            update_engine.TRUSTED_PREDECESSOR_HASHES,
            {relative: {beta14_hash}},
            clear=True,
        ):
            self.assertTrue(
                update_engine._safe_existing_file(
                    relative, beta14_menu, b"rendered beta15", b"signed beta15", None
                )
            )
            self.assertFalse(
                update_engine._safe_existing_file(
                    relative, b"customer edit", b"rendered beta15", b"signed beta15", None
                )
            )
            self.assertFalse(
                update_engine._safe_existing_file(
                    "eyzee/dashboards.yaml", beta14_menu,
                    b"rendered beta15", b"signed beta15", None
                )
            )

    def test_changed_managed_file_is_named_in_support_diagnostic(self):
        relative = "eyzee/dashboards.yaml"
        error = update_engine._local_change_error(relative)
        self.assertIn(relative, str(error))
        self.assertEqual(
            {"reason": "local_file_changed", "managed_path": relative},
            error.diagnostic,
        )

    def test_core_entitlement_renders_customer_facing_core_branding(self):
        plan = edition.plan_for(FakeSubscription("core"))
        self.assertEqual(edition.CORE, plan)
        self.assertEqual("EyZEE Core", edition.product_name(plan))
        self.assertEqual("EyZEE® Core", edition.product_name(plan, registered=True))

        menu = edition.render(payload_text(MENU), plan)
        self.assertIn("title: EyZEE® Core", menu)
        self.assertIn("heading: EyZEE Core", menu)
        self.assertNotIn("EyZEE® Home", menu)
        self.assertNotIn("EyZEE Home", menu)

        dashboards = edition.render(payload_text(DASHBOARDS), plan)
        self.assertIn("title: EyZEE® Core", dashboards)

        theme = edition.render(payload_text(THEME), plan)
        self.assertTrue(theme.startswith("EyZEE Core:"))

    def test_home_entitlement_retains_unchanged_home_branding(self):
        plan = edition.plan_for(FakeSubscription("home"))
        self.assertEqual(edition.HOME, plan)
        self.assertEqual("EyZEE® Home", edition.product_name(plan, registered=True))
        menu = payload_text(MENU)
        self.assertEqual(menu, edition.render(menu, plan))
        self.assertIn("title: EyZEE® Home", menu)
        self.assertIn("EyZEE Home", menu)
        self.assertNotIn("EyZEE® Core", menu)

    def test_unknown_or_missing_plan_defaults_to_core_for_a_subscription(self):
        self.assertEqual(edition.CORE, edition.plan_for(FakeSubscription("unexpected")))
        self.assertEqual(edition.CORE, edition.plan_for({"activated": True}))
        self.assertEqual(edition.HOME, edition.plan_for(None))

    def test_internal_lowercase_eyzee_home_routes_remain_unchanged(self):
        content = (
            "url_path: https://eyzee.au/eyzee-home/support/manage-my-rooms/\n"
            "path: eyzee_home\n"
            "filename: eyzee/ui/eyzee-room.yaml\n"
            "navigation_path: /eyzee-home/rooms\n"
        )
        self.assertEqual(content, edition.render(content, edition.CORE))
        menu = edition.render(payload_text(MENU), edition.CORE)
        self.assertIn("https://eyzee.au/eyzee-home/support/", menu)
        self.assertIn("navigation_path: /eyzee-main-menu/home", menu)
        self.assertNotIn("https://eyzee.au/eyzee-core/", menu)

    def test_advanced_controls_uses_production_setup_ingress_route(self):
        menu = edition.render(payload_text(MENU), edition.CORE)
        self.assertIn("name: Updates & Support", menu)
        self.assertIn("icon: mdi:update", menu)
        self.assertIn("url_path: " + PRODUCTION_INGRESS, menu)
        self.assertNotIn("local_eyzee_setup", menu)
        self.assertIn("name: Advanced Controls", menu)

    def test_static_ui_is_in_managed_update_scope_and_generated_pages_are_excluded(self):
        included = [
            "eyzee/dashboards.yaml",
            "eyzee/ui/living/eyzee-main-menu.yaml",
            "eyzee/ui/eyzee-onboarding.yaml",
            "eyzee/ui/automate/automate.yaml",
            "eyzee/ui/setup/eyzee-setup.yaml",
            "eyzee/ui/setup/existing_device.yaml",
            "eyzee/themes/eyzee_home.yaml",
        ]
        for relative in included:
            self.assertTrue(subscription.managed_path(relative), relative)
        for relative in ("eyzee/ui/eyzee-room.yaml", "eyzee/ui/eyzee-master.yaml",
                         "eyzee/ui/setup/add_device.yaml", "eyzee/ui/setup/device_setup.yaml",
                         "eyzee/state/rooms.yaml", "eyzee/generated_smart_behaviours.yaml",
                         "eyzee/templates/fans.yaml"):
            self.assertFalse(subscription.managed_path(relative), relative)

    def test_release_metadata_includes_static_ui_and_excludes_generated_pages(self):
        manifest = release_manifest()
        if manifest is None:
            self.skipTest("release/release.json is not present in this checkout")
        self.assertEqual("0.1.0-beta.15", manifest["version"])
        self.assertEqual("0.1.0-beta.15", manifest["requires_setup"])
        updates = manifest["update_files"]
        for relative in ("eyzee/dashboards.yaml", "eyzee/ui/living/eyzee-main-menu.yaml",
                         "eyzee/ui/eyzee-onboarding.yaml", "eyzee/ui/setup/eyzee-setup.yaml"):
            self.assertIn(relative, updates)
        for relative in ("eyzee/ui/eyzee-room.yaml", "eyzee/ui/eyzee-master.yaml",
                         "eyzee/ui/setup/add_device.yaml", "eyzee/ui/setup/device_setup.yaml",
                         "eyzee/state/rooms.yaml", "eyzee/generated_smart_behaviours.yaml",
                         "eyzee/templates/fans.yaml"):
            self.assertNotIn(relative, updates)

    def test_litespeed_compatible_user_agent_is_sent_explicitly(self):
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b"{}"

        class Opener:
            def open(self, request, timeout):
                seen["request"] = request
                return Response()

        with tempfile.TemporaryDirectory() as data:
            client = subscription.SubscriptionClient(
                data,
                "https://subscriptions.eyzee.au",
                subscription.OFFICIAL_RELEASE_PUBLIC_KEY,
            )
            with patch.object(subscription, "build_opener", return_value=Opener()):
                self.assertEqual({}, client.http("/v1/entitlement"))
        self.assertEqual("EyZEE-Setup/0.1", seen["request"].get_header("User-agent"))

    def test_core_installer_plan_uses_core_theme_and_dashboard_titles(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / "config"
            config.mkdir()
            (config / "configuration.yaml").write_text(
                "default_config:\nfrontend:\n  themes:\n    Other:\n      primary-color: blue\n",
                encoding="utf-8",
            )
            install = installer.Installer(
                config=config, data=root / "data", payload=PAYLOAD,
                api=object(), sleeper=lambda _: None,
                subscription=FakeSubscription("core"),
            )
            _, planned = install.config_plan()
            data = installer.load(planned)
            self.assertEqual("EyZEE® Core", data["lovelace"]["dashboards"]["eyzee-main-menu"]["title"])
            self.assertIn("EyZEE Core", data["frontend"]["themes"])
            self.assertNotIn("EyZEE Home", data["frontend"]["themes"])
            self.assertEqual("#D6AD60", data["frontend"]["themes"]["EyZEE Core"]["primary-color"])


class FreshRoomsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config"
        self.config.mkdir()
        self.install = installer.Installer(
            config=self.config,
            data=root / "data",
            payload=PAYLOAD,
            api=object(),
            sleeper=lambda _: None,
        )
        self.rooms = self.config / "eyzee/state/rooms.yaml"
        self.source = (PAYLOAD / "config/eyzee/state/rooms.yaml").read_bytes()

    def test_fresh_core_installation_renders_rooms_project_name(self):
        self.install.edition = edition.CORE
        self.install.write_payload("eyzee/state/rooms.yaml", self.source)
        rooms = self.rooms.read_text(encoding="utf-8")
        self.assertIn("project: My EyZEE Core", rooms)
        self.assertNotIn("My EyZEE Home", rooms)
        self.assertIn("rooms: {}", rooms)
        self.assertIn("devices: {}", rooms)

    def test_fresh_home_installation_leaves_rooms_file_unchanged(self):
        self.install.edition = edition.HOME
        self.install.write_payload("eyzee/state/rooms.yaml", self.source)
        self.assertEqual(self.source, self.rooms.read_bytes())

    def test_existing_customer_edited_rooms_file_is_preserved_byte_for_byte(self):
        existing = (
            b"version: 1\n"
            b"project: The Smiths\n"
            b"devices:\n  kitchen_light:\n    name: Kitchen Light\n"
            b"rooms:\n  kitchen:\n    label: Kitchen\n"
        )
        self.rooms.parent.mkdir(parents=True)
        self.rooms.write_bytes(existing)
        self.install.edition = edition.CORE
        self.install.write_payload("eyzee/state/rooms.yaml", self.source)
        self.assertEqual(existing, self.rooms.read_bytes())

    def test_rooms_file_remains_outside_managed_updates(self):
        self.assertFalse(subscription.managed_path("eyzee/state/rooms.yaml"))
        manifest = release_manifest()
        if manifest is not None:
            self.assertNotIn("eyzee/state/rooms.yaml", manifest["update_files"])


if __name__ == "__main__":
    unittest.main()
