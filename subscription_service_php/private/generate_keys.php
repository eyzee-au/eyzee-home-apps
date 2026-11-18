<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
if (!extension_loaded('sodium')) {
    fwrite(STDERR, "The sodium PHP extension is required.\n");
    exit(1);
}
$pair = sodium_crypto_sign_keypair();
echo "data_key=" . base64_encode(random_bytes(SODIUM_CRYPTO_SECRETBOX_KEYBYTES)) . PHP_EOL;
echo "signing_secret_key=" . base64_encode(sodium_crypto_sign_secretkey($pair)) . PHP_EOL;
echo "release_public_key=" . base64_encode(sodium_crypto_sign_publickey($pair)) . PHP_EOL;
echo "admin_token=" . bin2hex(random_bytes(32)) . PHP_EOL;
