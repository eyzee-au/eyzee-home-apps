# EyZEE subscriptions on OnlyDomains Kea

This package is the PHP/MariaDB replacement for the Docker/FastAPI subscription server. It keeps the same installer-facing API and Shopify order rules. It does not control whether an installed EyZEE home keeps working; expiry only stops new official downloads and direct support.

## Safety rules

- Keep the existing EyZEE website and existing databases untouched.
- Never put `config.php`, activation codes, Shopify secrets, signing keys, or database exports in the public subdomain folder.
- Never paste passwords or secrets into chat, GitHub, screenshots, or support tickets.
- Do not connect Shopify or the live Home Assistant installer until the private acceptance tests pass.
- Back up an existing `.htaccess` before editing it. Preserve cPanel's PHP and HTTPS lines.

## Server layout

Upload `index.php` and `admin.php` from `public/` to:

`/home/CPANEL_USER/subscriptions.eyzee.au/`

Upload the contents of `private/` to this non-public sibling folder:

`/home/CPANEL_USER/eyzee-subscriptions-private/`

The public folder contains only the HTTPS entry point and administration page. Database settings, keys, cron processing, release packages and source classes remain outside the web root.

Do not upload `eyzee-htaccess.txt` as a public text file or as a replacement for `.htaccess`. Open the existing `.htaccess`, preserve its current content, and append the EyZEE block from that file.

## Database

The dedicated database and user must be linked with all privileges. Select that database in phpMyAdmin and import:

`eyzee-subscriptions-private/schema.sql`

This creates only EyZEE subscription tables in the selected database.

## Secrets and configuration

1. Run `generate_keys.php` once through a temporary cPanel cron job:

   `/usr/local/bin/php /home/CPANEL_USER/eyzee-subscriptions-private/generate_keys.php > /home/CPANEL_USER/eyzee-subscriptions-private/generated-secrets.txt`

2. Remove that temporary cron job immediately after it runs.
3. Copy `config.example.php` to `config.php` locally.
4. Fill in the database name, database username and saved database password.
5. Copy the generated data key, signing secret key and administrator token into `config.php`.
6. Save the generated `release_public_key` separately. This is the public key later baked into EyZEE Setup; it is not a secret.
7. Delete `generated-secrets.txt` from the server after the values are safely stored.
8. Add the actual `*.myshopify.com` store domain, Shopify webhook signing secret and later the read-only order access token.
9. Add Shopify variant IDs only after the Core and Home products are created and verified.
10. Upload `config.php` to the private folder and set its permissions to `600` if File Manager permits.

Use PHP 8.4 for the subdomain if cPanel offers a per-domain setting. The code is also syntax-compatible with the current PHP 7.4 account setting, so the main site does not need to change.

## Recurring cron worker

After configuration and database import, add one cron job every five minutes:

`/usr/local/bin/php /home/CPANEL_USER/eyzee-subscriptions-private/cron.php >/dev/null 2>&1`

The worker uses a database lock so overlapping runs cannot grant twice. It processes durable Shopify receipts, queues reminders, sends activation emails and performs hourly read-only reconciliation when the Shopify access token is configured.

## Initial checks

1. Confirm `https://subscriptions.eyzee.au/health` returns `{"ok":true}`.
2. Confirm plain HTTP redirects to HTTPS.
3. Confirm an unknown path returns a JSON 404 and does not reveal a filesystem path.
4. Confirm `config.php`, `schema.sql`, release ZIPs and generated secrets are not available under the public hostname.
5. Sign in at `https://subscriptions.eyzee.au/admin.php` with the generated administrator token.
6. Create one internal Founding Beta grant and confirm exactly one email is delivered.
7. Activate it on a disposable beta.14 test installation.
8. Publish a signed test update and confirm an active installation can download it.
9. Confirm an expired test entitlement cannot download a newer release while the installed home continues working.
10. Test one Shopify test order, duplicate webhook delivery, refund review and order reconciliation before enabling live products.

## Shopify endpoints

Register these HTTPS webhook topics against the same URL:

- `orders/paid` → `https://subscriptions.eyzee.au/webhooks/shopify`
- `orders/cancelled` → `https://subscriptions.eyzee.au/webhooks/shopify`
- `refunds/create` → `https://subscriptions.eyzee.au/webhooks/shopify`

Webhook processing verifies the raw-body HMAC, exact shop domain, allowed topic and delivery ID before writing an encrypted durable receipt. Refunds and cancellations go to operator review and never switch off a customer's installed home automatically.

## Administration

The private administration page supports:

- complimentary Founding Beta, product-included and paid grants;
- customer status and expiry review;
- resending the same activation code;
- confirmed hardware transfer that invalidates the old installation credential;
- retrying or dismissing ambiguous Shopify orders;
- locking the public Founding Beta launch date;
- immutable signed release publishing.

The page never displays stored activation codes or installation credentials.
