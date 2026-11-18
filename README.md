# EyZEE Setup — 0.1.0-beta.15

This release candidate adds the two customer editions (EyZEE Core and EyZEE
Home) to the single beta14 activation, subscription and signed-update stream.
Read [`subscription_service/DEPLOYMENT.md`](subscription_service/DEPLOYMENT.md)
first. It includes deployment instructions, current test coverage and launch
blockers. The proposed prices are Core A$27/year and Home A$49.95/year, with GST
treatment still to confirm. The activation service and signed beta15 Core
release are deployed; the live Shopify purchase-to-code flow remains a launch
acceptance step.

**Do not promote this candidate to customers yet.** The Setup image no longer
bundles EyZEE application files. Its official HTTPS service origin, pinned
release public key and approved release are configured for the beta test.
The integration source remains public. Subscription checks apply to official
downloads and support; existing homes never require subscription permission to run.

The sections below retain the original beta.13 onboarding background. For the
new activation, hosted service and update flow, use the deployment document.

A candidate Home Assistant OS app repository for the EyZEE Home onboarding flow. This is a lab release: automated tests and incremental HAOS/MG24 tests have passed. A fresh installation of this consolidated version and the remaining recovery checks are required before customer distribution.

## Customer flow after repository publication

1. Follow **Install EyZEE Core** to add this app repository.
2. Install and start **EyZEE Setup**.
3. Open its screen, activate updates and support, then press **Prepare My Home**.
4. Choose an available Zigbee gateway by MAC address and IP when prompted.
5. Open **EyZEE Core** or **EyZEE Home**, according to the activated entitlement,
   when all connection checks pass.

The customer does not edit YAML or call Home Assistant actions. Setup invokes the existing EyZEE MG24 services; the bundled `zigbee_coordinator.py` is unchanged from the supplied integration.

## Reconnection after restart or address change

Beta.11 retries temporary administrator-verification failures and shows a friendly
reconnection screen while Home Assistant returns. Setup actions remain blocked
until the administrator session is verified again. The main **Open EyZEE Core**
button opens **eyzee-core.local** once the hostname change is confirmed. If you
keep the current hostname, the button opens the dashboard on that address.
If the original hostname no longer resolves, use the new address or the system IP,
sign in, and reopen EyZEE Setup from Home Assistant.

The checkbox remains selected by default for a fresh setup and preserves a saved
opt-out. Updating the Setup app does not reinstall or reset an existing EyZEE home.

## Included setup

- Official Terminal & SSH, Mosquitto broker, standard Zigbee2MQTT, and Studio Code Server.
- EyZEE custom component, dashboard files, clean initial state, themes, ZHA quirks, and 11 Zigbee2MQTT external converters.
- Per-home MQTT configuration using Supervisor credentials.
- Zigbee2MQTT's own generated defaults, with onboarding disabled and external JavaScript enabled for the supplied converters.
- Full pre-install backup, configuration validation before Core restart, and verified gateway setup through the existing backend.
- Admin-only Home Assistant ingress, request protection, and a report that excludes credentials.

Terminal & SSH and Studio Code Server are included because the current Sue installation specification explicitly requests all four apps. The later dongle handover proposes making these optional; that policy can be changed before customer release. No external SSH port is opened for a newly installed Terminal & SSH app.

## Fresh-install test from GitHub

1. Add `https://github.com/eyzee-au/eyzee-home-apps` through the Install EyZEE Home link.
2. Search the Home Assistant app store for **EyZEE Setup**.
3. Confirm **0.1.0-beta.15** before installing.
4. Open its screen, press **Prepare My Home**, and select the intended Zigbee gateway when prompted.
5. Follow `ACCEPTANCE.md`.

## Local lab installation

Use a fresh HAOS installation on the `.201` test machine with a default MG24 powered on and connected to Ethernet. Back up `.201` before rebuilding it. Keep `.200` intact.

1. Extract this archive.
2. Copy the complete `eyzee_setup` folder to `/addons/eyzee_setup` on the HAOS host using an existing support file-access method. It must contain `config.yaml`, `Dockerfile`, `server.py`, `installer.py`, and `payload/`.
3. Reload the app store. Find **EyZEE Setup** under **Local apps** (called add-ons on older Home Assistant versions).
4. Install, start, then open its web UI.
5. Press **Prepare My Home**. Keep the screen open through the Home Assistant Core restart.
6. Choose the gateway when prompted, then follow `ACCEPTANCE.md`.

A stopped/restarted Setup app preserves progress. Reopen it and press **Prepare My Home** to continue safely; it does not reuse an old ready result. A Core restart during preparation is handled automatically. A whole-host restart interrupts the worker and requires that button press.

This first candidate targets fresh installations. It refuses unknown or modified existing EyZEE integration files rather than migrate them. A current populated `.201` is therefore not the fresh-install acceptance environment.

## Publish the repository and make the real installation link

Publish the contents of this directory at the root of a Git repository accessible to HAOS. `repository.yaml` and the `eyzee_setup/` directory must be at repository root. The app is built locally on HAOS; no prebuilt container registry is required for this candidate.

After the real repository URL is known, generate the link:

```sh
python3 make_install_link.py https://github.com/YOUR-ACCOUNT/YOUR-REPOSITORY
```

Use the resulting URL behind **Install EyZEE Home**. Replace the app/repository website metadata if `https://eyzee.au` is not the desired product website. A website URL is not an app repository URL.

The source archive is not itself a Home Assistant repository URL. HAOS installs
from the published repository URL above.

## Release delivery

