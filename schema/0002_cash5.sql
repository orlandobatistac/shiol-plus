-- Register NC Cash 5 without activating it before code/backfill verification.
INSERT OR IGNORE INTO lotteries
    (id, name, draw_days, white_ball_count, white_ball_max,
     extra_ball_name, extra_ball_max, active)
VALUES
    ('cash5', 'NC Cash 5', 'sun,mon,tue,wed,thu,fri,sat', 5, 43, '', 0, 0);

