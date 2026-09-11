# Comm-Log Send Reconciliation (`target_base`)

**Candidate**: Disha Garg  
**Role**: Data Analyst Intern Drive 2026  
**Target Metric**: `target_base` = **22** (Merchant 501, October 2026, Diwali Campaigns)

---

## 1. Executive Summary

Finance reported a true **`target_base`** of **22** qualifying sends for **Merchant 501** across all **Diwali campaigns** in **October 2026**. Querying all raw send attempt records in `communication_log` yields **30**.

By investigating campaign lifecycle rules, delivery statuses, and retry structures, we reconciled the 8-record discrepancy step-by-step to reproduce Finance's target base of **22**.

---

## 2. Reconciliation Bridge

| Step | Description | Result | Reason |
| :---: | :--- | :---: | :--- |
| **0** | Naive raw count | **30** | Starting point (`communication_log` records for Merchant 501, Oct 2026, `communication_type = '2'`). |
| **1** | Campaign lifecycle eligibility | **26** | Campaign 9004 is excluded by the campaign lifecycle eligibility rule because its `creation_status` is `'approval_awaiting'`. |
| **2** | Successful delivery filter | **22** | Exclude **4** attempts with `delivery_status = 1100` (soft failures). |
| **Final** | **True target_base** | **22** | Matches Finance reported metric. |

---

## 3. Primary Reconciliation Query

This primary query is executable directly against `data/comm_log.db`:

```sql
SELECT 
    COUNT(l.id) AS target_base
FROM communication_log l
JOIN campaign c 
    ON l.communication_id = c.id
WHERE l.merchant_id = 501
  AND l.communication_type = '2'
  AND l.sent_time >= '2026-10-01' 
  AND l.sent_time < '2026-11-01'
  AND c.name LIKE 'Diwali%'
  AND c.creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
  AND c.processing_status = 'processed'
  AND l.delivery_status = 900;
```

---

## 4. Secondary Investigation: Retry Chains

The `campaign` table contains parent-child retry relationships representing campaign retry families:
- **Family A**: `9001 -> 9002 -> 9003` ("Diwali Cart Recovery")
- **Family B**: `9201 -> 9202` ("Diwali Wave 2")
- **Ineligible Branch**: `9004` ("Diwali Cart Recovery - Retry C (pending)")

We investigated these structures to determine whether retry attempts required customer deduplication across retry chains:
- In retry chains, failed attempts (`delivery_status = 1100`) were retried in subsequent campaign iterations until delivered (`delivery_status = 900`).
- **No customer received more than one successful delivery within the same retry family.**
- Therefore, filtering for successful deliveries on eligible campaigns naturally aligns with the retry-family deduplication count without requiring additional manual adjustments.

### Supporting Evidence: Structural Recursive CTE

To validate this behavior, we wrote a recursive CTE that explicitly deduplicates customers within retry families while keeping standalone send events individual:

```sql
WITH RECURSIVE campaign_tree AS (
    SELECT 
        id AS campaign_id,
        id AS root_campaign_id,
        creation_status,
        processing_status,
        name
    FROM campaign
    WHERE parent_id IS NULL

    UNION ALL

    SELECT 
        c.id AS campaign_id,
        ct.root_campaign_id,
        c.creation_status,
        c.processing_status,
        c.name
    FROM campaign c
    JOIN campaign_tree ct ON c.parent_id = ct.campaign_id
),
eligible_campaigns AS (
    SELECT 
        campaign_id,
        root_campaign_id
    FROM campaign_tree
    WHERE creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
      AND processing_status = 'processed'
      AND name LIKE 'Diwali%'
),
chain_metadata AS (
    SELECT 
        root_campaign_id,
        COUNT(campaign_id) AS chain_depth
    FROM eligible_campaigns
    GROUP BY root_campaign_id
),
qualifying_attempts AS (
    SELECT 
        l.id AS send_id,
        ec.root_campaign_id,
        l.customer_id,
        cm.chain_depth
    FROM communication_log l
    JOIN eligible_campaigns ec ON l.communication_id = ec.campaign_id
    JOIN chain_metadata cm ON ec.root_campaign_id = cm.root_campaign_id
    WHERE l.merchant_id = 501
      AND l.communication_type = '2'
      AND l.sent_time >= '2026-10-01' AND l.sent_time < '2026-11-01'
      AND l.delivery_status = 900
)
SELECT 
    COUNT(DISTINCT CASE WHEN chain_depth > 1 THEN root_campaign_id || '-' || customer_id END)
    + COUNT(CASE WHEN chain_depth = 1 THEN send_id END) AS target_base
FROM qualifying_attempts;
```

This structural query confirms the identical result of **`target_base = 22`**.

---

## 5. Secondary Investigation: Customer Deduplication

During analysis, we tested a global customer deduplication query:

```sql
SELECT COUNT(DISTINCT customer_id) -- Yields 21 (INCORRECT)
```

- **Why 21 is incorrect**: Customer `C20` was legitimately targeted and successfully delivered **twice** (on `2026-10-10` and `2026-10-20`) under Standalone Campaign `9101` ("Diwali Flash Sale - Standalone").
- Standalone campaigns treat each send event as an independent marketing communication. Applying global customer deduplication collapses these two valid send events into one, undercounting the target base.
- Because `target_base` measures qualifying send events rather than globally unique customers, the correct result remains **22**.

---

## 6. Data Surprises & Analytical Insights

> Campaign `9004` had four successfully delivered send records even though its creation status was still `'approval_awaiting'`. This made the campaign lifecycle status an important eligibility condition when reconciling Finance's number.

---

## 7. Repository Structure

```text
xeno-data-analyst-assignment/
├── README.md                      # Analytical investigation report & reconciliation bridge
├── .gitignore                     # Git ignore rules
├── data/
│   ├── campaign.csv               # Campaign metadata CSV
│   ├── communication_log.csv      # Send attempt logs CSV
│   └── comm_log.db                # SQLite database
├── sql/
│   └── reconciliation_query.sql   # Reconciliation SQL queries
└── scripts/
    └── verify_reconciliation.py   # Python verification script
```

---

## 8. How to Run / Reproduce Results

```bash
# Execute SQL queries directly against SQLite database
sqlite3 data/comm_log.db < sql/reconciliation_query.sql

# Execute Python verification script
python scripts/verify_reconciliation.py
```
