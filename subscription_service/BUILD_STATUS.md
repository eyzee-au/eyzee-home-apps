# Test build status — 13 November 2026

Implemented locally on branch `feature/subscriptions`, based on public main
`599fca060029b5231d83369075a134ac6dbb771a`. Setup version is beta.14.

## Verification completed

- 34 subscription/service/client/updater Python tests passed.
- 49 existing installer and ingress/server Python tests passed.
- 4 new subscription/admin DOM scenarios passed.
- 9 existing reconnection/hostname DOM scenarios passed.
- Repository diff whitespace checks passed.
- The full real source payload was packaged, signed through the test service,
  downloaded by the client and passed through fresh setup using simulated
  Supervisor/MQTT services. No live Home Assistant host or Zigbee radio was used.
- The tracked application payload is unchanged from the public baseline.

The tests cover signed Shopify fixtures, duplicate delivery and reconciliation,
activation retry, first-year/Beta dates, expiry, old-release recovery, invalid
credentials/signatures/archives, hardware transfer, retryable email delivery,
reminders, conservative updates, local-edit refusal, file-validation rollback,
interrupted-file recovery and changed-converter reload/refusal.

## Not claimed

- No live Shopify checkout, recurring charge, webhook installation or email sent.
- No products or prices created in the store. Proposed prices are recorded in
  `plans.json`: Core A$27/year and Home A$49.95/year; confirm GST treatment.
- No hosting service, DNS domain or HTTPS endpoint provisioned.
- No GitHub push or customer release publication.
- No .200 or .201 changes, hardware flashing or network configuration changes.
- Chromium could not launch because the execution environment disallowed its
  required socket operations. DOM tests passed, but rendered desktop/mobile
  verification and the supplied Playwright test still need running elsewhere.
- Docker is not installed here, so the service and add-on Docker image builds
  still need verification on the deployment host and .201 respectively.

## Next operational step

Choose the always-on service host, then configure HTTPS, persistent storage,
secrets and email. Connect Shopify paid-order notifications and read-orders
reconciliation, verify a controlled real checkout and annual renewal linkage,
then test fresh setup and populated-home updates on .201 before publication.

See `DEPLOYMENT.md` for commands, architecture, product mapping, billing-date
handling, multi-installation limitations and the live acceptance checklist.
