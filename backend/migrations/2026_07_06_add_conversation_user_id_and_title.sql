-- Migration: add user_id and title to conversations table
-- Date: 2026-07-06
-- Applies: knowledgeAgents backend MySQL

ALTER TABLE conversations
    ADD COLUMN user_id INT NULL AFTER id,
    ADD COLUMN title VARCHAR(200) NULL AFTER user_id,
    ADD INDEX idx_conversations_user_id (user_id),
    ADD CONSTRAINT fk_conversations_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL;
