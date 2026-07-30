INSERT OR REPLACE INTO jackpots
  (lottery_id,amount,cash_value,source,last_status,last_success_at,last_attempt_at)
VALUES
  ('powerball',457000000,205000000,'fixture','ok',datetime('now'),datetime('now'));

INSERT INTO draws (lottery_id,draw_date,n1,n2,n3,n4,n5,extra,source) VALUES
  ('powerball','2026-07-01',1,2,3,4,5,6,'fixture'),
  ('powerball','2026-07-08',12,29,37,43,55,18,'fixture');

INSERT INTO cycles (lottery_id,draw_date,status,tickets_total,strategies_run) VALUES
  ('powerball','2026-07-01','evaluated',160,8),
  ('powerball','2026-07-08','evaluated',160,8),
  ('powerball','2026-07-11','generated',160,8);

INSERT INTO strategy_stats
  (cycle_id,strategy_id,lottery_id,draw_date,tickets_count,matches_3,matches_4,
   matches_5,matches_jackpot,total_prize,roi,weight_before,weight_after)
SELECT c.id, s.id, 'powerball', c.draw_date, 20, 0, 0, 0, 0,
       CASE
         WHEN c.draw_date='2026-07-01' AND s.id='hybrid_ensemble' THEN 12
         WHEN c.draw_date='2026-07-01' AND s.id='cooccurrence' THEN 8
         WHEN c.draw_date='2026-07-08' THEN 4
         ELSE 0
       END,
       CASE
         WHEN c.draw_date='2026-07-01' AND s.id='hybrid_ensemble' THEN -0.7
         WHEN c.draw_date='2026-07-01' AND s.id='cooccurrence' THEN -0.8
         WHEN c.draw_date='2026-07-08' THEN -0.9
         ELSE -1
       END,
       1.0, 0.9
FROM cycles c
CROSS JOIN strategies s
WHERE c.lottery_id='powerball' AND c.status='evaluated' AND s.lottery_id='powerball';

WITH RECURSIVE positions(n) AS (
  SELECT 1 UNION ALL SELECT n+1 FROM positions WHERE n<20
)
INSERT INTO tickets
  (cycle_id,strategy_id,lottery_id,draw_date,n1,n2,n3,n4,n5,extra,confidence,
   matches_white,matches_extra,prize_level,prize_amount,evaluated)
SELECT c.id, s.id, 'powerball', c.draw_date,
       n, n+10, n+20, n+30, n+40, ((n-1)%26)+1,
       CASE s.id
         WHEN 'hybrid_ensemble' THEN 0.87
         WHEN 'xgboost_ml' THEN 0.82
         ELSE 0.7
       END,
       CASE WHEN n=1 THEN 1 ELSE 0 END,
       CASE WHEN n=1 THEN 1 ELSE 0 END,
       CASE WHEN n=1 THEN 'match1+pb' ELSE 'no_prize' END,
       CASE WHEN n=1 THEN 4 ELSE 0 END,
       1
FROM cycles c
CROSS JOIN strategies s
CROSS JOIN positions
WHERE c.lottery_id='powerball' AND c.draw_date='2026-07-08'
  AND s.lottery_id='powerball';

WITH RECURSIVE positions(n) AS (
  SELECT 1 UNION ALL SELECT n+1 FROM positions WHERE n<20
)
INSERT INTO tickets
  (cycle_id,strategy_id,lottery_id,draw_date,n1,n2,n3,n4,n5,extra,confidence,evaluated)
SELECT c.id, s.id, 'powerball', c.draw_date,
       n, n+10, n+20, n+30, n+40, ((n-1)%26)+1,
       CASE s.id
         WHEN 'hybrid_ensemble' THEN 0.87
         WHEN 'xgboost_ml' THEN 0.82
         WHEN 'random_baseline' THEN 0.5
         ELSE 0.7
       END,
       0
FROM cycles c
CROSS JOIN strategies s
CROSS JOIN positions
WHERE c.lottery_id='powerball' AND c.draw_date='2026-07-11'
  AND s.lottery_id='powerball';
