USE pharmsync;

-- Add patient accounts while preserving the existing network roles and users.
ALTER TABLE users
  MODIFY role ENUM('retail_chemist','clinic_phc','charity_ngo','patient') NOT NULL,
  MODIFY organization_name VARCHAR(180) NULL,
  MODIFY address VARCHAR(255) NULL,
  MODIFY city VARCHAR(100) NULL,
  MODIFY state VARCHAR(100) NULL;

-- Reservation count remains with the existing batch row.
SET @column_exists = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='medicine_batches' AND column_name='reserved_quantity');
SET @column_sql = IF(@column_exists=0,
  'ALTER TABLE medicine_batches ADD COLUMN reserved_quantity INT UNSIGNED NOT NULL DEFAULT 0 AFTER quantity', 'SELECT 1');
PREPARE column_stmt FROM @column_sql; EXECUTE column_stmt; DEALLOCATE PREPARE column_stmt;

SET @constraint_exists = (SELECT COUNT(*) FROM information_schema.table_constraints
  WHERE table_schema=DATABASE() AND table_name='medicine_batches' AND constraint_name='chk_batches_reserved_quantity');
SET @constraint_sql = IF(@constraint_exists=0,
  'ALTER TABLE medicine_batches ADD CONSTRAINT chk_batches_reserved_quantity CHECK (reserved_quantity <= quantity)', 'SELECT 1');
PREPARE constraint_stmt FROM @constraint_sql; EXECUTE constraint_stmt; DEALLOCATE PREPARE constraint_stmt;

CREATE TABLE IF NOT EXISTS medicine_orders (
  order_id VARCHAR(32) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  batch_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  quantity INT UNSIGNED NOT NULL,
  original_unit_price DECIMAL(12,2) NOT NULL,
  discount_percent TINYINT UNSIGNED NOT NULL DEFAULT 0,
  discounted_unit_price DECIMAL(12,2) NOT NULL,
  total_amount DECIMAL(14,2) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (order_id),
  KEY idx_medicine_orders_user_created (user_id, created_at),
  KEY idx_medicine_orders_node_status (node_id, status, created_at),
  KEY idx_medicine_orders_batch_status (batch_id, status),
  CONSTRAINT fk_medicine_orders_user FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_medicine_orders_node FOREIGN KEY (node_id) REFERENCES pharmacy_nodes(node_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_medicine_orders_batch FOREIGN KEY (batch_id) REFERENCES medicine_batches(batch_id) ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT chk_medicine_orders_qty CHECK (quantity > 0),
  CONSTRAINT chk_medicine_orders_discount CHECK (discount_percent IN (0,30,50)),
  CONSTRAINT chk_medicine_orders_amount CHECK (total_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema=DATABASE() AND table_name='sales' AND column_name='order_id');
SET @column_sql = IF(@column_exists=0,
  'ALTER TABLE sales ADD COLUMN order_id VARCHAR(32) NULL AFTER sale_id', 'SELECT 1');
PREPARE column_stmt FROM @column_sql; EXECUTE column_stmt; DEALLOCATE PREPARE column_stmt;

SET @index_exists = (SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema=DATABASE() AND table_name='sales' AND index_name='uq_sales_order_id');
SET @index_sql = IF(@index_exists=0,
  'CREATE UNIQUE INDEX uq_sales_order_id ON sales(order_id)', 'SELECT 1');
PREPARE index_stmt FROM @index_sql; EXECUTE index_stmt; DEALLOCATE PREPARE index_stmt;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.key_column_usage
  WHERE table_schema=DATABASE() AND table_name='sales' AND constraint_name='fk_sales_order');
SET @fk_sql = IF(@fk_exists=0,
  'ALTER TABLE sales ADD CONSTRAINT fk_sales_order FOREIGN KEY(order_id) REFERENCES medicine_orders(order_id) ON UPDATE CASCADE ON DELETE RESTRICT', 'SELECT 1');
PREPARE fk_stmt FROM @fk_sql; EXECUTE fk_stmt; DEALLOCATE PREPARE fk_stmt;