<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function respond(array $body, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function request_body(int $limit = 1048576): string
{
    $length = (int)($_SERVER['CONTENT_LENGTH'] ?? 0);
    if ($length > $limit) {
        respond(['error' => 'Request too large'], 413);
    }
    $body = file_get_contents('php://input', false, null, 0, $limit + 1);
    if ($body === false || strlen($body) > $limit) {
        respond(['error' => 'Request too large'], 413);
    }
    return $body;
}

function json_body(): array
{
    try {
        $body = json_decode(request_body(), true, 32, JSON_THROW_ON_ERROR);
    } catch (Throwable $error) {
        respond(['error' => 'Invalid JSON'], 400);
    }
    if (!is_array($body)) {
        respond(['error' => 'Invalid JSON'], 400);
    }
    return $body;
}

function bearer(): string
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    return strpos($header, 'Bearer ') === 0 ? substr($header, 7) : '';
}

function authenticated(EyzeeStore $store): array
{
    $parts = explode(':', bearer(), 2);
    if (count($parts) !== 2) {
        respond(['error' => 'Reopen EyZEE activation or contact support.'], 401);
    }
    try {
        return $store->authenticate($parts[0], $parts[1]);
    } catch (Throwable $error) {
        respond(['error' => 'Reopen EyZEE activation or contact support.'], 401);
    }
}

try {
    require dirname(__DIR__) . '/eyzee-subscriptions-private/bootstrap.php';
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

    if ($method === 'GET' && $path === '/health') {
        respond(['ok' => true]);
    }

    if ($method === 'POST' && $path === '/v1/activate') {
        if (function_exists('apcu_inc')) {
            $address = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
            $key = 'eyzee_activate_' . hash('sha256', $address);
            apcu_add($key, 0, 60);
            $success = false;
            $attempts = apcu_inc($key, 1, $success, 60);
            if (!$success) { $attempts = 1; apcu_store($key, 1, 60); }
            if ((int)$attempts > 10) { respond(['error' => 'Please wait a minute before trying again.'], 429); }
        }
        $body = json_body();
        $code = (string)($body['code'] ?? '');
        $installationId = (string)($body['installation_id'] ?? '');
        $credential = (string)($body['credential'] ?? '');
        if (strlen($code) < 10 || strlen($code) > 100) {
            respond(['error' => 'This activation code could not be verified. Check it or contact EyZEE.'], 409);
        }
        try {
            respond($store->activate($code, $installationId, $credential));
        } catch (InvalidArgumentException $error) {
            respond(['error' => $error->getMessage()], 409);
        }
    }

    if ($method === 'GET' && $path === '/v1/entitlement') {
        respond(EyzeeCore::publicEntitlement(authenticated($store)));
    }

    if ($method === 'GET' && $path === '/v1/releases/latest') {
        $entitlement = authenticated($store);
        $stmt = $pdo->query('SELECT * FROM releases WHERE enabled=1 ORDER BY published_at DESC,version DESC');
        $release = null;
        foreach ($stmt->fetchAll() as $candidate) {
            if (!empty($entitlement['activated_at']) && empty($entitlement['revoked']) &&
                (empty($entitlement['expires_at']) || $candidate['published_at'] <= $entitlement['expires_at'])) {
                $release = $candidate;
                break;
            }
        }
        if (!$release) {
            respond(['error' => 'No authorised release is available. Contact EyZEE support.'], 404);
        }
        $manifest = [
            'version' => $release['version'],
            'sha256' => $release['sha256'],
            'size' => (int)$release['size_bytes'],
            'published_at' => gmdate('c', strtotime($release['published_at'] . ' UTC')),
            'download_path' => '/v1/download/' . $release['version'],
        ];
        respond(['manifest' => $manifest, 'signature' => EyzeeCore::sign($manifest, $config),
            'entitlement' => EyzeeCore::publicEntitlement($entitlement)]);
    }

    if ($method === 'GET' && preg_match('#^/v1/download/([A-Za-z0-9][A-Za-z0-9._-]{0,79})$#', $path, $match)) {
        $entitlement = authenticated($store);
        $stmt = $pdo->prepare('SELECT * FROM releases WHERE version=? AND enabled=1');
        $stmt->execute([$match[1]]);
        $release = $stmt->fetch();
        if (!$release || empty($entitlement['activated_at']) || !empty($entitlement['revoked']) ||
            (!empty($entitlement['expires_at']) && $release['published_at'] > $entitlement['expires_at'])) {
            respond(['error' => 'This release requires an active updates subscription.'], 403);
        }
        $file = rtrim($config['release_directory'], DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $release['version'] . '.zip';
        if (!is_file($file) || filesize($file) !== (int)$release['size_bytes']) {
            respond(['error' => 'Download temporarily unavailable. Please retry later.'], 503);
        }
        header_remove('Content-Type');
        header('Content-Type: application/zip');
        header('Content-Length: ' . filesize($file));
        header('Content-Disposition: attachment; filename="EyZEE-' . $release['version'] . '.zip"');
        readfile($file);
        exit;
    }

    if ($method === 'POST' && $path === '/webhooks/shopify') {
        $raw = request_body();
        $expected = base64_encode(hash_hmac('sha256', $raw, $config['shopify_secret'], true));
        $provided = $_SERVER['HTTP_X_SHOPIFY_HMAC_SHA256'] ?? '';
        if ($provided === '' || !hash_equals($expected, $provided)) {
            respond(['error' => 'Invalid signature'], 401);
        }
        if (($_SERVER['HTTP_X_SHOPIFY_SHOP_DOMAIN'] ?? '') !== $config['shopify_domain']) {
            respond(['error' => 'Unknown store'], 401);
        }
        $topic = $_SERVER['HTTP_X_SHOPIFY_TOPIC'] ?? '';
        if (!in_array($topic, ['orders/paid', 'orders/cancelled', 'refunds/create'], true)) {
            respond(['error' => 'Unsupported topic'], 400);
        }
        $id = $_SERVER['HTTP_X_SHOPIFY_WEBHOOK_ID'] ?? '';
        try {
            $payload = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
            if (!is_array($payload)) {
                throw new RuntimeException('Invalid payload');
            }
            $store->receive($id, $topic, $payload);
        } catch (InvalidArgumentException $error) {
            respond(['error' => $error->getMessage()], 400);
        } catch (Throwable $error) {
            respond(['error' => 'Invalid JSON'], 400);
        }
        respond(['received' => true]);
    }

    respond(['error' => 'Not found'], 404);
} catch (Throwable $error) {
    error_log('EyZEE subscription service request failed: ' . get_class($error));
    respond(['error' => 'Service temporarily unavailable'], 503);
}
