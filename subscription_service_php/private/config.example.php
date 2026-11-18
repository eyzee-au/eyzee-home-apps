<?php
/* Copy to config.php, fill in locally, and chmod 600. Never place this file in the web root. */
return [
    'db_host' => 'localhost',
    'db_name' => 'CPANELPREFIX_subscriptions',
    'db_user' => 'CPANELPREFIX_subsvc',
    'db_password' => 'CHANGE_ME',
    'shopify_secret' => 'CHANGE_ME',
    'shopify_domain' => 'your-store.myshopify.com',
    'shopify_access_token' => '',
    'admin_token' => 'CHANGE_TO_AT_LEAST_32_RANDOM_CHARACTERS',
    'data_key' => 'BASE64_32_BYTE_KEY',
    'signing_secret_key' => 'BASE64_64_BYTE_ED25519_SECRET_KEY',
    'email_from' => 'support@eyzee.au',
    'renewal_url_core' => '',
    'renewal_url_home' => '',
    'variants' => [
        /* 'SHOPIFY_VARIANT_ID' => ['plan' => 'core', 'action' => 'subscription', 'months' => 12], */
    ],
    'release_directory' => __DIR__ . '/releases',
];
