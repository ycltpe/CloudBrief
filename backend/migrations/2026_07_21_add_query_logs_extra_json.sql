ALTER TABLE query_logs
ADD COLUMN extra_json JSON NULL
COMMENT '级联检索元数据及未来可扩展字段';
