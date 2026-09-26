USE pharmsync;

-- Product master data is stored separately from pharmacy-specific batches.
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
