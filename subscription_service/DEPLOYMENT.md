# EyZEE subscriptions — implementation and deployment

This is a local, tested implementation candidate, not a live commercial service.
The base repository was main commit `599fca060029b5231d83369075a134ac6dbb771a`
(Setup beta.13). Work is isolated on `feature/subscriptions` as beta.14.
No Shopify products, subscriptions, webhooks or payments were created. No
repository changes were pushed. Neither HAOS .200 nor .201 was accessed.

## Customer promise and proposed prices

- Core: A$27/year, standard non-priority email support and official updates.
- Home: A$49.95/year, first 12 months included with hardware from activation.
  Includes priority email, limited Sophie troubleshooting and callbacks within
  24 hours during business hours. Define business hours, holiday handling and
  human support scope before publishing those promises.
- Confirm GST treatment before checkout prices go live. Prices above are the
  proposed customer-facing amounts, not an instruction to add tax on top.
- Public help, videos and guides remain available without a subscription.
- No runtime licence lock. Expiry or a service outage never disables the home.
- Founding Beta: free during testing, then 12 months from the recorded public
  launch date, not the redemption date. No payment details required.
- Previous eligible official releases remain downloadable for recovery after
  expiry. Renewal makes the current release available again.

## What has been implemented

1. HTTPS API for activation, entitlement checks, signed release manifests and
   authenticated downloads, plus an authenticated customer-management page.
2. SQLite transactions and unique order-line-unit payment keys. Replayed
   Shopify notifications and reconciliation cannot credit the same payment twice.
3. HMAC-verified, store-verified Shopify webhook receipt with encrypted durable
   inbox, separate processing worker, encrypted activation-code storage,
   retryable TLS SMTP email delivery and paid-order API reconciliation.
4. Core, included Home and Beta grants; original activation and paid expiry
   survive a hardware transfer. Codes can be resent without creating a new grant.
5. Reminder email queue (30, 7, 1 and expiry day), enabled only after plan-specific
   HTTPS renewal URLs are configured. Shopify continues to own auto-billing.
6. Public Setup container excludes bundled payload. Source remains public;
   official packages are delivered by the entitlement service.
7. Setup activation UI, check-for-updates action and explicit update/restart
   confirmation, preserving ingress administrator verification and CSRF checks.
8. SHA-256 package verification bound to an Ed25519-signed manifest, safe bounded
   ZIP extraction and an allowlist of updateable code/helper/theme/converter paths.
9. Full HAOS backup before update; local-edit refusal; file rollback if validation
   fails; durable recovery journal for interruptions while writing files.

## Required before live use

- Choose an always-on hosting environment supporting a Python service or Docker,
  persistent disk, scheduled/background worker, HTTPS and database backups.
  Static website hosting alone is not enough. A proposed domain such as
  `updates.eyzee.au` must not be treated as provisioned or already owned in DNS.
- Connect the store and configure its real `*.myshopify.com` domain, webhook
  signing secret, and read-orders API access token for reconciliation.
- Confirm prices/tax and create the actual digital subscription variants in
  Shopify Subscriptions. Do not put the hardware itself on recurring billing.
- Configure transactional email credentials and verify sender delivery.
- Set the official service origin and release public key in Setup. For release,
  bake those PUBLIC values into the app defaults so customers enter only a code.
- Test on .201 before touching .200. Live Shopify first checkout and actual
  recurring renewal payloads must be tested; simulated payments are not proof
  of store/app integration. No real payments are performed by these tests.

## Local verification

From repository root, Python 3.12+:

```sh
python -m venv .venv
.venv/bin/pip install -r subscription_service/requirements.txt PyYAML==6.0.2 ruamel.yaml==0.18.6 websocket-client==1.8.0 httpx==0.28.1
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s eyzee_setup -v
```

## Hosting setup

Generate secrets on the selected host, privately. Never paste their output into
public repository files, support reports or customer messages:

```sh
python -m subscription_service.cli keys
```

Copy `.env.example` to a host-local `.env` and populate it through the host's
secret manager. Retain the Ed25519 public key for installer configuration.
Back up the private signing key and Fernet data key separately from encrypted
database backups. Losing the data key loses activation-email delivery data.
Losing the signing key requires an explicit installer key-rotation release.

For Docker, run from `subscription_service/` after preparing its local `data/`
directory for UID 10001 and populating `.env`:

```sh
docker compose up --build -d
```

Place a TLS reverse proxy in front of localhost port 8080, with a 1 MiB request
limit, IP rate limits, and no request-body or Authorization logging. Keep `/admin`
behind an additional administrator access gate if the hosting platform supports
one. Do not expose a shared admin key in the storefront. Only one email worker
should run for the v1 SQLite deployment; use transactional queue leases before
scaling workers. Monitor worker retries, review items and email backlog.

Back up the SQLite database using its online backup API, along with `releases/`
and secret keys; restore-test before launch. Do not copy an actively written
SQLite database as an ordinary file. Setup's `/data/subscription.json` contains
the installation credential: it must be included in protected HAOS app backups,
never a diagnostic report. Hardware transfer invalidates the old credential.

## Shopify mapping

`EYZEE_VARIANTS` maps **numeric variant IDs**, not titles or SKUs, for example:

```json
{
  "ACTUAL_CORE_ANNUAL_VARIANT_ID": {"plan":"core","action":"subscription","months":12},
  "ACTUAL_HOME_HARDWARE_VARIANT_ID": {"plan":"home","action":"included","months":12},
  "ACTUAL_HOME_ANNUAL_VARIANT_ID": {"plan":"home","action":"subscription","months":12}
}
```

Replace the example key labels with numeric IDs. The service rejects placeholder
labels. Rules:

