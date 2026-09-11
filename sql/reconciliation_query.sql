-- =============================================================================
-- Xeno Data Analyst Take-Home Assignment: Target Base Reconciliation SQL
-- Merchant: 501 | Period: October 2026 | Scope: Diwali Campaigns
-- Expected Finance Target Base: 22
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. PRIMARY RECONCILIATION QUERY (Definitive Calculation)
-- Directly filters communication logs by merchant, period, campaign eligibility,
-- campaign scope, and successful delivery status.
-- -----------------------------------------------------------------------------
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


-- -----------------------------------------------------------------------------
-- 2. SECONDARY STRUCTURAL INVESTIGATION QUERY (Recursive CTE / Retry-Chain Aware)
-- Used during analysis to model parent-child retry chains (9001->9002->9003)
-- and verify whether retries require distinct customer deduplication.
-- Confirms that retry-chain customer deduplication yields the identical 22 count.
-- -----------------------------------------------------------------------------
WITH RECURSIVE campaign_tree AS (
    -- Anchor: Root campaigns (parent_id IS NULL)
    SELECT 
        id AS campaign_id,
        id AS root_campaign_id,
        creation_status,
        processing_status,
        name
    FROM campaign
    WHERE parent_id IS NULL

    UNION ALL

    -- Recursive: Link retry child campaigns to root
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
    -- Retry chains (chain_depth > 1): Deduplicate customer per root retry family
    COUNT(DISTINCT CASE WHEN chain_depth > 1 THEN root_campaign_id || '-' || customer_id END)
    -- Standalone campaigns (chain_depth = 1): Count every delivered send event individually
    + COUNT(CASE WHEN chain_depth = 1 THEN send_id END) AS target_base
FROM qualifying_attempts;
