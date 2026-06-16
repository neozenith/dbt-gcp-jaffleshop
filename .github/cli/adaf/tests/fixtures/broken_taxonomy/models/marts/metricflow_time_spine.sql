-- Genuine false positive: a generated time spine has no natural grain key or consumer contract.
-- MD-01 + MD-02 are suppressed for this model in adaf.yml.
select cast('2020-01-01' as date) as date_day
