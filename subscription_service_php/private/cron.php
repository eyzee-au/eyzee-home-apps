<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$lock = $pdo->query("SELECT GET_LOCK('eyzee_subscription_cron',0) AS locked")->fetch();
if (!$lock || (int)$lock['locked'] !== 1) {
    exit(0);
}

function queue_reminders(EyzeeStore $store, PDO $pdo, array $config): int
{
    $rows = $pdo->query("SELECT * FROM entitlements WHERE activated_at IS NOT NULL AND expires_at IS NOT NULL AND revoked=0")->fetchAll();
    $count = 0;
    $today = new DateTimeImmutable('now', new DateTimeZone('UTC'));
    foreach ($rows as $row) {
        $url = (string)($config['renewal_url_' . $row['plan']] ?? '');
        if (strpos($url, 'https://') !== 0) {
            continue;
        }
        $expiry = DateTimeImmutable::createFromFormat('!Y-m-d H:i:s', $row['expires_at'], new DateTimeZone('UTC'));
        if (!$expiry) {
            continue;
        }
        $seconds = $expiry->getTimestamp() - $today->getTimestamp();
        $remaining = $seconds / 86400;
        foreach ([30, 7, 1, 0] as $days) {
            if (($days > 0 && $remaining > $days - 1 && $remaining <= $days) || ($days === 0 && $remaining > -1 && $remaining <= 0)) {
                $id = 'reminder:' . $row['id'] . ':' . $row['expires_at'] . ':' . $days;
                $store->queueNamed($id, $row['id'], $row['email'], 'reminder:' . $days);
                $count++;
                break;
            }
        }
    }
    return $count;
}

function deliver_mail(EyzeeStore $store, PDO $pdo, array $config): int
{
    if (!filter_var($config['email_from'] ?? '', FILTER_VALIDATE_EMAIL)) {
        return 0;
    }
    $rows = $pdo->query("SELECT o.*,e.encrypted_code,e.plan FROM outbox o JOIN entitlements e ON e.id=o.entitlement_id WHERE o.sent_at IS NULL ORDER BY o.created_at LIMIT 25")->fetchAll();
    $sent = 0;
    foreach ($rows as $row) {
        if (strpos($row['kind'], 'reminder:') === 0) {
            $subject = 'Your EyZEE updates and support subscription';
            $url = $config['renewal_url_' . $row['plan']] ?? '';
            $message = "Your EyZEE updates and support access is approaching expiry or has just expired.\n\n" .
                "Your installed home keeps working. Renew to continue receiving new EyZEE updates and direct support.\n" .
                "Renewal information: " . $url . "\n\n" .
                "If you have already arranged automatic renewal, please check your Shopify account before making another purchase.\n" .
                "Help and guides: https://eyzee.au/eyzee-home/support/\n";
        } else {
            $subject = 'Your EyZEE ' . ucfirst($row['plan']) . ' activation code';
            $code = EyzeeCore::decrypt($row['encrypted_code'], $config);
            $message = "Welcome to EyZEE.\n\nYour activation code is:\n" . $code .
                "\n\nEnter this code in EyZEE Setup on your Home Assistant system.\n" .
                "Installation guide: https://eyzee.au/eyzee-core/downloads/\n\n" .
                "Your subscription provides software updates and support. Your installed system keeps working if you do not renew.\n" .
                "Public help: https://eyzee.au/eyzee-home/support/\n";
        }
        $domain = substr(strrchr($config['email_from'], '@') ?: '@eyzee.au', 1);
        $domain = preg_replace('/[^a-z0-9.-]/i', '', $domain);
        $headers = [
            'From: EyZEE Support <' . $config['email_from'] . '>',
            'Content-Type: text/plain; charset=UTF-8',
            'Message-ID: <' . hash('sha256', $row['id']) . '@' . $domain . '>',
        ];
        if (@mail($row['email'], $subject, $message, implode("\r\n", $headers))) {
            $stmt = $pdo->prepare('UPDATE outbox SET sent_at=? WHERE id=? AND sent_at IS NULL');
            $stmt->execute([EyzeeCore::now(), $row['id']]);
            $sent++;
        }
    }
    return $sent;
}

