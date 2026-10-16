# Database model (PostgreSQL)

```mermaid
erDiagram
    users ||--o| donors : "has profile"
    users ||--o| ngos : "has profile"
    donors ||--o{ donations : lists
    ngos ||--o{ requests : posts
    ngos ||--o{ donations : "accepts"
    donations ||--o{ matches : "top 5"
    ngos ||--o{ matches : receives
    requests ||--o{ matches : "for need"
    ingest_batches ||--o{ donations : produced
    ingest_batches ||--o{ requests : produced
    ingest_batches ||--o{ rejected_rows : rejected

    users {
        int id PK
        string email UK
        string password_hash
        string role "donor | ngo | admin"
    }
    donors {
        int id PK
        int user_id FK
        string name UK
        string area
        float lat
        float lng
    }
    ngos {
        int id PK
        int user_id FK
        string name UK
        string area
        float lat
        float lng
    }
    donations {
        int id PK
        int donor_id FK
        string food_type
        string category
        float quantity_kg
        datetime expiry_time
        float lat
        float lng
        string area
        string status "listed matched accepted picked_up delivered expired"
        string source "manual sim api upload history"
        int batch_id FK
        int accepted_ngo_id FK
    }
    requests {
        int id PK
        int ngo_id FK
        string category "null = any"
        float quantity_kg
        float fulfilled_kg
        datetime needed_by
        bool standing
    }
    matches {
        int id PK
        int donation_id FK
        int ngo_id FK
        int request_id FK
        int rank
        float score
        float distance_km
        string status "suggested accepted declined"
    }
    ingest_batches {
        int id PK
        string source
        int total_rows
        int accepted_donations
        int accepted_requests
        int rejected_rows
    }
    rejected_rows {
        int id PK
        int batch_id FK
        int row_number
        json raw
        string reason
    }
    events {
        int id PK
        string kind
        string message
    }
    analytics_snapshots {
        int id PK
        json data
    }
    quality_reports {
        int id PK
        json data
    }
```

Other stores: **MongoDB** `raw_ingest` (every incoming row) and `events` (donation.created payloads);
**Delta Lake** tables `donation_history` and `status_events` under `data/delta/`;
**Elasticsearch** indices `fr-donations` and `fr-ngos`.
