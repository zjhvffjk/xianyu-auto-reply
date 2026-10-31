PUBLISH_BATCH_DDL = '''
CREATE TABLE IF NOT EXISTS xy_publish_batches (
 id VARCHAR(36) PRIMARY KEY, user_id BIGINT NOT NULL,
 mode VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'waiting',
 start_at DATETIME NOT NULL, next_run_at DATETIME NULL, interval_seconds INT NOT NULL,
 account_ids JSON NOT NULL, materials JSON NOT NULL, sync_results JSON NOT NULL,
 cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
 claim_token VARCHAR(36) NULL, lease_until DATETIME NULL, current_log_id BIGINT NULL,
 last_error VARCHAR(500) NULL,
 history_cleared_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 KEY idx_pb_due (status, next_run_at), KEY idx_pb_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
'''
