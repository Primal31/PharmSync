USE pharmsync;

-- Add the dataset's optional short batch label and pharmacist-confirmed storage condition.
-- Existing batch_number, unit_price_inr, and manufacturing_date columns remain unchanged.
SET @has_batch = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='medicine_batches' AND COLUMN_NAME='batch');
SET @sql = IF(@has_batch=0, 'ALTER TABLE medicine_batches ADD COLUMN batch VARCHAR(80) NULL AFTER medicine_name', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @has_restock_unique = (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='medicine_batches' AND INDEX_NAME='uq_batch_pharmacy_medicine_number');
SET @sql = IF(@has_restock_unique=0, 'ALTER TABLE medicine_batches ADD UNIQUE KEY uq_batch_pharmacy_medicine_number (node_id,medicine_id,batch_number)', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @has_storage = (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='medicine_batches' AND COLUMN_NAME='storage_condition');
SET @sql = IF(@has_storage=0, 'ALTER TABLE medicine_batches ADD COLUMN storage_condition VARCHAR(80) NULL AFTER expiry_date', 'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;