function reconcile_shopify(EyzeeStore $store, PDO $pdo, array $config): bool
{
    $token = (string)($config['shopify_access_token'] ?? '');
    if ($token === '' || !function_exists('curl_init')) {
        return false;
    }
    $last = $store->setting('reconciled_at');
    $since = $last ? gmdate('c', strtotime($last . ' UTC') - 172800) : gmdate('c', time() - 5184000);
    $query = <<<'GRAPHQL'
query PaidOrders($after:String,$query:String!){orders(first:25,after:$after,query:$query,sortKey:UPDATED_AT){pageInfo{hasNextPage endCursor}nodes{id email test cancelledAt displayFinancialStatus updatedAt customer{id}lineItems(first:100){pageInfo{hasNextPage}nodes{id quantity variant{id}customAttributes{key value}}}}}}
GRAPHQL;
    $after = null;
    $started = EyzeeCore::now();
    for ($page = 0; $page < 100; $page++) {
        $payload = json_encode(['query' => $query, 'variables' => ['after' => $after, 'query' => 'updated_at:>=' . $since]], JSON_THROW_ON_ERROR);
        $curl = curl_init('https://' . $config['shopify_domain'] . '/admin/api/2026-10/graphql.json');
        curl_setopt_array($curl, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $payload, CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30, CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-Shopify-Access-Token: ' . $token]]);
        $raw = curl_exec($curl);
        $status = (int)curl_getinfo($curl, CURLINFO_RESPONSE_CODE);
        curl_close($curl);
        if (!is_string($raw) || $status < 200 || $status >= 300) {
            throw new RuntimeException('Shopify reconciliation request failed');
        }
        $result = json_decode($raw, true, 64, JSON_THROW_ON_ERROR);
        if (!empty($result['errors']) || empty($result['data']['orders'])) {
            throw new RuntimeException('Shopify reconciliation returned an error');
        }
        $orders = $result['data']['orders'];
        foreach ($orders['nodes'] as $order) {
            if (!empty($order['lineItems']['pageInfo']['hasNextPage'])) {
                $stmt = $pdo->prepare('INSERT IGNORE INTO review (id,reason,created_at) VALUES (?,?,?)');
                $stmt->execute([$order['id'], 'Order has over 100 lines; reconcile separately', EyzeeCore::now()]);
                continue;
            }
            $mapped = ['id' => basename($order['id']), 'email' => $order['email'], 'test' => $order['test'],
                'cancelled_at' => $order['cancelledAt'], 'financial_status' => strtolower($order['displayFinancialStatus']),
                'customer' => ['id' => empty($order['customer']['id']) ? '' : basename($order['customer']['id'])], 'line_items' => []];
            foreach ($order['lineItems']['nodes'] as $line) {
                $properties = [];
                foreach ($line['customAttributes'] as $p) {
                    $properties[] = ['name' => $p['key'], 'value' => $p['value']];
                }
                $mapped['line_items'][] = ['id' => basename($line['id']), 'quantity' => $line['quantity'],
                    'variant_id' => empty($line['variant']['id']) ? '' : basename($line['variant']['id']), 'properties' => $properties];
            }
            $topic = $order['cancelledAt'] ? 'orders/cancelled' : (strpos($order['displayFinancialStatus'], 'REFUND') !== false ? 'refunds/create' : 'orders/paid');
            $store->receive('reconcile:' . $order['id'] . ':' . $order['updatedAt'], $topic, $mapped);
        }
        if (empty($orders['pageInfo']['hasNextPage'])) {
            $stmt = $pdo->prepare('INSERT INTO settings (setting_key,setting_value) VALUES (?,?) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)');
            $stmt->execute(['reconciled_at', $started]);
            return true;
        }
        $after = $orders['pageInfo']['endCursor'];
    }
    throw new RuntimeException('Shopify reconciliation page limit reached');
}

try {
    $inbox = $store->processInbox($config['variants'] ?? []);
    $reminders = queue_reminders($store, $pdo, $config);
    $mail = deliver_mail($store, $pdo, $config);
    $lastAttempt = $store->setting('reconcile_attempt_at');
    if (!$lastAttempt || strtotime($lastAttempt . ' UTC') < time() - 3600) {
        $stmt = $pdo->prepare('INSERT INTO settings (setting_key,setting_value) VALUES (?,?) ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)');
        $stmt->execute(['reconcile_attempt_at', EyzeeCore::now()]);
        reconcile_shopify($store, $pdo, $config);
    }
    echo 'EyZEE subscription worker completed: inbox=' . $inbox . ' reminders=' . $reminders . ' email=' . $mail . PHP_EOL;
} catch (Throwable $error) {
    error_log('EyZEE subscription worker requires retry: ' . get_class($error));
    exit(1);
} finally {
    $pdo->query("SELECT RELEASE_LOCK('eyzee_subscription_cron')");
}
