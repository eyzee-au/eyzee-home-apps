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
