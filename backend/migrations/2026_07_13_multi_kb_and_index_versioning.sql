-- 2026_07_13_multi_kb_and_index_versioning.sql
-- Phase 3 2 周 MVP：多知识库支持与索引版本链

-- 1. 为 index_metadata 增加知识库与版本字段
ALTER TABLE index_metadata
    ADD COLUMN kb_id VARCHAR(64) NOT NULL DEFAULT 'default' AFTER id,
    ADD COLUMN version INT NOT NULL DEFAULT 1 AFTER is_active,
    ADD COLUMN parent_id INT NULL AFTER version,
    ADD COLUMN reason VARCHAR(32) NULL AFTER parent_id,
    ADD COLUMN source_changes_json TEXT NULL AFTER reason,
    ADD INDEX idx_index_metadata_kb_id (kb_id),
    ADD INDEX idx_index_metadata_version (version),
    ADD INDEX idx_index_metadata_parent_id (parent_id),
    ADD CONSTRAINT fk_index_metadata_parent_id
        FOREIGN KEY (parent_id) REFERENCES index_metadata(id)
        ON DELETE SET NULL;

-- 2. 新增知识库用户访问权限表
CREATE TABLE IF NOT EXISTS kb_user_access (
    id INT AUTO_INCREMENT PRIMARY KEY,
    kb_id VARCHAR(64) NOT NULL,
    user_id INT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'approved',
    created_by INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uix_kb_user_access_kb_user (kb_id, user_id),
    INDEX idx_kb_user_access_kb_id (kb_id),
    INDEX idx_kb_user_access_user_id (user_id),
    CONSTRAINT fk_kb_user_access_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 回填现有 index_metadata 记录的版本号（按创建时间排序）
SET @row_number = 0;
UPDATE index_metadata
SET version = (@row_number := @row_number + 1)
WHERE kb_id = 'default'
ORDER BY created_at ASC;
