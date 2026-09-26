from pydantic import BaseModel, Field

class MedicineExtraction(BaseModel):
    medicineName: str | None = Field(...)
    genericName: str | None = Field(...)
    manufacturer: str | None = Field(...)
    medicineId: str | None = Field(...)
    batchNumber: str | None = Field(...)
    manufacturingDate: str | None = Field(...)
    expiryDate: str | None = Field(...)
    gtin: str | None = Field(...)
    storageCondition: str | None = Field(...)

class RestockRequest(BaseModel):
    medicine_id: str = Field(min_length=1, max_length=32)
    medicine_name: str = Field(min_length=1, max_length=180)
    batch: str | None = Field(default=None, max_length=80)
    batch_number: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    manufacture_date: str
    expiry_date: str
    storage_condition: str = "Unknown"
    batch_status: str = "active"
