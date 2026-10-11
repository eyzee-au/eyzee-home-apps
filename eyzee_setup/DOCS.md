# Preparing your EyZEE Home

Connect your EyZEE Zigbee gateway to Ethernet and power it on. Open EyZEE Setup and press **Prepare My Home**. Setup saves a recovery copy, prepares your home services, and checks the connection. Home Assistant restarts during preparation; keep the screen open.

Choose your gateway when prompted. Its MAC address is the stable identifier; its network address may change. When setup passes its checks, choose **Open EyZEE Core**.

If preparation stops, check power and network, then press **Retry Preparation**. If you restarted the Setup app or Home Assistant OS, reopen this screen and press **Prepare My Home**. Your progress is saved.

If the problem repeats, select **Setup progress & help**, download the setup report, and give it to EyZEE Support. Do not send passwords or Zigbee network keys.

This is a test release for a fresh installation. Existing or modified EyZEE files may require installer review before preparation can proceed.

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
