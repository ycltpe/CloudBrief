ALTER TABLE index_metadata
ADD COLUMN shadow_collection_name VARCHAR(255) NULL
COMMENT 'Shadow 索引对应的 Milvus collection 名称';

ALTER TABLE index_metadata
ADD COLUMN shadow_index_type VARCHAR(32) NULL
COMMENT 'Shadow 索引的算法类型（HNSW / IVF_FLAT 等）';

UPDATE index_metadata
SET shadow_index_type = 'HNSW'
WHERE shadow_index_type IS NULL AND shadow_collection_name IS NOT NULL;