- `activation`: creates one paid activation code per quantity purchased.
- `included`: creates one included first-year code per hardware unit.
- `subscription`: first paid order creates access if the buyer has no matching
  plan; later paid orders extend their single matching entitlement.
- `renewal`: extends an existing entitlement only; never creates a new one.
- Matching uses Shopify customer ID and plan, not an email-only guess. Checkout
  must attach the buyer to a Shopify customer. Reconcile guest identity and
  changed accounts in the review queue rather than extending another home.
- **V1 has a single-installation-per-customer-per-plan automatic matching rule.**
  Customers with multiple installations of the same plan must supply a matching
  `_eyzee_entitlement_id` line-item property that survives subscription renewal.
  Verify property persistence in the actual Shopify Subscriptions app. If it
  cannot be guaranteed, add an explicit contract/order mapping before supporting
  multi-installation automatic billing. Ambiguous renewals enter review; they
  never guess which home to extend.
- An early renewal extends from the later of now and existing paid expiry.
  An unactivated paid grant accumulates months without starting its first year.
- Shopify's recurring billing anniversary is controlled by Shopify checkout and
  its subscription app, not by our code-redemption date. For the promised first
  year from activation, sell initial Core access as a one-time `activation`
  purchase and invite customers into an annual renewal plan near expiry. Home
  hardware uses `included`. Do not enrol either in automatic billing at purchase
  and imply their first future charge will automatically follow a later activation.
  If recurring billing is offered immediately, disclose its checkout-based
  billing anniversary separately and test the entitlement overlap rules.
- Test-mode orders do not grant access. Exercise test flows through complimentary
  grants and signed fixtures, then validate a controlled real checkout with the
  owner's explicit payment approval before launch.

Subscribe paid-order, cancelled-order and refund webhooks to
`https://YOUR_CONFIGURED_ORIGIN/webhooks/shopify` using API version 2026-10.
Set the correct signing secret for whichever Shopify app/admin webhook actually
registers the subscription; do not substitute an API access token for that secret.
Do not subscribe to contracts owned by the Shopify Subscriptions app and assume
our separate app can read them. V1 uses paid orders and read-orders reconciliation.

Cancellation of recurring billing does not shorten paid-through access. Failed
payments add no access. Refunds and order cancellations enter operator review
without disabling the home. Product-purchase rewards and Nabu Casa bundling are
not implemented because their commercial rules have not been agreed.

## Publish releases and configure Setup

Create a package from the approved payload (never from a live customer's config):

```sh
python tools/build_release.py --version YOUR_NEW_VERSION --output dist/EyZEE-YOUR_NEW_VERSION.zip
```

On the service host with the same service environment loaded:

```sh
python -m subscription_service.cli publish /path/to/EyZEE-YOUR_NEW_VERSION.zip
```

Published version names are immutable. The server signs the release digest with
its private key; Setup pins the public key and will not follow redirects with
customer credentials. Both Core and Home currently use the same approved code,
with different support entitlements.

Set `service_url` to the HTTPS origin (no path) and `release_public_key` to the
base64 Ed25519 public key in Setup app configuration for lab testing. These
fields are deliberately empty in the unpublished candidate: a fresh install
cannot silently fall back to unverified bundled software.

The current updater covers integration code, EyZEE helpers/scripts/themes,
EyZEE-specific ZHA quirks and converters. It does not delete old files, change
Zigbee networking, replace customer state/generated dashboards, or perform new
configuration-schema migrations. A release that needs these changes requires a
separately tested migration and a new release format/installer. Do not call a
release universally upgradeable just because it can be downloaded.

The full-backup and config validation checks do not prove successful runtime
startup. V1 retains the backup and previous file journal, but a runtime failure
after restart still needs the operator's backup recovery path. Live startup
health checks and unattended rollback remain a pre-launch hardening item.

## Operator management

Visit `/admin` over HTTPS and use the private administrator key. The UI lists
up to 500 customers and 100 open review items. It can grant complimentary access,
resend activation codes and retry/dismiss review items. The JSON API also has
confirmed hardware transfer; CLI equivalents below. Unbounded management views,
customised support-ticket integration and automatic Sophie lookups are not yet
connected. The service records which plan is entitled to support.

```sh
python -m subscription_service.cli grant --email CUSTOMER_EMAIL --plan core --kind beta
python -m subscription_service.cli list
python -m subscription_service.cli resend ENTITLEMENT_ID
python -m subscription_service.cli transfer ENTITLEMENT_ID
python -m subscription_service.cli launch-beta --date ACTUAL_LAUNCH_ISO_DATE_WITH_TIMEZONE
python -m subscription_service.cli reconcile
python -m subscription_service.cli process
```

Grant creation queues email; it never prints activation codes. Transfer must be
requested by the verified customer and preserves paid expiry. The launch date is
not guessed or silently changed. Free access never creates an automatic payment
agreement; Shopify checkout must collect explicit consent for future billing.

## Acceptance before publishing beta.14

1. Restore-test service database, package storage and keys.
2. Prove a new paid order produces exactly one email/code, including webhook
   replay and read-orders backfill.
3. On .201, activate Core, prepare fresh HAOS, commission only the intended MG24,
   and verify all existing onboarding behaviour. Never flash the .200 coordinator.
4. Activate Home and Beta grants; verify first-year and launch-date calculations.
5. Perform an actual Shopify annual renewal and confirm entitlement/customer
   linkage from its payload, cancellation and failure handling.
6. Update a populated .201; verify rooms, names, groups, automations and Zigbee
   network remain intact. Exercise local-edit refusal, config-check failure,
   host interruption and failed post-restart runtime.
7. Simulate expiry and service outage; show local control still works and an
   older eligible release remains recoverable.
8. Verify SMTP delivery, sender authentication and reminder URLs, then set public
   service/key defaults and publish Setup only after the service is operational.
