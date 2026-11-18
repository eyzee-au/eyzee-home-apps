<?php
declare(strict_types=1);

session_name('eyzee_admin');
session_set_cookie_params(['secure' => true, 'httponly' => true, 'samesite' => 'Strict', 'path' => '/admin.php']);
session_start();
header("Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'");
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store');

require dirname(__DIR__) . '/eyzee-subscriptions-private/bootstrap.php';

function h(string $value): string { return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function redirect_admin(string $message = ''): void
{
    header('Location: /admin.php' . ($message === '' ? '' : '?message=' . rawurlencode($message)), true, 303);
    exit;
}

if (isset($_POST['login_token'])) {
    if (hash_equals((string)$config['admin_token'], (string)$_POST['login_token'])) {
        session_regenerate_id(true);
        $_SESSION['authenticated'] = true;
        $_SESSION['csrf'] = bin2hex(random_bytes(24));
        redirect_admin();
    }
    usleep(500000);
}

if (empty($_SESSION['authenticated'])) {
    echo '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>EyZEE Administration</title>';
    echo '<style>body{font:16px system-ui;background:#111;color:#eee;max-width:560px;margin:12vh auto;padding:24px}input,button{font:inherit;padding:12px;width:100%;box-sizing:border-box;margin:8px 0}button{background:#d6ad60;border:0;font-weight:700}</style>';
    echo '<h1>EyZEE Updates &amp; Support</h1><form method="post"><label>Administrator key<input type="password" name="login_token" autocomplete="current-password" required></label><button>Sign in</button></form></html>';
    exit;
}

$csrf = (string)($_SESSION['csrf'] ?? '');
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !isset($_POST['login_token'])) {
    if ($csrf === '' || !hash_equals($csrf, (string)($_POST['csrf'] ?? ''))) {
        http_response_code(403);
        exit('Invalid request');
    }
    try {
        $action = (string)($_POST['action'] ?? '');
        if ($action === 'grant') {
            $store->transaction(function () use ($store): void {
                $store->create((string)$_POST['email'], (string)$_POST['plan'], (string)$_POST['kind'], (int)$_POST['months']);
            });
            redirect_admin('Subscription created and activation email queued.');
        }
        if ($action === 'resend') {
            $store->resend((string)$_POST['id']);
            redirect_admin('Activation email queued.');
        }
        if ($action === 'transfer' && ($_POST['confirm'] ?? '') === 'yes') {
            $store->transfer((string)$_POST['id']);
            redirect_admin('Old installation access removed and a new activation email queued.');
        }
        if ($action === 'dismiss_review') {
            $stmt = $pdo->prepare('UPDATE review SET resolved_at=? WHERE id=?');
            $stmt->execute([EyzeeCore::now(), (string)$_POST['id']]);
            redirect_admin('Review item dismissed.');
        }
        if ($action === 'retry_review') {
            $pdo->beginTransaction();
            $stmt = $pdo->prepare('UPDATE inbox SET processed=0,error=NULL WHERE id=?');
            $stmt->execute([(string)$_POST['id']]);
            $stmt = $pdo->prepare('UPDATE review SET resolved_at=? WHERE id=?');
            $stmt->execute([EyzeeCore::now(), (string)$_POST['id']]);
            $pdo->commit();
            redirect_admin('Order queued for another attempt.');
        }
        if ($action === 'set_beta_launch') {
            $date = DateTimeImmutable::createFromFormat('!Y-m-d', (string)$_POST['launch_date'], new DateTimeZone('Australia/Sydney'));
            if (!$date) { throw new InvalidArgumentException('Invalid date'); }
            $utc = $date->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d H:i:s');
            $existing = $store->setting('beta_launch');
            if ($existing && $existing !== $utc) { throw new RuntimeException('Launch date is already locked'); }
            $pdo->beginTransaction();
            $stmt = $pdo->prepare('INSERT IGNORE INTO settings (setting_key,setting_value) VALUES (?,?)');
            $stmt->execute(['beta_launch', $utc]);
            $rows = $pdo->query("SELECT * FROM entitlements WHERE kind='beta' FOR UPDATE")->fetchAll();
            foreach ($rows as $row) {
                $expiry = EyzeeCore::addMonths($utc, (int)$row['months']);
                if (empty($row['expires_at']) || $row['expires_at'] < $expiry) {
                    $stmt = $pdo->prepare('UPDATE entitlements SET expires_at=? WHERE id=?');
                    $stmt->execute([$expiry, $row['id']]);
                }
            }
            $pdo->commit();
            redirect_admin('Founding Beta launch date set. It cannot be casually changed.');
        }
        if ($action === 'publish_release') {
            $version = trim((string)($_POST['version'] ?? ''));
            if (!preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/', $version) ||
                empty($_FILES['package']['tmp_name']) || ($_FILES['package']['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
                throw new InvalidArgumentException('Invalid release');
            }
            $tmp = $_FILES['package']['tmp_name'];
            $size = filesize($tmp);
            if ($size === false || $size < 1 || $size > 52428800) { throw new InvalidArgumentException('Package size is invalid'); }
            $zip = new ZipArchive();
            if ($zip->open($tmp) !== true || $zip->numFiles < 1 || $zip->numFiles > 3000) { throw new InvalidArgumentException('Package is not a safe ZIP'); }
            $uncompressed = 0;
            for ($i = 0; $i < $zip->numFiles; $i++) {
                $info = $zip->statIndex($i);
                $name = (string)($info['name'] ?? '');
                $uncompressed += (int)($info['size'] ?? 0);
                if ($name === '' || $name[0] === '/' || strpos($name, '..') !== false || strpos($name, "\\") !== false || $uncompressed > 104857600) {
                    $zip->close(); throw new InvalidArgumentException('Package contains an unsafe path or is too large');
                }
            }
            $zip->close();
            $directory = rtrim($config['release_directory'], DIRECTORY_SEPARATOR);
            if (!is_dir($directory) && !mkdir($directory, 0700, true)) { throw new RuntimeException('Release directory unavailable'); }
            $destination = $directory . DIRECTORY_SEPARATOR . $version . '.zip';
            if (is_file($destination)) { throw new RuntimeException('Release versions are immutable'); }
            if (!move_uploaded_file($tmp, $destination)) { throw new RuntimeException('Release could not be stored'); }
            chmod($destination, 0600);
            try {
                $stmt = $pdo->prepare('INSERT INTO releases (version,published_at,sha256,size_bytes,enabled) VALUES (?,?,?,?,1)');
                $stmt->execute([$version, EyzeeCore::now(), hash_file('sha256', $destination), filesize($destination)]);
            } catch (Throwable $error) {
                unlink($destination); throw $error;
            }
            $store->audit('publish', $version);
            redirect_admin('Release ' . $version . ' published for eligible customers.');
        }
    } catch (Throwable $error) {
        if ($pdo->inTransaction()) { $pdo->rollBack(); }
        redirect_admin('The request needs review; no subscription was changed.');
    }
}

$customers = $pdo->query('SELECT * FROM entitlements ORDER BY created_at DESC LIMIT 500')->fetchAll();
$review = $pdo->query('SELECT * FROM review WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 100')->fetchAll();
$pending = (int)$pdo->query('SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL')->fetchColumn();
$betaLaunch = $store->setting('beta_launch');
$message = (string)($_GET['message'] ?? '');
?><!doctype html>
<html lang="en-AU"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EyZEE Subscription Administration</title>
<style>
body{font:15px system-ui;margin:0;background:#f4f4f4;color:#171717}header{background:#111;color:#fff;padding:18px 4vw}main{max-width:1200px;margin:auto;padding:24px}section{background:#fff;border-radius:10px;padding:20px;margin:0 0 20px;box-shadow:0 2px 10px #0001}h1,h2{margin-top:0}form.inline{display:inline}input,select,button{font:inherit;padding:9px;margin:4px;border:1px solid #aaa;border-radius:5px}button{background:#d6ad60;border-color:#d6ad60;font-weight:700;cursor:pointer}.danger{background:#fff;border-color:#b33;color:#900}.notice{padding:12px;background:#eef8e9;border-left:4px solid #4a4}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid #ddd;vertical-align:top}.scroll{overflow:auto}.status-active{color:#176b28;font-weight:700}.status-expired,.status-revoked{color:#9b2226;font-weight:700}@media(max-width:700px){main{padding:12px}section{padding:14px}table{min-width:900px}}
</style></head><body><header><h1>EyZEE Updates &amp; Support</h1><div><?= count($customers) ?> subscriptions · <?= $pending ?> pending emails · <?= count($review) ?> items for review</div></header><main>
<?php if ($message !== ''): ?><p class="notice"><?= h($message) ?></p><?php endif; ?>
<section><h2>Create access</h2><form method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="grant">
<input type="email" name="email" placeholder="Customer email" required><select name="plan"><option value="core">Core</option><option value="home">Home</option></select>
<select name="kind"><option value="beta">Founding Beta</option><option value="included">Included with product</option><option value="paid">Paid year</option></select>
<input type="number" name="months" value="12" min="1" max="120" required><button>Create and email code</button></form></section>

<section><h2>Release management</h2><form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="publish_release">
<input name="version" placeholder="Version, for example beta.14" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,79}" required><input type="file" name="package" accept=".zip,application/zip" required><button>Publish signed update</button></form>
<p>Release versions cannot be silently replaced. Existing homes only see releases published within their paid access period.</p></section>

<section><h2>Founding Beta</h2><?php if ($betaLaunch): ?><p>Public launch is locked to <?= h($betaLaunch) ?> UTC. Beta access expires 12 months after this date.</p><?php else: ?>
<form method="post" onsubmit="return confirm('Set the public launch date? This date is deliberately locked once saved.');"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="set_beta_launch"><input type="date" name="launch_date" required><button>Set public launch date</button></form>
<p>Leave this unset while Founding Beta testing continues.</p><?php endif; ?></section>

<section><h2>Customers</h2><div class="scroll"><table><thead><tr><th>Email</th><th>Plan</th><th>Type</th><th>Status</th><th>Activated</th><th>Expires</th><th>Actions</th></tr></thead><tbody>
<?php foreach ($customers as $row): $public = EyzeeCore::publicEntitlement($row); ?><tr><td><?= h($row['email']) ?></td><td><?= h(ucfirst($row['plan'])) ?></td><td><?= h($row['kind']) ?></td>
<td class="status-<?= h($public['status']) ?>"><?= h($public['status']) ?></td><td><?= h((string)$row['activated_at']) ?></td><td><?= h((string)$row['expires_at']) ?></td><td>
<form class="inline" method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="resend"><input type="hidden" name="id" value="<?= h($row['id']) ?>"><button>Resend</button></form>
<?php if (!empty($row['installation_id'])): ?><form class="inline" method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="transfer"><input type="hidden" name="id" value="<?= h($row['id']) ?>"><label><input type="checkbox" name="confirm" value="yes" required> confirm transfer</label><button class="danger">Transfer</button></form><?php endif; ?></td></tr><?php endforeach; ?>
</tbody></table></div></section>

<?php if ($review): ?><section><h2>Needs review</h2><div class="scroll"><table><thead><tr><th>Received</th><th>Reason</th><th>Actions</th></tr></thead><tbody><?php foreach ($review as $row): ?><tr><td><?= h($row['created_at']) ?></td><td><?= h($row['reason']) ?></td><td>
<form class="inline" method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="retry_review"><input type="hidden" name="id" value="<?= h($row['id']) ?>"><button>Retry</button></form>
<form class="inline" method="post"><input type="hidden" name="csrf" value="<?= h($csrf) ?>"><input type="hidden" name="action" value="dismiss_review"><input type="hidden" name="id" value="<?= h($row['id']) ?>"><button class="danger">Dismiss</button></form></td></tr><?php endforeach; ?></tbody></table></div></section><?php endif; ?>
</main></body></html>
