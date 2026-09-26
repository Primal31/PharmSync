# Dataset import map

The importer uses the actual files copied from `PharmSync_datasets.zip` into `server/database/datasets`. It does not rename identifiers or infer a generic batch/sale model.

| Source file | MySQL table | Source columns preserved |
|---|---|---|
| `pharmacy_nodes.csv` | `pharmacy_nodes` | All 9 columns, including `node_id` and `verification_status` |
| `medicine_batches.csv` | `medicine_batches` | All 10 columns; actual dataset uses `batch_id`, `batch_number`, `unit_price_inr`, and `manufacturing_date` (there is no separate `batch` source column) |
| `sales.csv` | `sales` | All 9 columns; `pharmacy_id` is the pharmacy node ID, and there is no `status` source column |
| `clinic_demand.csv` | `clinic_demand` | All 10 columns |
| `charity_organizations.csv` | `charity_organizations` | All 9 columns; actual headers are `organization_name` and `verification_status` |
| `transfer_manifests.csv` | `transfer_manifests` | All 11 columns; actual source name is `transfer_manifests.csv` and distance column is `distance_km` |
| `donations.csv` | `donations` | All 9 columns; actual source file is plural `donations.csv` |
| `audit_logs.csv` | `audit_logs` | All 8 columns, including the source `status` column |

For the inventory table, the displayed “Batch” value is the existing `batch_id`; “Batch number” is `batch_number`. POS and sales always retain the real `batch_id` association. No separate `batch` value is fabricated.

## Existing source relationship repair

The supplied `charity_organizations.csv` includes seven valid charity node IDs (`EXT004` through `EXT010`) that are not present in `pharmacy_nodes.csv`. To preserve all charity records while retaining a single canonical `pharmacy_nodes` table, the importer adds those seven source IDs to `pharmacy_nodes` using the charity rows’ organization name, city, state, and verification status. Address and coordinates remain NULL because the charity CSV does not provide them. The dry-run and import summary report this supplemental mapping.

## Authenticated account linking

`users.node_id` is a nullable string foreign key to `pharmacy_nodes.node_id`. New registration links only when organization name, city, state, and role-compatible node type exactly match an imported node. Existing Step 2 demo user `Ramesh Medicals` does not exactly match a node name in this ZIP (its pharmacy nodes are named `Pharma 01`, `Pharma 02`, etc.), so the importer deliberately leaves its node unset instead of guessing. Review the available nodes, then link that account to the correct node:

```sql
SELECT node_id, node_name, city, state, verification_status
FROM pharmacy_nodes WHERE LOWER(node_type) = 'pharmacy'
ORDER BY city, node_name;

-- Replace Nxxx with the actual node for that organization.
UPDATE users SET node_id = 'Nxxx'
WHERE email = 'ramesh@pharmsync.demo';
```
