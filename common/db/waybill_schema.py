WAYBILL_DDL = {
    'xy_waybill_authorizations': '''CREATE TABLE IF NOT EXISTS xy_waybill_authorizations (
        account_pk BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, app_key VARCHAR(120) NOT NULL,
        platform_fingerprint VARCHAR(64) NOT NULL, token_hash VARCHAR(64) NOT NULL,
        token_ciphertext TEXT NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pending',
        expires_at DATETIME NOT NULL, mall_user_id VARCHAR(40) NULL, shop_name VARCHAR(200) NOT NULL DEFAULT '',
        authorized_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_waybill_auth_token (token_hash), UNIQUE KEY uk_waybill_authorized_shop (app_key, mall_user_id),
        KEY idx_waybill_auth_owner (owner_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
    'xy_waybill_platform': '''CREATE TABLE IF NOT EXISTS xy_waybill_platform (
        id INT PRIMARY KEY, app_key VARCHAR(120) NOT NULL,
        credentials_ciphertext TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
    'xy_waybill_connections': '''CREATE TABLE IF NOT EXISTS xy_waybill_connections (
        account_pk BIGINT PRIMARY KEY, owner_id BIGINT NOT NULL, app_key VARCHAR(120) NOT NULL DEFAULT '',
        credentials_ciphertext TEXT NOT NULL, login_user VARCHAR(200) NOT NULL DEFAULT '',
        mall_user_id VARCHAR(40) NOT NULL DEFAULT '', verified_at DATETIME NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_waybill_connection_owner (owner_id), UNIQUE KEY uk_waybill_remote_shop (app_key, mall_user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
    'xy_waybill_records': '''CREATE TABLE IF NOT EXISTS xy_waybill_records (
        id VARCHAR(36) PRIMARY KEY, owner_id BIGINT NOT NULL, account_pk BIGINT NOT NULL,
        order_no VARCHAR(64) NOT NULL, remote_tid VARCHAR(120) NOT NULL,
        status VARCHAR(32) NOT NULL, detail VARCHAR(300) NOT NULL DEFAULT '',
        recipient_ciphertext TEXT NOT NULL,
        source_hash VARCHAR(64) NOT NULL,
        template_id VARCHAR(80) NOT NULL DEFAULT '', carrier VARCHAR(120) NOT NULL DEFAULT '',
        waybill_no VARCHAR(80) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_waybill_account_order (account_pk, order_no), UNIQUE KEY uk_waybill_remote_tid (remote_tid),
        KEY idx_waybill_owner (owner_id), KEY idx_waybill_account (account_pk)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci''',
}
