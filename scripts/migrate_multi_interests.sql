ALTER TABLE users ADD COLUMN IF NOT EXISTS interests varchar(64)[] NOT NULL DEFAULT '{}';

-- Carry each existing single interest over as the first entry of the array.
UPDATE users
   SET interests = ARRAY[interest]::varchar(64)[]
 WHERE interest IS NOT NULL
   AND cardinality(interests) = 0;
