USE pharmsync;

-- Add descriptive master-data columns to the existing step 8 medicines catalog.
SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='medicines' AND COLUMN_NAME='strength');
SET @ddl = IF(@column_exists=0, 'ALTER TABLE medicines ADD COLUMN strength VARCHAR(80) NULL AFTER generic_name', 'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @column_exists = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='medicines' AND COLUMN_NAME='dosage_form');
SET @ddl = IF(@column_exists=0, 'ALTER TABLE medicines ADD COLUMN dosage_form VARCHAR(80) NULL AFTER strength', 'SELECT 1');
PREPARE migration_stmt FROM @ddl;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;
