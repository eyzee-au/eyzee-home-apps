<?php
declare(strict_types=1);

ini_set('display_errors', '0');

$configPath = __DIR__ . '/config.php';
if (!is_file($configPath)) {
    throw new RuntimeException('EyZEE subscription service is not configured');
}
$config = require $configPath;
if (!is_array($config)) {
    throw new RuntimeException('EyZEE subscription configuration is invalid');
}
if (!preg_match('/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/', (string)($config['shopify_domain'] ?? ''))) {
    throw new RuntimeException('Configure the actual Shopify myshopify.com domain');
}
if (strlen((string)($config['shopify_secret'] ?? '')) < 16 || strlen((string)($config['admin_token'] ?? '')) < 32) {
    throw new RuntimeException('Configure the Shopify secret and a strong administrator token');
}
foreach (($config['variants'] ?? []) as $variant => $spec) {
    if (!ctype_digit((string)$variant) || !is_array($spec) ||
        !in_array($spec['plan'] ?? '', ['core', 'home'], true) ||
        !in_array($spec['action'] ?? '', ['activation', 'included', 'subscription', 'renewal'], true) ||
        !is_int($spec['months'] ?? 12) || ($spec['months'] ?? 12) < 1 || ($spec['months'] ?? 12) > 120) {
        throw new RuntimeException('A Shopify variant mapping is invalid');
    }
}

require_once __DIR__ . '/src/Core.php';
require_once __DIR__ . '/src/Store.php';

if (!extension_loaded('sodium')) {
    throw new RuntimeException('The Sodium PHP extension is required');
}
EyzeeCore::dataKey($config);
$signingKey = base64_decode((string)($config['signing_secret_key'] ?? ''), true);
if ($signingKey === false || strlen($signingKey) !== SODIUM_CRYPTO_SIGN_SECRETKEYBYTES) {
    throw new RuntimeException('Configure a valid Ed25519 signing key');
}

$pdo = new PDO(
    'mysql:host=' . $config['db_host'] . ';dbname=' . $config['db_name'] . ';charset=utf8mb4',
    $config['db_user'],
    $config['db_password'],
    [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]
);
$store = new EyzeeStore($pdo, $config);
