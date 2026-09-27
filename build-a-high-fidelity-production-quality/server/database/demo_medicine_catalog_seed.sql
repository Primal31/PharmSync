USE pharmsync;

-- Synthetic catalog records for the six PharmSync demo package images.
-- These are product-master mappings only; this seed does not create inventory batches.
-- INSERT IGNORE preserves any existing catalog entry with a colliding medicine ID or GTIN.
INSERT IGNORE INTO medicines
  (medicine_id, gtin, medicine_name, generic_name, strength, dosage_form, manufacturer)
VALUES
  ('DEMO-ATOR10', '08901000000019', 'Atorvastatin 10 mg', 'Atorvastatin', '10 mg', 'Tablet', 'PharmSync Demo'),
  ('DEMO-MET850', '08901000000026', 'Metformin 850 mg', 'Metformin', '850 mg', 'Tablet', 'PharmSync Demo'),
  ('DEMO-OME20', '08901000000033', 'Omeprazole 20 mg', 'Omeprazole', '20 mg', 'Capsule', 'PharmSync Demo'),
  ('PARA-BATCH-2', '08901000000040', 'Paracetamol 500 mg', 'Paracetamol', '500 mg', 'Tablet', 'PharmSync Demo'),
  ('DEMO-IBU200', '08901000000057', 'Ibuprofen 200 mg', 'Ibuprofen', '200 mg', 'Tablet', 'PharmSync Demo'),
  ('AMOX-BATCH-001', '08901000000064', 'Amoxicillin 500 mg', 'Amoxicillin', '500 mg', 'Capsule', 'PharmSync Demo');
