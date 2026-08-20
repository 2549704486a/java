USE `budou`;

SET @award_id = 6;
SET @target_split_count = 100;
SET @total_inventory = (
  SELECT inventory
  FROM award_config
  WHERE awardId = @award_id
);

SET SESSION cte_max_recursion_depth = GREATEST(@target_split_count + 10, 1000);

DELETE FROM award_inventory_split
WHERE awardId = @award_id;

INSERT INTO award_inventory_split (splitId, awardId, inventory)
WITH RECURSIVE seq AS (
  SELECT 1 AS n
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < @target_split_count
)
SELECT
  n AS splitId,
  @award_id AS awardId,
  FLOOR(@total_inventory / @target_split_count)
    + CASE WHEN n <= MOD(@total_inventory, @target_split_count) THEN 1 ELSE 0 END AS inventory
FROM seq;
