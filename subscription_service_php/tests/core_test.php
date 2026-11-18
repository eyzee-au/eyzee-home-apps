<?php
declare(strict_types=1);

require '/app/Core.php';

function same($actual, $expected, string $message): void
{
    if ($actual !== $expected) {
        throw new RuntimeException($message . ': expected ' . var_export($expected, true) . ', got ' . var_export($actual, true));
    }
}

same(EyzeeCore::addMonths('2024-02-29 12:30:00', 12), '2025-02-28 12:30:00', 'leap year renewal');
same(EyzeeCore::addMonths('2026-01-31 00:00:00', 1), '2026-02-28 00:00:00', 'month end renewal');
same(EyzeeCore::canonicalJson(['z' => 1, 'a' => '/x']), '{"a":"/x","z":1}', 'canonical JSON');
if (!preg_match('/^[a-f0-9-]{36}$/', EyzeeCore::uuid())) { throw new RuntimeException('UUID format'); }
$activation = EyzeeCore::activationCode();
if (!preg_match('/^EYZ-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}(?:-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}){3}$/', $activation)) {
    throw new RuntimeException('Activation code format');
}
same(EyzeeCore::activationCodeCandidates(' eyz 7k3m p9tr w6qh 4n2d ')[1], 'EYZ-7K3M-P9TR-W6QH-4N2D', 'friendly activation input');
same(EyzeeCore::activationCodeCandidates('eyz0123456789abcdef0123456789abcdef')[1], 'EYZ-0123456789ABCDEF0123456789ABCDEF', 'legacy activation input');

if (extension_loaded('sodium')) {
    $pair = sodium_crypto_sign_keypair();
    $config = [
        'data_key' => base64_encode(random_bytes(SODIUM_CRYPTO_SECRETBOX_KEYBYTES)),
        'signing_secret_key' => base64_encode(sodium_crypto_sign_secretkey($pair)),
    ];
    $plain = 'EYZ-secret-code';
    $encrypted = EyzeeCore::encrypt($plain, $config);
    same(EyzeeCore::decrypt($encrypted, $config), $plain, 'secretbox round trip');
    if (strpos($encrypted, $plain) !== false) { throw new RuntimeException('Ciphertext exposed plaintext'); }
    $manifest = ['version' => 'beta.14', 'sha256' => str_repeat('a', 64), 'size' => 123,
        'published_at' => '2026-11-13T00:00:00+00:00', 'download_path' => '/v1/download/beta.14'];
    $signature = base64_decode(EyzeeCore::sign($manifest, $config), true);
    if (!sodium_crypto_sign_verify_detached($signature, EyzeeCore::canonicalJson($manifest), sodium_crypto_sign_publickey($pair))) {
        throw new RuntimeException('Manifest signature failed');
    }
}

$row = ['id' => 'id', 'plan' => 'core', 'kind' => 'beta', 'activated_at' => null, 'expires_at' => null, 'revoked' => 0];
same(EyzeeCore::publicEntitlement($row)['status'], 'unactivated', 'unactivated state');
$row['activated_at'] = '2026-01-01 00:00:00'; $row['expires_at'] = '2025-01-01 00:00:00';
same(EyzeeCore::publicEntitlement($row)['status'], 'expired', 'expired state');
echo "Core tests passed\n";
