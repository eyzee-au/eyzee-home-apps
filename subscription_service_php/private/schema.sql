CREATE TABLE IF NOT EXISTS entitlements (
  id CHAR(36) PRIMARY KEY,
  customer_id VARCHAR(64) NULL,
  email VARCHAR(254) NOT NULL,
  plan ENUM('core','home') NOT NULL,
  kind ENUM('paid','included','beta') NOT NULL,
  months SMALLINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL,
  activated_at DATETIME NULL,
  expires_at DATETIME NULL,
  installation_id CHAR(36) NULL UNIQUE,
  credential_hash CHAR(64) NULL,
  code_hash CHAR(64) NOT NULL UNIQUE,
  encrypted_code TEXT NOT NULL,
  revoked TINYINT(1) NOT NULL DEFAULT 0,
  INDEX idx_customer_plan (customer_id, plan),
  INDEX idx_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payments (
  id VARCHAR(191) PRIMARY KEY,
  entitlement_id CHAR(36) NOT NULL,
  paid_at DATETIME NOT NULL,
  CONSTRAINT fk_payment_entitlement FOREIGN KEY (entitlement_id) REFERENCES entitlements(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS inbox (
  id VARCHAR(191) PRIMARY KEY,
  topic VARCHAR(40) NOT NULL,
  payload MEDIUMTEXT NOT NULL,
  received_at DATETIME NOT NULL,
  processed TINYINT(1) NOT NULL DEFAULT 0,
  error VARCHAR(255) NULL,
  INDEX idx_inbox_pending (processed, received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outbox (
  id VARCHAR(191) PRIMARY KEY,
  entitlement_id CHAR(36) NOT NULL,
  email VARCHAR(254) NOT NULL,
  kind VARCHAR(40) NOT NULL,
  created_at DATETIME NOT NULL,
  sent_at DATETIME NULL,
  INDEX idx_outbox_pending (sent_at, created_at),
  CONSTRAINT fk_outbox_entitlement FOREIGN KEY (entitlement_id) REFERENCES entitlements(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS review (
  id VARCHAR(191) PRIMARY KEY,
  reason VARCHAR(500) NOT NULL,
  created_at DATETIME NOT NULL,
  resolved_at DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS settings (
  setting_key VARCHAR(80) PRIMARY KEY,
  setting_value TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS releases (
  version VARCHAR(80) PRIMARY KEY,
  published_at DATETIME NOT NULL,
  sha256 CHAR(64) NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  INDEX idx_release_latest (enabled, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  action_name VARCHAR(60) NOT NULL,
  target VARCHAR(191) NOT NULL,
  occurred_at DATETIME NOT NULL,
  INDEX idx_audit_target (target, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
