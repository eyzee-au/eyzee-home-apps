# 0.1.0-beta.15 — editions beta release

- Link the Setup updates panel to the live EyZEE Core software licence, opening
  it in a separate browser tab without giving the destination access to Setup.
- Changed-file update failures now name the managed relative path in the screen
  message and downloaded Setup report while continuing to preserve all files.
- Core edition migration accepts an existing file only when it matches either
  its tracked hash or the exact verified signed Home source before rendering.
  Genuinely modified local files remain protected.
- Accept the exact official beta14 `eyzee-main-menu.yaml` hash for that path
  only, allowing beta14 to receive the beta15 Updates & Support tile while
  continuing to block any customer-edited value.
- Carry each preflight-approved current-file hash into the atomic writer. This
  removes a contradictory second rejection while retaining protection against
  a file changed between preflight and writing.
- Migrate the exact beta14 inline main-menu registration title from
  `EyZEE® Home` to `EyZEE® Core` for Core entitlements. Preserve custom titles,
  comments, other dashboards and unrelated configuration, with journalled
  rollback if Home Assistant validation fails.
- Add one codebase with two customer editions: `core` displays EyZEE® Core and
  `home` displays EyZEE® Home. Internal `/eyzee-home/` routes, `eyzee_home`
  identifiers, dashboard IDs and file paths are unchanged.
- Add `edition.py` with `plan_for`, `product_name` and `render`. The installer
  and signed updater render downloaded themes, dashboards, static UI and managed
  integration files for the activated entitlement plan.
- Extend managed update scope to `eyzee/dashboards.yaml` and static files under
  `eyzee/ui/`. Exclude generated/mutable room and setup pages, installation
  state, credentials, subscription state and other customer-generated data.
- On a fresh installation only, render `eyzee/state/rooms.yaml` for the edition
  (`project: My EyZEE Core` or `project: My EyZEE Home`). Preserve an existing
  customer-edited `rooms.yaml` byte-for-byte and keep it outside managed updates.
- Add an Advanced Controls **Updates & Support** button (`mdi:update`) opening
  the production Setup ingress `/config/app/eba672c4_eyzee_setup/ingress`.
- Preserve the beta14 activation service, pinned release public key, Ed25519
  signature checks, payload hashes and subscription-independent operation.
- Retain the explicit `User-Agent: EyZEE-Setup/0.1` header required by LiteSpeed.
- Update the signed release to version 0.1.0-beta.15 with required Setup version
  0.1.0-beta.15.

Beta.14 remains published and immutable. Beta.15 is released for fresh-install
acceptance before customer promotion.

# 0.1.0-beta.14 — unpublished subscriptions candidate

- Add the separate official activation, Shopify entitlement and release service.
- Add activation, update checks and a confirmed update/restart flow to Setup.
- Download signed official packages; exclude the payload from the Setup image.
- Preserve local operation independently of subscription state.
- Back up before updates, preserve home data and local edits, and restore files
  when validation fails or a file-writing update is interrupted.
- Reload changed Zigbee2MQTT converters and check they loaded before completing
  an update. Network configuration is not changed by the updater.
- Proposed annual prices: Core A$27; Home A$49.95, subject to GST confirmation.

See `subscription_service/DEPLOYMENT.md`. Hosting, live Shopify checkout/renewal,
email delivery and real HAOS upgrade acceptance remain required. Do not publish
the new Setup image until the download service and public key are configured.

# 0.1.0-beta.13

- Set the current Home Assistant form-background variables to keep EyZEE dropdowns readable when the phone switches to dark mode. This correction passed the live phone test.
- Keep the full EyZEE theme in eyzee/themes/eyzee_home.yaml and create an include pointer in an existing themes directory. Fresh configurations use the standard themes directory, ready for additional themes.

# 0.1.0-beta.12

- Open EyZEE Core on the confirmed hostname and show the button destination below it.

# 0.1.0-beta.11

- Treat temporary Home Assistant administrator-lookup failures as retryable, without caching an access denial.
- Replace the raw start-page authentication error with a branded reconnection screen that retries access automatically and explains how to reopen Home Assistant after a hostname change.
- Keep the main Open EyZEE Core button on the current signed-in address. Offer eyzee-core.local separately after its hostname change is confirmed, retaining the browser protocol and port.
- Pause setup actions while disconnected, recover controls on reconnect, prevent overlapping status requests, and refresh the process request token only from an authenticated status response.
- Preserve ingress source checks, administrator checks, CSRF checks, readiness validation, and the owner's hostname choice. No setup action is replayed automatically after a failed request.
- Retain the latest bundled room and notification fixes. Payload contents and checksums are unchanged from the verified baseline.

Validation: 46 Python checks and 9 JavaScript/DOM recovery scenarios passed. Live HAOS and iPhone/Safari installation acceptance remains required. Desktop Chromium launch was unavailable in the execution environment; no rendered mobile-browser verification is claimed.

# 0.1.0-beta.10

- Refresh payload checksums to match the current integration, theme and dashboard files.
- Bump the Setup app version so Home Assistant can build the corrected package.
- Retain file verification; payload contents are unchanged by this repair.

