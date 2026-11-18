# Fresh HAOS acceptance — 0.1.0-beta.15 pending

Record HAOS, Supervisor, Core and installed app versions with the setup report. Start with a fresh backed-up `.201` and a default MG24 on Ethernet/PoE. Do not use `.200` for this run.

## Beta.15 editions and update-rendering acceptance

The beta.14 activation, subscription and signed-update flow passed an end-to-end
HAOS test. Re-run those checks below and add the edition checks on a backed-up
HAOS test machine before publication.

- [ ] A `core` entitlement installs EyZEE® Core page titles, headings and theme name.
- [ ] A `home` entitlement retains EyZEE® Home page titles, headings and theme name.
- [ ] Lowercase `/eyzee-home/` support URLs, `eyzee_home` identifiers, dashboard IDs and file paths are unchanged.
- [ ] Advanced Controls shows **Updates & Support** (`mdi:update`) and opens `/config/app/eba672c4_eyzee_setup/ingress`.
- [ ] A signed update changes `eyzee/dashboards.yaml` and static `eyzee/ui/` files for the activated edition.
- [ ] A fresh Core install creates `eyzee/state/rooms.yaml` with `project: My EyZEE Core`; a fresh Home install keeps `project: My EyZEE Home`.
- [ ] Re-prepare or restart with a customer-edited `eyzee/state/rooms.yaml`; the file remains byte-for-byte unchanged.
- [ ] An update leaves `eyzee/ui/eyzee-room.yaml`, `eyzee/ui/eyzee-master.yaml`, `eyzee/ui/setup/add_device.yaml`, `eyzee/ui/setup/device_setup.yaml`, room state and other customer-generated data untouched.
- [ ] An expired subscription still starts and runs the installed home; only official updates and support are unavailable.
- [ ] The release package and Setup image contain no activation codes, customer credentials, installation state or signing private keys.

## Beta.14 activation and release delivery

- [ ] Setup first shows the activation screen and makes no Home Assistant changes before activation succeeds.
- [ ] An invalid code shows a useful message and leaves the home unchanged.
- [ ] The retained Founding Beta test code activates once and binds to this HAOS installation.
- [ ] Setup downloads the published release only from `https://subscriptions.eyzee.au`.
- [ ] A changed signature, package hash or payload hash is rejected before installation.
- [ ] After activation, **Prepare My Home** appears and completes the existing fresh-install flow.
- [ ] Reopening Setup does not request the activation code again.
- [ ] The administrator page shows the entitlement as active and records the installation and activation time.
- [ ] An expired or unavailable subscription service never disables an already installed home.
- [ ] Setup status and downloaded reports contain no activation code, installation credential or release signing secret.

- [ ] EyZEE Setup image builds and its admin-only ingress opens.
- [ ] A non-admin account cannot open or start setup.
- [ ] Prepare installs/starts all four specified apps without visiting their configuration pages.
- [ ] MQTT integration loads without manual credentials.
- [ ] EyZEE files, ZHA quirks and all approved converters install.
- [ ] Core configuration check passes before restart; ingress recovers after Core restart.
- [ ] Gateway discovery displays MAC/IP; customer chooses the intended available gateway.
- [ ] Existing coordinator/extender protection is respected.
- [ ] MG24 setup writes `ember` and `tcp://<selected-ip>:6638` using the existing service.
- [ ] Zigbee2MQTT starts with onboarding disabled and reports online with that same serial port.
- [ ] All supplied converter names are reported as loaded.
- [ ] The ready button opens EyZEE Home; rooms and device pairing work.
- [ ] Pair a supported switch/light and control it in both directions.
- [ ] Run Prepare again: customer room/state and Zigbee network settings remain intact.
- [ ] Restart the Setup app: stale readiness is cleared; Prepare rechecks successfully.
- [ ] Reboot HAOS: apps reconnect; reopened Setup rechecks successfully.
- [ ] Power-cycle MG24: Zigbee reconnects.
- [ ] A missing/offline gateway produces a useful message and never reports ready.
- [ ] Induce coordinator failure in the lab and confirm backend rollback restores the prior configuration.
- [ ] Simulate a failed Core configuration check: original configuration is restored and Core is not restarted.
- [ ] Setup report contains no MQTT password, Supervisor token or network key.
- [ ] Restore the pre-install full backup and verify recovery.

Do not distribute to ordinary customers until every applicable item passes. Final converter/quirk selection must be approved before release.

## Consolidated dashboard regression checks

- [ ] Newly paired device makes Locate & Set Up appear without F5; opening it shows the new physical device.
- [ ] Zigbee2MQTT bridge and virtual lighting groups are excluded from Locate & Set Up.
- [ ] Two physical wall switches in one room have separate headings and controls in endpoint order.
- [ ] Smart Behaviours device and group dropdowns populate after adding and renaming devices without Developer Tools actions.
- [ ] Group My Lights dropdown labels use the saved control names.
- [ ] Check a light set up immediately after a multi-gang switch: its control name must match its device name. This previously inherited the last switch button name and remains a known regression check.
- [ ] Main lighting-group setup has a discreet Delete lighting groups link; deletion controls appear only on the separate page.
- [ ] Back / Home / Help navigation, theme and red delete styling work across screens.
- [ ] Aura wording and saved colour work across room controls and Smart Behaviours.

## Beta.12 restart and hostname acceptance

- [ ] On the backed-up test system, install beta.12 and test on iPhone/Safari with the eyzee-core.local checkbox selected. Confirm the restart/reconnect message replaces the raw JSON page, and gateway selection and readiness complete.
- [ ] Open EyZEE Core using the main completion button; it opens the confirmed eyzee-core.local address and matches the text below it.
- [ ] If asked, sign in, then confirm the room dashboard loads. Confirm the new address resolves on the test network.
- [ ] Repeat with the checkbox unticked; confirm the completion button and address text both use the original hostname.
- [ ] While Core restarts, reload the Setup screen. It either stays on the progress screen or shows the recovery screen and retries. If the Home Assistant ingress session has expired, reopening Home Assistant as an administrator and opening Setup restores access.
- [ ] A non-admin, a missing user header, a direct app-port request, and an invalid CSRF token still cannot read setup state or start actions.
- [ ] Report download contains no CSRF token, passwords, Supervisor token or network keys.

The web app cannot reconnect through a hostname that no longer resolves, or bypass a Home Assistant sign-in on a new origin. In those cases use the new address or IP and reopen Setup after signing in. A fresh HAOS end-to-end run is still required before claiming the phone issue is resolved.
