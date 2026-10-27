REFUND_DDL = {
    'xy_refund_approvals': '''CREATE TABLE IF NOT EXISTS xy_refund_approvals (
        id VARCHAR(36) PRIMARY KEY, owner_id BIGINT NOT NULL, actor_id BIGINT NOT NULL,
        account_id VARCHAR(80) NOT NULL, order_no VARCHAR(64) NOT NULL,
        refund_id VARCHAR(64) NOT NULL, amount DECIMAL(12,2) NOT NULL,
        status VARCHAR(32) NOT NULL, detail VARCHAR(300) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_refund_approval (account_id, refund_id), KEY idx_refund_approval_owner (owner_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
    'xy_refund_message_configs': '''CREATE TABLE IF NOT EXISTS xy_refund_message_configs (
        account_id VARCHAR(80) PRIMARY KEY, owner_id BIGINT NOT NULL,
        enabled TINYINT(1) NOT NULL DEFAULT 0, enabled_at DATETIME NULL,
        unshipped_enabled TINYINT(1) NOT NULL DEFAULT 0,
        shipped_enabled TINYINT(1) NOT NULL DEFAULT 0,
        unshipped_content TEXT NOT NULL, shipped_content TEXT NOT NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_refund_config_owner (owner_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
    'xy_refund_message_records': '''CREATE TABLE IF NOT EXISTS xy_refund_message_records (
        id INT AUTO_INCREMENT PRIMARY KEY, owner_id BIGINT NOT NULL,
        account_id VARCHAR(80) NOT NULL, order_no VARCHAR(64) NOT NULL,
        content TEXT NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'processing',
        detail VARCHAR(300) NOT NULL DEFAULT '', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_refund_message_order (account_id, order_no),
        KEY idx_refund_message_owner (owner_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
}
