# Fresh HAOS acceptance — 0.1.0-beta.4 pending

Record HAOS, Supervisor, Core and installed app versions with the setup report. Start with a fresh backed-up `.201` and a default MG24 on Ethernet/PoE. Do not use `.200` for this run.

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
