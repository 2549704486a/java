-- Existing environments need this key so automatic metric refreshes update one snapshot.
ALTER TABLE `campaign_effect_metric`
  ADD UNIQUE KEY `uk_campaign_effect_identity` (`activity_id`, `metric_name`, `source_ref`);
