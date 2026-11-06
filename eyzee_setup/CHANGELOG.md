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
