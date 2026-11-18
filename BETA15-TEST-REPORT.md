# EyZEE beta.15 release-candidate test report

Generated: 2026-11-18 (Australia/Sydney)

## Scope

- Version: `0.1.0-beta.15`
- Setup add-on: `EyZEE-Setup-beta15-release-candidate.zip`
- Signed-release input: `EyZEE-Core-0.1.0-beta.15.zip`
- Baseline: supplied beta14 source plus the supplied `EyZEE-beta14-LiteSpeed-fix.zip`
  `subscription.py` change (explicit `User-Agent: EyZEE-Setup/0.1`).
- The signed beta15 Core release is published to the subscription service. This
  report covers the matching Setup source prepared for GitHub beta testing.

## Results

| Suite | Result |
| --- | --- |
| Python unit/integration tests (`test_installer`, `test_server`, `test_edition`) | **70 tests, 70 passed** |
| JavaScript/DOM reconnect tests (`test_reconnect_ui.cjs`) | **9 scenarios, 9 passed** |
| Subscription service Python tests (`tests/test_subscriptions.py`) | **37 tests, 37 passed** |
| Subscription DOM tests (`tests/test_subscription_dom.cjs`) | **4 scenarios, 4 passed** |
| Core archive audit (`tools/audit_core.py`) | **42/42 checks passed** |
| Payload SHA-256 verification (Setup payload and release payload) | **90/90 files matched** |
| Signed-release update mapping | **72 managed files, 0 missing, 0 bad mappings** |

### Required beta.15 tests

- `test_setup_page_links_to_live_software_licence_safely` — the Setup updates
  panel links to the live EyZEE Core software licence in a separate, isolated
  browser tab.
- `test_core_migration_accepts_exact_signed_home_source_only` — an exact verified
  Home-source file is a safe Core-rendering baseline, while an untracked local
  edit remains blocked.
- `test_changed_managed_file_is_named_in_support_diagnostic` — a changed-file
  safety stop identifies the managed relative path in both its message and
  structured support diagnostic.
- `test_beta14_main_menu_is_the_only_trusted_predecessor_exception` — the exact
  official beta14 main-menu hash is accepted for its single managed path, while
  a customer edit or the same bytes at another path remain blocked.
- `test_preflight_verified_hash_allows_exact_file_but_blocks_a_race` — the file
  writer accepts the precise hash approved by update preflight, but refuses a
  file changed between preflight and writing.
- `test_beta14_inline_sidebar_registration_migrates_to_core_only` — the exact
  beta14 `EyZEE® Home` main-menu registration becomes `EyZEE® Core` while
  comments, other dashboards and all other settings are preserved.
- `test_custom_inline_sidebar_title_is_preserved` — a homeowner-customised
  sidebar title is never replaced by the edition migration.
- `test_update_rollback_restores_inline_sidebar_registration` — a failed update
  restores the original `configuration.yaml` together with all managed files.
- `test_core_entitlement_renders_customer_facing_core_branding` — Core plan renders
  EyZEE® Core page title, visible heading and theme name.
- `test_home_entitlement_retains_unchanged_home_branding` — Home content is returned
  unchanged.
- `test_internal_lowercase_eyzee_home_routes_remain_unchanged` — `/eyzee-home/`,
  `eyzee_home` and internal identifiers are preserved.
- `test_advanced_controls_uses_production_setup_ingress_route` — the **Updates &
  Support** button (`mdi:update`) uses
  `/config/app/eba672c4_eyzee_setup/ingress`; no `local_eyzee_setup` slug.
- `test_static_ui_is_in_managed_update_scope_and_generated_pages_are_excluded` —
  `eyzee/dashboards.yaml` and static `eyzee/ui/` files are managed; the four
  generated/mutable pages and homeowner state are not.
- `test_release_metadata_includes_static_ui_and_excludes_generated_pages` — the
  built `release.json` proves the same scope.
- `test_litespeed_compatible_user_agent_is_sent_explicitly` — a real
  `SubscriptionClient.http()` request carries `User-Agent: EyZEE-Setup/0.1`.
- `test_core_installer_plan_uses_core_theme_and_dashboard_titles` — the installer's
  configuration plan uses the Core theme key and dashboard title.
- `test_fresh_core_installation_renders_rooms_project_name` — a fresh Core install
  writes `project: My EyZEE Core` to `eyzee/state/rooms.yaml`.
- `test_fresh_home_installation_leaves_rooms_file_unchanged` — a fresh Home install
  keeps the supplied `project: My EyZEE Home` bytes.
- `test_existing_customer_edited_rooms_file_is_preserved_byte_for_byte` — an existing
  rooms file is not overwritten or re-rendered.
- `test_rooms_file_remains_outside_managed_updates` — `rooms.yaml` stays excluded
  from the signed update manifest.
- All 49 existing beta14 activation, installer, subscription, update and
  reconnection tests continue to pass.

### Existing behaviour preserved

- Activation service remains `https://subscriptions.eyzee.au`.
- Release public key remains
  `vAoZ9VFR/qYR+LFXJEXJknAnAVBxU8BBuTwylZKeVkA=`.
- Ed25519 manifest signature verification, package SHA-256 and per-file
  `payload-hashes.json` verification are unchanged.
- An expired subscription does not stop an installed home; it only affects
  official updates and support.
- `/eyzee-home/` routes, `eyzee_home`, dashboard IDs and file paths are unchanged.
- Generated homeowner state and the four mutable/generated UI pages are excluded
  from managed updates. The four pages are rendered once when first created on a
  fresh install.
- On a fresh install only, `eyzee/state/rooms.yaml` is edition-rendered: Core gets
  `project: My EyZEE Core`, Home keeps `project: My EyZEE Home`. An existing
  customer-edited file is preserved byte-for-byte and stays outside managed
  updates.

## Core archive audit

The signed package is edition-neutral. The audit renders a Core copy using the
installer's rule and checks the result. See [`BETA15-AUDIT.md`](BETA15-AUDIT.md).

Confirmed:

- Core page title `EyZEE® Core`.
- Core visible heading `EyZEE Core`.
- Core theme name `EyZEE Core`.
- Lowercase `/eyzee-home/` and `eyzee_home` occurrences unchanged in count.
- **Updates & Support** production ingress route present.
- No unintended visible `EyZEE Home`/`EyZEE® Home` labels in rendered product
  files; the fresh Core rooms project is `My EyZEE Core`.
- No populated room/device records, subscription state, installation state,
  credentials or private signing keys in the archive.

## Environment and limitations

- Python 3.12.14; PyYAML 6.0.2, ruamel.yaml 0.18.6, cryptography 46.0.3,
  websocket-client 1.8.0.
- Node.js 24.21.0 with jsdom 31.0.1 for the existing reconnect UI test.
- Tests use simulated Supervisor/Home Assistant services. Real HAOS install,
  phone/Safari recovery, radio commissioning and the beta.14 end-to-end flow
  must still be re-run on the backed-up HAOS test machine before publication.
- The Windows test runner (`tools/run_tests.py`) runs Python in UTF-8 mode and
  retries a transient sandboxed temporary-file rename. These are test-harness
  accommodations for the Windows workspace; production code and its HAOS
  permissions are unchanged.
- The existing beta14 end-to-end HAOS result is not re-claimed here. This report
  covers the beta.15 code and package checks only.

## Publication state

- beta14 remains published and unmodified.
- The signed beta15 Core release is published to the subscription server; the
  matching Setup source is published to GitHub for fresh-install acceptance.
- No Core/Home repository split, branch split or separate version stream was
  created.
