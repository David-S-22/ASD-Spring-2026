# Anomalies Database ERDs

## Conceptual ERD

```mermaid
erDiagram
    TRANSACTIONS ||--o| ANOMALIES : "may have"

    TRANSACTIONS {
        int id
        date date
        string merchant
        string description
        decimal amount
        int category_id
        datetime created_at
        datetime updated_at
    }

    ANOMALIES {
        int id
        int transaction_id
        string agent_reason_suspected
        boolean is_confirmed_by_user
    }
```

## Logical ERD

```mermaid
erDiagram
    TRANSACTIONS ||--o| ANOMALIES : "has at most one"

    TRANSACTIONS {
        int id PK
        datetime date
        string merchant
        string description
        decimal amount
        int category_id
        datetime created_at
        datetime updated_at
    }

    ANOMALIES {
        int id PK
        int transaction_id UK
        string agent_reason_suspected
        boolean is_confirmed_by_user
    }
```

## Physical ERD

```mermaid
erDiagram
    TRANSACTIONS ||--o| ANOMALIES : "transaction_id reference"

    TRANSACTIONS {
        INTEGER id PK "NOT NULL"
        DATETIME date "NOT NULL"
        VARCHAR_200 merchant "NOT NULL"
        VARCHAR_500 description "NOT NULL"
        NUMERIC_12_2 amount "NOT NULL"
        INTEGER category_id "NOT NULL"
        DATETIME created_at "NOT NULL"
        DATETIME updated_at "NOT NULL"
    }

    ANOMALIES {
        INTEGER id PK "NOT NULL"
        INTEGER transaction_id UK "NOT NULL"
        VARCHAR agent_reason_suspected "NOT NULL"
        BOOLEAN is_confirmed_by_user "NULLABLE"
    }
```

The `transactions` table and `anomalies` table are stored in separate databases. Therefore, the relationship between `anomalies.transaction_id` and `transactions.id` is a logical cross-database reference rather than an enforced database foreign key. The `UNIQUE` constraint on `anomalies.transaction_id` ensures that each transaction can have zero or one anomaly.
