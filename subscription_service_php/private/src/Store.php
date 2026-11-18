<?php
declare(strict_types=1);

final class EyzeeStore
{
    private PDO $db;
    private array $config;

    public function __construct(PDO $db, array $config)
    {
        $this->db = $db;
        $this->config = $config;
    }

    public function db(): PDO
    {
        return $this->db;
    }

    public function transaction(callable $work)
    {
        $this->db->beginTransaction();
        try {
            $result = $work($this->db);
            $this->db->commit();
            return $result;
        } catch (Throwable $error) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $error;
        }
    }

    public function create(string $email, string $plan, string $kind = 'paid', int $months = 12, ?string $customerId = null): string
    {
        $email = strtolower(trim($email));
        if (!filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($email) > 254 ||
            !in_array($plan, ['core', 'home'], true) || !in_array($kind, ['paid', 'included', 'beta'], true) ||
            $months < 1 || $months > 120) {
            throw new InvalidArgumentException('Invalid subscription grant');
        }
        $id = EyzeeCore::uuid();
        $code = EyzeeCore::activationCode();
        $stmt = $this->db->prepare('INSERT INTO entitlements
            (id,customer_id,email,plan,kind,months,created_at,code_hash,encrypted_code)
            VALUES (?,?,?,?,?,?,?,?,?)');
        $stmt->execute([$id, $customerId, $email, $plan, $kind, $months, EyzeeCore::now(),
            EyzeeCore::digest($code), EyzeeCore::encrypt($code, $this->config)]);
        $this->queue($id, $email, 'activation');
        $this->audit('grant', $id);
        return $id;
    }

    public function activate(string $code, string $installationId, string $credential): array
    {
        if (!preg_match('/^[a-f0-9-]{36}$/', $installationId) || strlen($credential) < 40 || strlen($credential) > 128) {
            throw new InvalidArgumentException('Activation details are invalid');
        }
        return $this->transaction(function () use ($code, $installationId, $credential): array {
            $stmt = $this->db->prepare('SELECT * FROM entitlements WHERE code_hash=? FOR UPDATE');
            $row = false;
            foreach (EyzeeCore::activationCodeCandidates($code) as $candidate) {
                $stmt->execute([EyzeeCore::digest($candidate)]);
                $row = $stmt->fetch();
                if ($row) {
                    break;
                }
            }
            if (!$row || !empty($row['revoked'])) {
                throw new InvalidArgumentException('This activation code could not be verified. Check it or contact EyZEE.');
            }
            if (!empty($row['installation_id'])) {
                if (!hash_equals($row['installation_id'], $installationId) ||
                    !hash_equals((string)$row['credential_hash'], EyzeeCore::digest($credential))) {
                    throw new InvalidArgumentException('This code is already activated. Contact EyZEE to move it to another system.');
                }
                return EyzeeCore::publicEntitlement($row);
            }
            $check = $this->db->prepare('SELECT id FROM entitlements WHERE installation_id=?');
            $check->execute([$installationId]);
            if ($check->fetch()) {
                throw new InvalidArgumentException('This installation is already activated. Contact EyZEE to change its plan.');
            }
            $at = $row['activated_at'] ?: EyzeeCore::now();
            $expiry = $row['expires_at'];
            if (!$expiry) {
                if ($row['kind'] === 'beta') {
                    $launch = $this->setting('beta_launch');
                    $expiry = $launch ? EyzeeCore::addMonths($launch, (int)$row['months']) : null;
                } else {
                    $expiry = EyzeeCore::addMonths($at, (int)$row['months']);
                }
            }
            $update = $this->db->prepare('UPDATE entitlements SET activated_at=?,expires_at=?,installation_id=?,credential_hash=? WHERE id=?');
            $update->execute([$at, $expiry, $installationId, EyzeeCore::digest($credential), $row['id']]);
            $this->audit('activate', $row['id']);
            $row['activated_at'] = $at;
            $row['expires_at'] = $expiry;
            $row['installation_id'] = $installationId;
            return EyzeeCore::publicEntitlement($row);
        });
    }

    public function authenticate(string $installationId, string $credential): array
    {
        $stmt = $this->db->prepare('SELECT * FROM entitlements WHERE installation_id=?');
        $stmt->execute([$installationId]);
        $row = $stmt->fetch();
        if (!$row || empty($row['credential_hash']) || !hash_equals($row['credential_hash'], EyzeeCore::digest($credential))) {
            throw new RuntimeException('Installation credentials could not be verified.');
        }
        return $row;
    }

    public function receive(string $id, string $topic, array $payload): void
    {
        if ($id === '' || strlen($id) > 191) {
            throw new InvalidArgumentException('Missing delivery ID');
        }
        $stmt = $this->db->prepare('INSERT IGNORE INTO inbox (id,topic,payload,received_at) VALUES (?,?,?,?)');
        $stmt->execute([$id, $topic, EyzeeCore::encrypt(json_encode($payload, JSON_THROW_ON_ERROR), $this->config), EyzeeCore::now()]);
    }

    public function processInbox(array $variants): int
    {
        $events = $this->db->query('SELECT * FROM inbox WHERE processed=0 ORDER BY received_at,id LIMIT 100')->fetchAll();
        $count = 0;
        foreach ($events as $event) {
            try {
                $payload = json_decode(EyzeeCore::decrypt($event['payload'], $this->config), true, 512, JSON_THROW_ON_ERROR);
                $this->transaction(function () use ($event, $payload, $variants): void {
                    if ($event['topic'] === 'orders/paid') {
                        $this->processOrder($payload, $variants);
                    } else {
                        $reason = 'Refund or order cancellation requires review: ' . ($payload['order_id'] ?? $payload['id'] ?? 'unknown');
                        $this->review($event['id'], $reason);
                    }
                    $stmt = $this->db->prepare('UPDATE inbox SET processed=1,error=NULL WHERE id=?');
                    $stmt->execute([$event['id']]);
                });
            } catch (Throwable $error) {
                $this->transaction(function () use ($event): void {
                    $stmt = $this->db->prepare("UPDATE inbox SET processed=1,error='Order mapping requires review' WHERE id=?");
                    $stmt->execute([$event['id']]);
                    $this->review($event['id'], 'Order mapping requires review');
                });
            }
            $count++;
        }
        return $count;
    }

    private function processOrder(array $order, array $variants): void
    {
        if (!empty($order['test']) || ($order['financial_status'] ?? '') !== 'paid' || !empty($order['cancelled_at'])) {
            return;
        }
        $email = strtolower((string)($order['email'] ?? $order['contact_email'] ?? ''));
        $customerId = (string)($order['customer']['id'] ?? '');
        foreach (($order['line_items'] ?? []) as $line) {
            $variantId = (string)($line['variant_id'] ?? '');
            if (!isset($variants[$variantId])) {
                continue;
            }
            if (!filter_var($email, FILTER_VALIDATE_EMAIL) || $customerId === '') {
                throw new InvalidArgumentException('Paid order has no customer identity');
            }
            $quantity = $line['quantity'] ?? 0;
            if (!is_int($quantity) || $quantity < 1 || $quantity > 100) {
                throw new InvalidArgumentException('Invalid quantity');
            }
            $spec = $variants[$variantId];
            $plan = (string)($spec['plan'] ?? '');
            $action = (string)($spec['action'] ?? '');
            $months = (int)($spec['months'] ?? 12);
            for ($unit = 0; $unit < $quantity; $unit++) {
                $paymentId = (string)$order['id'] . ':' . (string)$line['id'] . ':' . $unit;
                $seen = $this->db->prepare('SELECT id FROM payments WHERE id=?');
                $seen->execute([$paymentId]);
                if ($seen->fetch()) {
                    continue;
                }
                if ($action === 'activation' || $action === 'included') {
                    $id = $this->create($email, $plan, $action === 'included' ? 'included' : 'paid', $months, $customerId);
                    $this->payment($paymentId, $id);
                    continue;
                }
                if ($action !== 'renewal' && $action !== 'subscription') {
                    throw new InvalidArgumentException('Unknown product action');
                }
                $properties = [];
                foreach (($line['properties'] ?? []) as $property) {
                    $properties[(string)($property['name'] ?? '')] = (string)($property['value'] ?? '');
                }
                $id = $properties['_eyzee_entitlement_id'] ?? '';
                $sql = 'SELECT * FROM entitlements WHERE customer_id=? AND plan=?' . ($id !== '' ? ' AND id=?' : '') . ' FOR UPDATE';
                $stmt = $this->db->prepare($sql);
                $stmt->execute($id !== '' ? [$customerId, $plan, $id] : [$customerId, $plan]);
                $rows = $stmt->fetchAll();
                if ($action === 'subscription' && count($rows) === 0 && $id === '' && $quantity === 1) {
                    $newId = $this->create($email, $plan, 'paid', $months, $customerId);
                    $this->payment($paymentId, $newId);
                    continue;
                }
                if (count($rows) !== 1 || $quantity !== 1) {
                    throw new InvalidArgumentException('Renewal must identify exactly one installation');
                }
                $this->renew($rows[0], $months, $paymentId);
            }
        }
    }

    private function renew(array $row, int $months, string $paymentId): void
    {
        if (!empty($row['revoked'])) {
            throw new InvalidArgumentException('Revoked entitlement needs review');
        }
        if (!empty($row['activated_at'])) {
            $base = max($row['expires_at'] ?: EyzeeCore::now(), EyzeeCore::now());
            $stmt = $this->db->prepare('UPDATE entitlements SET expires_at=? WHERE id=?');
            $stmt->execute([EyzeeCore::addMonths($base, $months), $row['id']]);
        } else {
            $stmt = $this->db->prepare('UPDATE entitlements SET months=months+? WHERE id=?');
            $stmt->execute([$months, $row['id']]);
        }
        $this->payment($paymentId, $row['id']);
        $this->audit('renew', $row['id']);
    }

    private function payment(string $paymentId, string $entitlementId): void
    {
        $stmt = $this->db->prepare('INSERT INTO payments (id,entitlement_id,paid_at) VALUES (?,?,?)');
        $stmt->execute([$paymentId, $entitlementId, EyzeeCore::now()]);
    }

    public function queue(string $id, string $email, string $kind): void
    {
        $this->queueNamed(EyzeeCore::uuid(), $id, $email, $kind);
    }

    public function queueNamed(string $outboxId, string $id, string $email, string $kind): void
    {
        $stmt = $this->db->prepare('INSERT IGNORE INTO outbox (id,entitlement_id,email,kind,created_at) VALUES (?,?,?,?,?)');
        $stmt->execute([$outboxId, $id, $email, $kind, EyzeeCore::now()]);
    }

    public function resend(string $id): void
    {
        $stmt = $this->db->prepare('SELECT email FROM entitlements WHERE id=?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            throw new InvalidArgumentException('Subscription not found');
        }
        $this->queue($id, $row['email'], 'activation');
    }

    public function transfer(string $id): void
    {
        $this->transaction(function () use ($id): void {
            $stmt = $this->db->prepare('SELECT * FROM entitlements WHERE id=? FOR UPDATE');
            $stmt->execute([$id]);
            $row = $stmt->fetch();
            if (!$row) {
                throw new InvalidArgumentException('Subscription not found');
            }
            $code = EyzeeCore::activationCode();
            $update = $this->db->prepare('UPDATE entitlements SET installation_id=NULL,credential_hash=NULL,code_hash=?,encrypted_code=? WHERE id=?');
            $update->execute([EyzeeCore::digest($code), EyzeeCore::encrypt($code, $this->config), $id]);
            $this->queue($id, $row['email'], 'activation');
            $this->audit('transfer', $id);
        });
    }

    public function audit(string $action, string $target): void
    {
        $stmt = $this->db->prepare('INSERT INTO audit (action_name,target,occurred_at) VALUES (?,?,?)');
        $stmt->execute([$action, $target, EyzeeCore::now()]);
    }

    public function setting(string $key): ?string
    {
        $stmt = $this->db->prepare('SELECT setting_value FROM settings WHERE setting_key=?');
        $stmt->execute([$key]);
        $row = $stmt->fetch();
        return $row ? $row['setting_value'] : null;
    }

    private function review(string $id, string $reason): void
    {
        $stmt = $this->db->prepare('INSERT IGNORE INTO review (id,reason,created_at) VALUES (?,?,?)');
        $stmt->execute([$id, $reason, EyzeeCore::now()]);
    }
}
