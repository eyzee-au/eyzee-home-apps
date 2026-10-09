# EyZEE Setup — 0.1.0-beta.4

A candidate Home Assistant OS app repository for the EyZEE Home onboarding flow. This is a lab release: automated tests and incremental HAOS/MG24 tests have passed. A fresh installation of this consolidated version and the remaining recovery checks are required before customer distribution.

## Customer flow after repository publication

1. Follow **Install EyZEE Home** to add this app repository.
2. Install and start **EyZEE Setup**.
3. Open its screen and press **Prepare My Home**.
4. Choose an available Zigbee gateway by MAC address and IP when prompted.
5. Open **EyZEE Home** when all connection checks pass.

The customer does not edit YAML or call Home Assistant actions. Setup invokes the existing EyZEE MG24 services; the bundled `zigbee_coordinator.py` is unchanged from the supplied integration.

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
3. Confirm the offered version is **0.1.0-beta.4**, then install and start it.
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

The source archive is not itself a Home Assistant repository URL. This delivery does not create or host a Git repository, or create a public install link.

## Release delivery

For this candidate, the versioned EyZEE bundle is included in the Setup app download and verified against bundled SHA-256 hashes before installation. No release-server URL was supplied, so arbitrary server downloads are not implemented. The pinned card-mod resource is downloaded over HTTPS from upstream and verified independently. A later release-server manifest can replace the bundled-payload source without changing the homeowner flow.

The supplied converter set may still contain experimental versions. Tidy and approve it before the final customer release, then regenerate `payload-hashes.json`. External JavaScript is enabled only to support this supplied code.

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
