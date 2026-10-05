# Fresh HAOS acceptance — pending

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
