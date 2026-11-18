<?php
declare(strict_types=1);

final class EyzeeCore
{
    private const ACTIVATION_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';

    public static function now(): string
    {
        return gmdate('Y-m-d H:i:s');
    }

    public static function uuid(): string
    {
        $b = random_bytes(16);
        $b[6] = chr((ord($b[6]) & 0x0f) | 0x40);
        $b[8] = chr((ord($b[8]) & 0x3f) | 0x80);
        $h = bin2hex($b);
        return substr($h, 0, 8) . '-' . substr($h, 8, 4) . '-' . substr($h, 12, 4) . '-' . substr($h, 16, 4) . '-' . substr($h, 20);
    }

    public static function addMonths(string $value, int $months): string
    {
        $date = DateTimeImmutable::createFromFormat('!Y-m-d H:i:s', $value, new DateTimeZone('UTC'));
        if (!$date || $months < 1 || $months > 120) {
            throw new InvalidArgumentException('Invalid subscription date');
        }
        $day = (int)$date->format('d');
        $first = $date->modify('first day of this month')->modify('+' . $months . ' months');
        $lastDay = (int)$first->format('t');
        return $first->setDate((int)$first->format('Y'), (int)$first->format('m'), min($day, $lastDay))->format('Y-m-d H:i:s');
    }

    public static function digest(string $value): string
    {
        return hash('sha256', $value);
    }

    public static function activationCode(): string
    {
        $characters = '';
        $last = strlen(self::ACTIVATION_ALPHABET) - 1;
        for ($index = 0; $index < 16; $index++) {
            $characters .= self::ACTIVATION_ALPHABET[random_int(0, $last)];
        }
        return 'EYZ-' . implode('-', str_split($characters, 4));
    }

    public static function activationCodeCandidates(string $value): array
    {
        $upper = strtoupper(trim($value));
        $candidates = [$upper];
        $compact = preg_replace('/[\s-]+/', '', $upper);
        if (strpos($compact, 'EYZ') !== 0) {
            return $candidates;
        }
        $payload = substr($compact, 3);
        if (preg_match('/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{16}$/', $payload)) {
            $candidates[] = 'EYZ-' . implode('-', str_split($payload, 4));
        } elseif (preg_match('/^[A-F0-9]{32}$/', $payload)) {
            $candidates[] = 'EYZ-' . $payload;
        }
        return array_values(array_unique($candidates));
    }

    public static function dataKey(array $config): string
    {
        $key = base64_decode((string)($config['data_key'] ?? ''), true);
        if ($key === false || strlen($key) !== SODIUM_CRYPTO_SECRETBOX_KEYBYTES) {
            throw new RuntimeException('Configure a valid 32-byte data key');
        }
        return $key;
    }

    public static function encrypt(string $plain, array $config): string
    {
        $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        return base64_encode($nonce . sodium_crypto_secretbox($plain, $nonce, self::dataKey($config)));
    }

    public static function decrypt(string $encoded, array $config): string
    {
        $raw = base64_decode($encoded, true);
        if ($raw === false || strlen($raw) <= SODIUM_CRYPTO_SECRETBOX_NONCEBYTES) {
            throw new RuntimeException('Encrypted data is invalid');
        }
        $nonce = substr($raw, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
        $plain = sodium_crypto_secretbox_open(substr($raw, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES), $nonce, self::dataKey($config));
        if ($plain === false) {
            throw new RuntimeException('Encrypted data could not be opened');
        }
        return $plain;
    }

    public static function canonicalJson(array $value): string
    {
        ksort($value, SORT_STRING);
        return json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    }

    public static function sign(array $manifest, array $config): string
    {
        $secret = base64_decode((string)($config['signing_secret_key'] ?? ''), true);
        if ($secret === false || strlen($secret) !== SODIUM_CRYPTO_SIGN_SECRETKEYBYTES) {
            throw new RuntimeException('Configure a valid Ed25519 signing key');
        }
        return base64_encode(sodium_crypto_sign_detached(self::canonicalJson($manifest), $secret));
    }

    public static function publicEntitlement(array $row): array
    {
        $active = !empty($row['activated_at']) && empty($row['revoked']) &&
            (empty($row['expires_at']) || $row['expires_at'] > self::now());
        return [
            'entitlement_id' => $row['id'],
            'plan' => $row['plan'],
            'kind' => $row['kind'],
            'expires_at' => $row['expires_at'],
            'active' => $active,
            'status' => !empty($row['revoked']) ? 'revoked' : ($active ? 'active' : (!empty($row['activated_at']) ? 'expired' : 'unactivated')),
        ];
    }
}
