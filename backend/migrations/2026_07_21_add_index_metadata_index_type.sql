ALTER TABLE index_metadata
ADD COLUMN index_type VARCHAR(32) NULL
COMMENT 'Milvus 向量索引类型（IVF_FLAT / HNSW / 其他）';

UPDATE index_metadata
SET index_type = 'IVF_FLAT'
WHERE index_type IS NULL;