Beta.13 bundled the versioned EyZEE payload. This beta.15 release candidate
downloads it from the configured official service after activation, verifies an
Ed25519-signed release manifest and the package/file SHA-256 hashes, then uses
the existing preparation engine. The activated entitlement plan renders the
Core or Home edition of the downloaded themes, dashboards, static UI files and
managed integration files. The pinned card-mod resource is still downloaded over
HTTPS from upstream and verified independently. The source payload remains in Git
for development and release packaging, but is excluded from the Setup image.

The supplied converter set may still contain experimental versions. Tidy and approve it before the final customer release, then regenerate `payload-hashes.json`. External JavaScript is enabled only to support this supplied code.

## Customer editions (beta.15)

There is one codebase and one version stream. The activated entitlement plan
selects the customer-visible edition:

- `core` displays **EyZEE® Core** (DIY product on customer-supplied hardware).
- `home` displays **EyZEE® Home** (complete supplied hardware and software).

`eyzee_setup/edition.py` renders product wording only. Lowercase internal
identifiers and routes such as `/eyzee-home/`, `eyzee_home`, dashboard IDs and
file paths are never renamed. The installer renders downloaded themes,
dashboards and static UI files for the activated plan; the signed updater renders
the same way before comparing and writing files. Home rendering leaves content
unchanged.

Managed updates include `eyzee/dashboards.yaml` and static files under
`eyzee/ui/`. These generated or mutable files are explicitly excluded from
managed updates: `eyzee/ui/eyzee-room.yaml`, `eyzee/ui/eyzee-master.yaml`,
`eyzee/ui/setup/add_device.yaml` and `eyzee/ui/setup/device_setup.yaml`.
Installation state, credentials, subscription state, rooms and other
customer-generated data remain excluded.

On a fresh installation only, `eyzee/state/rooms.yaml` is edition-rendered so a
Core home starts with `project: My EyZEE Core` and a Home home keeps
`project: My EyZEE Home`. If `rooms.yaml` already exists, it is preserved
byte-for-byte and remains outside managed updates.

Advanced Controls includes an **Updates & Support** button (`mdi:update`) that
opens the production Setup ingress at
`/config/app/eba672c4_eyzee_setup/ingress`. The local test add-on may use
`local_eyzee_setup`; the committed production dashboard uses the GitHub slug.

## Preservation and recovery

Setup creates a full HAOS backup before mutation and keeps copies of changed files. It preserves unrelated configuration values, existing network parameters and customer state. YAML is parsed and rewritten, so comments and formatting in `configuration.yaml` may change. Unusual layouts and duplicate keys stop setup for review.

If Core configuration validation fails, the original `configuration.yaml` is restored and Core is not restarted. Other already-installed apps or files remain for retry; this is not a whole-installation transaction. The MG24 service owns coordinator rollback. Use the full backup to recover the complete prior system.

Do not copy customer Zigbee network keys, coordinator backups, device registries, rules or room state between homes.

## Development validation

```sh
cd eyzee_setup
python3 -m pip install PyYAML==6.0.2 websocket-client==1.8.0
python3 -m unittest discover -v
```

Tests use simulated Supervisor/Home Assistant services. They cover commissioning dispatch by stable MAC address, repeat preparation, preservation and refusals, failed configuration validation, altered payloads, missing converters, mismatched coordinator reports, ingress request protection and admin identity checks. They do not prove real Supervisor permissions, image builds, radio commissioning, pairing or recovery on HAOS. Run the complete acceptance checklist before calling this customer-ready.

## EyZEE Core address (beta.6)

This download installs EyZEE Core on the owner's hardware. EyZEE Home and eyzee-home.local are reserved for the complete supplied system.

Before Prepare My Home, optionally select **Use eyzee-core.local for this new system**. Leave it unticked to retain the current hostname. The choice is saved during preparation and applied only after readiness checks pass. Completion shows **Open EyZEE Core**. A confirmed hostname change updates that link while preserving the browser protocol and port. Current-address recovery remains under Setup progress & help.

This does not change IP configuration, ports or TLS certificates. Local name resolution still requires a real network test. Existing-home upgrades remain unverified.

Acceptance: verify preparation with the option unticked preserves the hostname; repeat on a fresh test system with it selected, confirm eyzee-core.local resolves, and check current-IP recovery, reboot persistence, retries and gateway selection.

## Room-addition fix (beta.5)

Includes the supplied integration fix for adding standard rooms without replacing
existing indoor/custom rooms. Repeated room types receive unused numbered IDs.
Outdoor areas continue to follow their selected toggles. On fresh HAOS, verify
that adding rooms retains prior room names and device assignments.

## Existing-installation safeguard (beta.7)

Reopening Setup after a completed installation shows **EyZEE Core is already installed** and **Open EyZEE Core**. Repeated preparation requests return to that screen before changing Home Assistant, the hostname, supporting apps or installed files. An integration with no installer ownership history is also protected; its completeness is not assumed and it needs manual review if it does not open.

An incomplete installation tracked by Setup can still resume. An available **Check Connection Again** action checks services; detecting installed files does not claim those services are healthy. Existing-home upgrades still require a tested migration path.

Acceptance: complete a fresh install, restart Setup, and verify the open-only screen. Confirm a repeated preparation request makes no installation changes. Verify an interrupted incomplete setup can resume and a failed connection check does not re-enable preparation on a completed home.

## Theme files

For directory-based themes, Setup stores the EyZEE definition in
/config/eyzee/themes/eyzee_home.yaml and writes an include pointer in the active
theme directory. A fresh configuration uses /config/themes. Additional themes can
be added to that directory. Existing configurations that include the EyZEE folder
directly use the definition there.
