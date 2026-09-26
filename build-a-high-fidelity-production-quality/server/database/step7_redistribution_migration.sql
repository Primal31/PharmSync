USE pharmsync;

-- Reuse transfer_manifests as the transfer_receipt store. The new fields connect
-- requested transfers back to the exact imported clinic_demand row and stable match.
SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND column_name='demand_id');
SET @col_sql = IF(@col_exists=0,
  'ALTER TABLE transfer_manifests ADD COLUMN demand_id VARCHAR(32) NULL AFTER batch_id', 'SELECT 1');
PREPARE col_stmt FROM @col_sql; EXECUTE col_stmt; DEALLOCATE PREPARE col_stmt;

SET @col_exists = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND column_name='match_id');
SET @col_sql = IF(@col_exists=0,
  'ALTER TABLE transfer_manifests ADD COLUMN match_id VARCHAR(32) NULL AFTER transfer_id', 'SELECT 1');
PREPARE col_stmt FROM @col_sql; EXECUTE col_stmt; DEALLOCATE PREPARE col_stmt;

SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND index_name='uq_transfer_match_id');
SET @idx_sql = IF(@idx_exists=0,
  'CREATE UNIQUE INDEX uq_transfer_match_id ON transfer_manifests(match_id)', 'SELECT 1');
PREPARE idx_stmt FROM @idx_sql; EXECUTE idx_stmt; DEALLOCATE PREPARE idx_stmt;

SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND index_name='idx_transfer_demand_status');
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_transfer_demand_status ON transfer_manifests(demand_id,status)', 'SELECT 1');
PREPARE idx_stmt FROM @idx_sql; EXECUTE idx_stmt; DEALLOCATE PREPARE idx_stmt;

SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND index_name='idx_transfer_destination_status');
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_transfer_destination_status ON transfer_manifests(destination_clinic_id,status)', 'SELECT 1');
PREPARE idx_stmt FROM @idx_sql; EXECUTE idx_stmt; DEALLOCATE PREPARE idx_stmt;

SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='medicine_batches' AND index_name='idx_batches_network_supply');
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_batches_network_supply ON medicine_batches(medicine_id,node_id,expiry_date,batch_status)', 'SELECT 1');
PREPARE idx_stmt FROM @idx_sql; EXECUTE idx_stmt; DEALLOCATE PREPARE idx_stmt;

SET @idx_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='clinic_demand' AND index_name='idx_demand_network_match');
SET @idx_sql = IF(@idx_exists=0,
  'CREATE INDEX idx_demand_network_match ON clinic_demand(medicine_id,clinic_id,shortage_quantity,priority)', 'SELECT 1');
PREPARE idx_stmt FROM @idx_sql; EXECUTE idx_stmt; DEALLOCATE PREPARE idx_stmt;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.key_column_usage
  WHERE table_schema=DATABASE() AND table_name='transfer_manifests' AND constraint_name='fk_transfer_demand');
SET @fk_sql = IF(@fk_exists=0,
  'ALTER TABLE transfer_manifests ADD CONSTRAINT fk_transfer_demand FOREIGN KEY(demand_id) REFERENCES clinic_demand(demand_id) ON UPDATE CASCADE ON DELETE RESTRICT', 'SELECT 1');
PREPARE fk_stmt FROM @fk_sql; EXECUTE fk_stmt; DEALLOCATE PREPARE fk_stmt;