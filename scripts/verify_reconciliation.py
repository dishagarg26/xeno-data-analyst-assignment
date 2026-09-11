"""
Verification Script for Comm-Log Reconciliation (target_base)
Runs against data/comm_log.db and asserts all step-by-step investigation counts.
"""

import sqlite3
from pathlib import Path

def main():
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / "comm_log.db"

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at expected path: {db_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Step 0: Naive Raw Count (Scope: Merchant 501, Oct 2026, Campaign Type 2)
    step0 = cur.execute("""
        SELECT COUNT(*) 
        FROM communication_log 
        WHERE merchant_id = 501 
          AND communication_type = '2' 
          AND sent_time >= '2026-10-01' AND sent_time < '2026-11-01';
    """).fetchone()[0]

    # Step 1: Campaign Lifecycle Eligibility Filter (creation_status in approved/aborted/resumed/stopped, processing_status = processed)
    step1 = cur.execute("""
        SELECT COUNT(*) 
        FROM communication_log l
        JOIN campaign c ON l.communication_id = c.id
        WHERE l.merchant_id = 501 
          AND l.communication_type = '2'
          AND l.sent_time >= '2026-10-01' AND l.sent_time < '2026-11-01'
          AND c.name LIKE 'Diwali%'
          AND c.creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
          AND c.processing_status = 'processed';
    """).fetchone()[0]

    # Step 2: Delivery Success Filter (delivery_status = 900) -> Final Target Base
    step2 = cur.execute("""
        SELECT COUNT(*) 
        FROM communication_log l
        JOIN campaign c ON l.communication_id = c.id
        WHERE l.merchant_id = 501 
          AND l.communication_type = '2'
          AND l.sent_time >= '2026-10-01' AND l.sent_time < '2026-11-01'
          AND c.name LIKE 'Diwali%'
          AND c.creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
          AND c.processing_status = 'processed'
          AND l.delivery_status = 900;
    """).fetchone()[0]

    # Validation: Global Distinct Customer Deduplication Investigation
    distinct_customers = cur.execute("""
        SELECT COUNT(DISTINCT l.customer_id) 
        FROM communication_log l
        JOIN campaign c ON l.communication_id = c.id
        WHERE l.merchant_id = 501 
          AND l.communication_type = '2'
          AND l.sent_time >= '2026-10-01' AND l.sent_time < '2026-11-01'
          AND c.name LIKE 'Diwali%'
          AND c.creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
          AND c.processing_status = 'processed'
          AND l.delivery_status = 900;
    """).fetchone()[0]

    # Structural Validation Query (Recursive CTE)
    cte_query = """
    WITH RECURSIVE campaign_tree AS (
        SELECT id AS campaign_id, id AS root_campaign_id, creation_status, processing_status, name
        FROM campaign WHERE parent_id IS NULL
        UNION ALL
        SELECT c.id, ct.root_campaign_id, c.creation_status, c.processing_status, c.name
        FROM campaign c JOIN campaign_tree ct ON c.parent_id = ct.campaign_id
    ),
    eligible_campaigns AS (
        SELECT campaign_id, root_campaign_id FROM campaign_tree
        WHERE creation_status IN ('approved', 'aborted', 'resumed', 'stopped')
          AND processing_status = 'processed' AND name LIKE 'Diwali%'
    ),
    chain_metadata AS (
        SELECT root_campaign_id, COUNT(campaign_id) AS chain_depth
        FROM eligible_campaigns GROUP BY root_campaign_id
    ),
    qualifying_attempts AS (
        SELECT l.id AS send_id, ec.root_campaign_id, l.customer_id, cm.chain_depth
        FROM communication_log l
        JOIN eligible_campaigns ec ON l.communication_id = ec.campaign_id
        JOIN chain_metadata cm ON ec.root_campaign_id = cm.root_campaign_id
        WHERE l.merchant_id = 501 AND l.communication_type = '2'
          AND l.sent_time >= '2026-10-01' AND l.sent_time < '2026-11-01'
          AND l.delivery_status = 900
    )
    SELECT 
        COUNT(DISTINCT CASE WHEN chain_depth > 1 THEN root_campaign_id || '-' || customer_id END)
        + COUNT(CASE WHEN chain_depth = 1 THEN send_id END) AS target_base
    FROM qualifying_attempts;
    """
    cte_result = cur.execute(cte_query).fetchone()[0]

    print("=========================================================")
    print("           TARGET BASE RECONCILIATION BRIDGE             ")
    print("=========================================================")
    print(f"Step 0: Naive Raw Count               : {step0}")
    print(f"Step 1: Exclude Unapproved (9004)      : {step1}  (-4 rows)")
    print(f"Step 2: Exclude Soft Failures (1100)   : {step2}  (-4 rows)")
    print("---------------------------------------------------------")
    print(f"RECONCILED TARGET BASE                : {step2}")
    print("=========================================================")
    print(f"Validation: Global DISTINCT Customers : {distinct_customers}  (Undercounts due to C20 re-targeting)")
    print(f"Validation: Structural CTE Result     : {cte_result}")
    print("=========================================================")

    # Assertions to ensure exact reconciliation
    assert step0 == 30, f"Expected step0 = 30, got {step0}"
    assert step1 == 26, f"Expected step1 = 26, got {step1}"
    assert step2 == 22, f"Expected step2 = 22, got {step2}"
    assert distinct_customers == 21, f"Expected distinct_customers = 21, got {distinct_customers}"
    assert cte_result == 22, f"Expected cte_result = 22, got {cte_result}"

    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
    conn.close()

if __name__ == "__main__":
    main()