# 0.1.0-beta.9

- Replace the blinking status dot with a gold progress bar driven by actual setup stages.
- Show the current step, wait at gateway selection, and show completion only after readiness checks pass.
- Recover progress from saved status after page reload; retain the last stage on failure or interrupted setup.
- Hold the bar during connection loss and resume it on the next successful status response.
- Keep existing installation protection, preparation/retry controls and gateway setup unchanged.

The bar measures completed stages, not elapsed time or download bytes. Payload and
payload hashes are unchanged. All 37 existing Python tests and 15 progress checks
pass. Real HAOS installation acceptance remains required.

# 0.1.0-beta.8

- Preserve Home Assistant configuration comments, quoted values, include/secret tags,
  and existing settings while merging the required EyZEE entries.
- Verify the merged settings before writing; retain the original recovery copy and
  restore it if Home Assistant configuration validation fails.
- Stop if configuration.yaml changes while preparation is running.
- Check converter and ZHA quirk filename conflicts before backup/app mutations;
  retain unrelated customer files and reject changes to unowned files.
- Preserve an explicitly disabled ZHA quirks setting by stopping for review.
- Add ruamel.yaml 0.18.6 to the installer image for comment-preserving YAML editing.

Payload unchanged from beta.7; payload hashes remain valid. 37 automated tests pass.
Real HAOS acceptance is still required. Existing unsupported include layouts,
custom ZHA paths and custom Zigbee data paths still stop for review; this release
does not claim support for every existing-home configuration. Existing completed
EyZEE installations retain the beta.7 preparation guard.

# 0.1.0-beta.7

- Detect an existing EyZEE installation and show Open EyZEE Core instead of preparation.
- Block repeated preparation on the server before app, backup, configuration, hostname or payload changes.
- Preserve completed-install protection across restarts and connection-check failures.
- Keep resumable incomplete preparation available; do not adopt an untracked integration.

Payload unchanged from beta.6. No files removed or renamed. Fresh HAOS and completed-system reopening tests remain required. This is not an existing-home migration release.

# 0.1.0-beta.6

- Identify the downloadable installer as EyZEE Core.
- Offer eyzee-core.local before preparation; keep the existing hostname unless selected.
- Apply the chosen hostname after setup checks pass and verify it before using the new link.
- Simplify completion to Open EyZEE Core and retain current-address recovery under help.
- Preserve the tested Prepare My Home button hiding and retry behaviour.

Payload unchanged from beta.5, including its room-addition fix. No files removed or renamed. Fresh HAOS acceptance remains required.

# 0.1.0-beta.5

- Offer an explicit Use eyzee-home.local action after setup checks pass.
- Preserve the current hostname unless the owner presses that button.
- Read back the hostname before offering the new address; preserve the browser protocol and port.
- Keep the existing Open EyZEE Home link available and explain bookmark/address recovery.
- Fix hidden controls being overridden by button display styling.
- Include the supplied room-addition fix: preserve existing indoor/custom rooms and metadata, and allocate unused numbered IDs for added rooms.

Fresh HAOS test candidate only. The integration payload includes Ian's supplied room-overwrite fix. This does not establish an existing-home upgrade path. Real HAOS hostname discovery, browser access and full installation acceptance remain pending. No files removed or renamed.

# 0.1.0-beta.4

- Make secondary main-menu pages subviews with explicit back destinations; keep Home as the entry view.
- Apply gold icons to Manage Devices while retaining red Remove Device styling.
- Make Scan Existing Devices and Add to EyZEE Home compact full-width tiles, including icon actions.
- Set existing-device navigation and footer to full section width.

Dashboard changes supplied from the working HAOS system. Fresh beta.4 installation and complete navigation/action acceptance remain pending. No backend behaviour changes.

# 0.1.0-beta.3

- Refresh Smart Behaviours device choices when the device inventory, lighting groups or device names change.
- Show Locate & Set Up when devices become ready without a browser reload; open the current device list on its own dashboard.
- Exclude Zigbee2MQTT bridge and virtual groups from physical-device setup.
- Keep each physical switch's buttons together under its device label in room views.
- Apply the EyZEE Home theme across dashboards and use compact Back / Home / Help navigation; retain red delete controls.
- Move lighting-group deletion to a separate page linked from Group My Lights.
- Clarify Aura as the whole-home colour preset.

These changes have been tested incrementally on the lab HAOS system. The next fresh installation validates this consolidated package; customer release acceptance remains pending. The four supporting apps remain unchanged. Samba is not included.

# 0.1.0-beta.2

Fix MQTT discovery setup by listing pending flows through Home Assistant's WebSocket API. The previous GET request is unsupported and returns HTTP 405. Setup reports now identify failed API requests without including credentials or response bodies. Existing installed apps and recovery backups are reused when preparation resumes. Live commissioning remains under test.

# 0.1.0-beta.1

Initial lab candidate: Home Assistant ingress onboarding, four-app provisioning, checksum-verified EyZEE files, configuration validation and restart, existing MG24 service orchestration, and MQTT-backed readiness checks. Fresh HAOS acceptance remains pending.
