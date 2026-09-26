USE pharmsync;

-- medicine_batches.batch_status already has capacity for Step 5 states.
-- Add the covering index needed for per-pharmacy, trailing-window velocity aggregation.
SET @idx_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='sales' AND index_name='idx_sales_pharmacy_date_batch'
);
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_sales_pharmacy_date_batch ON sales(pharmacy_id,sale_date,batch_id)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;

SET @idx_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='medicine_batches' AND index_name='idx_batches_status'
);
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_batches_status ON medicine_batches(batch_status)',
  'SELECT 1');
PREPARE idx_stmt FROM @idx_sql;
EXECUTE idx_stmt;
DEALLOCATE PREPARE idx_stmt;