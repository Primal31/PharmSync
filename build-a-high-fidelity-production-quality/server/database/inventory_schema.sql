USE pharmsync;

CREATE TABLE IF NOT EXISTS pharmacy_nodes (
  node_id VARCHAR(32) NOT NULL,
  node_name VARCHAR(180) NOT NULL,
  node_type VARCHAR(32) NOT NULL,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(100) NOT NULL,
  address VARCHAR(255) NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  verification_status VARCHAR(32) NOT NULL,
  PRIMARY KEY (node_id),
  KEY idx_pharmacy_nodes_type_city (node_type, city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Product master data; pharmacy-specific batch details stay in medicine_batches.
CREATE TABLE IF NOT EXISTS medicines (
  medicine_id VARCHAR(32) NOT NULL,
  gtin CHAR(14) NULL,
  medicine_name VARCHAR(180) NOT NULL,
  generic_name VARCHAR(180) NULL,
  manufacturer VARCHAR(180) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (medicine_id),
  UNIQUE KEY uq_medicines_gtin (gtin),
  KEY idx_medicines_name (medicine_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS medicine_batches (
  batch_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  batch_number VARCHAR(80) NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 0,
  unit_price_inr DECIMAL(12,2) NOT NULL DEFAULT 0,
  manufacturing_date DATE NOT NULL,
  expiry_date DATE NOT NULL,
  batch_status VARCHAR(32) NOT NULL DEFAULT 'Available',
  PRIMARY KEY (batch_id),
  KEY idx_batches_node_expiry (node_id, expiry_date),
  KEY idx_batches_medicine (medicine_id),
  CONSTRAINT fk_batches_node FOREIGN KEY (node_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS sales (
  sale_id VARCHAR(32) NOT NULL,
  sale_date DATE NOT NULL,
  pharmacy_id VARCHAR(32) NOT NULL,
  batch_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  quantity_sold INT UNSIGNED NOT NULL,
  unit_price_inr DECIMAL(12,2) NOT NULL,
  total_amount_inr DECIMAL(14,2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (sale_id),
  KEY idx_sales_pharmacy_date_batch (pharmacy_id, sale_date, batch_id),
  KEY idx_sales_batch (batch_id),
  CONSTRAINT fk_sales_pharmacy FOREIGN KEY (pharmacy_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_sales_batch FOREIGN KEY (batch_id) REFERENCES medicine_batches(batch_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS clinic_demand (
  demand_id VARCHAR(32) NOT NULL,
  clinic_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  form VARCHAR(80) NOT NULL,
  current_stock INT UNSIGNED NOT NULL DEFAULT 0,
  daily_demand DECIMAL(12,2) NOT NULL DEFAULT 0,
  required_quantity INT UNSIGNED NOT NULL DEFAULT 0,
  shortage_quantity INT UNSIGNED NOT NULL DEFAULT 0,
  priority VARCHAR(32) NOT NULL,
  PRIMARY KEY (demand_id),
  KEY idx_demand_clinic (clinic_id),
  KEY idx_demand_medicine (medicine_id),
  CONSTRAINT fk_demand_clinic FOREIGN KEY (clinic_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS charity_organizations (
  charity_id VARCHAR(32) NOT NULL,
  node_id VARCHAR(32) NOT NULL,
  organization_name VARCHAR(180) NOT NULL,
  city VARCHAR(100) NOT NULL,
  state VARCHAR(100) NOT NULL,
  verification_status VARCHAR(32) NOT NULL,
  service_type VARCHAR(120) NOT NULL,
  contact_email VARCHAR(254) NULL,
  contact_phone VARCHAR(32) NULL,
  PRIMARY KEY (charity_id),
  UNIQUE KEY uq_charity_node (node_id),
  CONSTRAINT fk_charity_node FOREIGN KEY (node_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS transfer_manifests (
  transfer_id VARCHAR(32) NOT NULL,
  transfer_date DATE NOT NULL,
  source_pharmacy_id VARCHAR(32) NOT NULL,
  destination_clinic_id VARCHAR(32) NOT NULL,
  batch_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  quantity INT UNSIGNED NOT NULL,
  status VARCHAR(32) NOT NULL,
  decision_reason TEXT NULL,
  distance_km DECIMAL(10,2) NULL,
  PRIMARY KEY (transfer_id),
  KEY idx_transfer_source_date (source_pharmacy_id, transfer_date),
  KEY idx_transfer_destination_date (destination_clinic_id, transfer_date),
  KEY idx_transfer_batch (batch_id),
  CONSTRAINT fk_transfer_source FOREIGN KEY (source_pharmacy_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_transfer_destination FOREIGN KEY (destination_clinic_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_transfer_batch FOREIGN KEY (batch_id) REFERENCES medicine_batches(batch_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS donations (
  donation_id VARCHAR(32) NOT NULL,
  donation_date DATE NOT NULL,
  donor_pharmacy_id VARCHAR(32) NOT NULL,
  charity_id VARCHAR(32) NOT NULL,
  medicine_id VARCHAR(32) NOT NULL,
  medicine_name VARCHAR(180) NOT NULL,
  quantity INT UNSIGNED NOT NULL,
  status VARCHAR(32) NOT NULL,
  reason TEXT NULL,
  PRIMARY KEY (donation_id),
  KEY idx_donations_date (donation_date),
  KEY idx_donations_charity (charity_id),
  CONSTRAINT fk_donation_pharmacy FOREIGN KEY (donor_pharmacy_id) REFERENCES pharmacy_nodes(node_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_donation_charity FOREIGN KEY (charity_id) REFERENCES charity_organizations(charity_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
  log_id VARCHAR(32) NOT NULL,
  `timestamp` DATETIME NOT NULL,
  agent_name VARCHAR(120) NOT NULL,
  action VARCHAR(80) NOT NULL,
  entity_type VARCHAR(80) NOT NULL,
  entity_id VARCHAR(80) NOT NULL,
  status VARCHAR(32) NOT NULL,
  message TEXT NOT NULL,
  PRIMARY KEY (log_id),
  KEY idx_audit_entity_time (entity_type, entity_id, `timestamp`),
  KEY idx_audit_action_time (action, `timestamp`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS dataset_imports (
  dataset_name VARCHAR(120) NOT NULL,
  sha256 CHAR(64) NOT NULL,
  row_count INT UNSIGNED NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (dataset_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET @fk_exists = (SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND CONSTRAINT_NAME='fk_users_node');
SET @fk_sql = IF(@fk_exists=0,
  'ALTER TABLE users ADD CONSTRAINT fk_users_node FOREIGN KEY (node_id) REFERENCES pharmacy_nodes(node_id) ON UPDATE CASCADE ON DELETE SET NULL',
  'SELECT 1');
PREPARE fk_stmt FROM @fk_sql;
EXECUTE fk_stmt;
DEALLOCATE PREPARE fk_stmt;
