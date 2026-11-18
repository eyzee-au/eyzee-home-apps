# PHP deployment build status

## Verified locally

- All PHP source files pass PHP 7.4 syntax checking through a WebAssembly PHP runtime.
- Shared date, canonical JSON, UUID and entitlement-state logic passes on PHP 7.4 and PHP 8.4.
- Installer-facing paths and response fields match the beta.14 Python client contract.
- Secrets and release packages are designed to live outside the subdomain document root.
- Shopify webhook HMAC checking uses the unmodified request body and timing-safe comparison.
- Database writes use PDO prepared statements and InnoDB transactions.
- Duplicate Shopify delivery IDs and payment unit IDs are idempotent.
- Release versions are immutable and update ZIP paths and sizes are checked before publishing.

## Requires Kea acceptance testing

- MariaDB schema import and PDO connection with the dedicated live database.
- Sodium encryption and Ed25519 signing with the enabled server extension. The local WebAssembly runtime did not include Sodium.
- Apache rewrite rules merged with the cPanel-generated `.htaccess`.
- Per-subdomain PHP 8.4 selection, if available.
- cPanel `mail()` delivery, SPF/DKIM alignment and retry behaviour.
- Outbound cURL access to the Shopify Admin GraphQL endpoint.
- AutoSSL activation and HTTP-to-HTTPS redirect.
- Maximum upload size for release ZIPs.
- Live Shopify Subscriptions annual renewal payloads and preservation of the entitlement line-item property.

Do not connect the production installer or enable paid Shopify products until these checks pass.
