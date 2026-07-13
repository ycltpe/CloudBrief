-- Migration: add index_task_steps table for persistent index build logs
-- Date: 2026-07-11
-- Applies: knowledgeAgents backend MySQL

CREATE TABLE IF NOT EXISTS index_task_steps (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    step_name VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL,
    duration_ms INT NULL,
    log TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uix_index_task_steps_task_step (task_id, step_name),
    KEY idx_index_task_steps_task_updated (task_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
