const JSON_HEADERS = {
  'Content-Type': 'application/json; charset=utf-8',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
};

const TICKET_COSTS = {
  powerball: 2,
  mega_millions: 2,
  cash5: 1,
  pick3: 1,
  pick4: 1,
};

// Equivalent evidence strength for the empirical-Bayes ranking adjustment.
const RANKING_PRIOR_DRAWS = 20;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function rounded(value, digits = 4) {
  const factor = 10 ** digits;
  return Math.round(number(value) * factor) / factor;
}

function coverage(available, expected) {
  return expected > 0 ? rounded(available / expected, 4) : 0;
}

function lifetimeRoi(totalWon, evaluatedCombinations, ticketCost) {
  const totalCost = evaluatedCombinations * ticketCost;
  return totalCost > 0 ? rounded((totalWon - totalCost) / totalCost, 4) : null;
}

function parsePagination(url, { defaultLimit = 10, maxLimit = 50 } = {}) {
  const limitRaw = url.searchParams.get('limit');
  const offsetRaw = url.searchParams.get('offset');
  const validInteger = value => /^(0|[1-9]\d*)$/.test(value);

  if (limitRaw !== null && (!validInteger(limitRaw) || Number(limitRaw) < 1 || Number(limitRaw) > maxLimit)) {
    return { error: `limit must be an integer between 1 and ${maxLimit}` };
  }
  if (offsetRaw !== null && (!validInteger(offsetRaw) || Number(offsetRaw) > 100000)) {
    return { error: 'offset must be an integer between 0 and 100000' };
  }

  return {
    limit: limitRaw === null ? defaultLimit : Number(limitRaw),
    offset: offsetRaw === null ? 0 : Number(offsetRaw),
  };
}

function validDrawDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function jackpotPayload(row) {
  if (!row || row.amount == null) return { found: false };
  const staleAfterMs = 5 * 24 * 60 * 60 * 1000;
  const lastSuccessMs = row.last_success_at ? new Date(row.last_success_at).getTime() : NaN;
  const staleByTime = !Number.isFinite(lastSuccessMs)
    || Date.now() - lastSuccessMs > staleAfterMs;
  return {
    found: true,
    amount: number(row.amount),
    cash_value: row.cash_value == null ? null : number(row.cash_value),
    source: row.source,
    stale: row.last_status !== 'ok' || staleByTime,
    last_success_at: row.last_success_at || null,
  };
}

function gamePayload(game) {
  return {
    id: game.id,
    name: game.name,
    draw_days: game.draw_days,
    white_ball_count: number(game.white_ball_count),
    white_ball_max: number(game.white_ball_max),
    extra_ball_name: game.extra_ball_name,
    extra_ball_max: number(game.extra_ball_max),
    active: game.active != null ? Boolean(game.active) : true,
    ticket_cost: TICKET_COSTS[game.id] || 1,
    game_type: game.game_type || 'lotto',
    jurisdiction: game.jurisdiction || 'national',
  };
}

function drawPayload(row) {
  if (!row || !row.draw_date) return null;
  const numbers = [row.n1, row.n2, row.n3, row.n4, row.n5]
    .filter(n => n !== null && n !== undefined)
    .map(number);
  return {
    draw_date: row.draw_date,
    draw_number: row.draw_number != null ? number(row.draw_number) : 1,
    numbers,
    extra: row.extra == null ? null : number(row.extra),
  };
}

async function loadGame(db, lotteryId) {
  return db.prepare(`
    SELECT id, name, draw_days, white_ball_count, white_ball_max,
           extra_ball_name, extra_ball_max, active, game_type, jurisdiction
    FROM lotteries WHERE id=? AND active=1
  `).bind(lotteryId).first();
}

async function overview(url, env, game) {
  const lotteryId = game.id;
  const ticketCost = TICKET_COSTS[lotteryId];
  const [historyResult, topResult, latestResult, nextResult, detailResult, jackpotResult] = await env.DB.batch([
    env.DB.prepare(`
      SELECT COUNT(DISTINCT draw_date) AS evaluated_draws,
             COALESCE(SUM(tickets_count),0) AS evaluated_combinations,
             COALESCE(SUM(total_prize),0) AS total_won
      FROM strategy_stats WHERE lottery_id=?
    `).bind(lotteryId),
    env.DB.prepare(`
      SELECT ss.strategy_id, s.name,
             SUM(ss.total_prize) AS total_won,
             SUM(ss.tickets_count) AS evaluated_combinations,
             COUNT(*) AS evaluated_draws,
             CASE WHEN SUM(ss.tickets_count)>0
               THEN (SUM(ss.total_prize) - SUM(ss.tickets_count) * ?)
                    / (SUM(ss.tickets_count) * ?)
               ELSE NULL END AS lifetime_roi
      FROM strategy_stats ss
      JOIN strategies s ON s.id=ss.strategy_id
      WHERE ss.lottery_id=?
      GROUP BY ss.strategy_id, s.name
      ORDER BY total_won DESC, lifetime_roi DESC, ss.strategy_id ASC
      LIMIT 1
    `).bind(ticketCost, ticketCost, lotteryId),
    env.DB.prepare(`
      SELECT c.draw_date, d.n1, d.n2, d.n3, d.n4, d.n5, d.extra
      FROM cycles c
      JOIN draws d ON d.lottery_id=c.lottery_id AND d.draw_date=c.draw_date
      WHERE c.lottery_id=? AND c.status='evaluated'
      ORDER BY c.draw_date DESC LIMIT 1
    `).bind(lotteryId),
    env.DB.prepare(`
      SELECT c.id, c.draw_date, c.status, c.tickets_total,
             COUNT(t.id) AS available_combinations
      FROM cycles c
      LEFT JOIN tickets t ON t.cycle_id=c.id AND t.evaluated=0
      WHERE c.lottery_id=? AND c.status='generated'
      GROUP BY c.id, c.draw_date, c.status, c.tickets_total
      ORDER BY c.draw_date DESC LIMIT 1
    `).bind(lotteryId),
    env.DB.prepare(`
      SELECT COUNT(*) AS available_combinations,
             COALESCE(SUM(CASE WHEN prize_amount>0 THEN 1 ELSE 0 END),0) AS covered_winning_combinations
      FROM tickets WHERE lottery_id=? AND evaluated=1
    `).bind(lotteryId),
    env.DB.prepare(`
      SELECT amount, cash_value, source, last_status, last_success_at
      FROM jackpots WHERE lottery_id=?
    `).bind(lotteryId),
  ]);

  const history = historyResult.results[0] || {};
  const top = topResult.results[0] || null;
  const latest = latestResult.results[0] || null;
  const next = nextResult.results[0] || null;
  const detail = detailResult.results[0] || {};
  const totalWon = number(history.total_won);
  const evaluatedCombinations = number(history.evaluated_combinations);
  const availableCombinations = number(detail.available_combinations);
  const totalCost = evaluatedCombinations * ticketCost;

  return json({
    game: gamePayload(game),
    jackpot: jackpotPayload(jackpotResult.results[0]),
    next_draw: next ? {
      found: true,
      draw_date: next.draw_date,
      status: next.status,
      expected_combinations: number(next.tickets_total),
      available_combinations: number(next.available_combinations),
    } : { found: false },
    last_result: drawPayload(latest),
    performance: {
      evaluated_draws: number(history.evaluated_draws),
      evaluated_combinations: evaluatedCombinations,
      total_won: totalWon,
      total_cost: totalCost,
      lifetime_roi: lifetimeRoi(totalWon, evaluatedCombinations, ticketCost),
    },
    detail_coverage: {
      expected_combinations: evaluatedCombinations,
      available_combinations: availableCombinations,
      ratio: coverage(availableCombinations, evaluatedCombinations),
      covered_winning_combinations: number(detail.covered_winning_combinations),
    },
    top_strategy: top ? {
      strategy_id: top.strategy_id,
      name: top.name,
      total_won: number(top.total_won),
      evaluated_combinations: number(top.evaluated_combinations),
      evaluated_draws: number(top.evaluated_draws),
      lifetime_roi: rounded(top.lifetime_roi),
    } : null,
  });
}

async function analyses(url, env, game) {
  const pagination = parsePagination(url);
  if (pagination.error) return json({ error: pagination.error }, 400);
  const { limit, offset } = pagination;
  const lotteryId = game.id;
  const ticketCost = TICKET_COSTS[lotteryId];

  const [countResult, rowsResult] = await env.DB.batch([
    env.DB.prepare(`
      SELECT COUNT(DISTINCT ss.cycle_id) AS total
      FROM strategy_stats ss
      JOIN cycles c ON c.id=ss.cycle_id AND c.status='evaluated'
      WHERE ss.lottery_id=?
    `).bind(lotteryId),
    env.DB.prepare(`
      WITH stat_summary AS (
        SELECT cycle_id, draw_date,
               SUM(tickets_count) AS evaluated_combinations,
               SUM(total_prize) AS total_won
        FROM strategy_stats WHERE lottery_id=?
        GROUP BY cycle_id, draw_date
      ),
      ticket_summary AS (
        SELECT cycle_id, COUNT(*) AS available_combinations,
               SUM(CASE WHEN prize_amount>0 THEN 1 ELSE 0 END) AS winning_combinations,
               MAX(matches_white * 2 + matches_extra) AS best_match_score
        FROM tickets WHERE lottery_id=? AND evaluated=1
        GROUP BY cycle_id
      ),
      ranked_strategies AS (
        SELECT cycle_id, strategy_id, total_prize, roi,
               ROW_NUMBER() OVER (
                 PARTITION BY cycle_id
                 ORDER BY total_prize DESC, roi DESC, strategy_id ASC
               ) AS strategy_rank
        FROM strategy_stats WHERE lottery_id=?
      )
      SELECT ss.cycle_id, ss.draw_date, ss.evaluated_combinations, ss.total_won,
             d.n1, d.n2, d.n3, d.n4, d.n5, d.extra,
             COALESCE(ts.available_combinations,0) AS available_combinations,
             COALESCE(ts.winning_combinations,0) AS winning_combinations,
             ts.best_match_score,
             rs.strategy_id AS best_strategy_id,
             rs.total_prize AS best_strategy_total_won,
             rs.roi AS best_strategy_roi,
             s.name AS best_strategy_name
      FROM stat_summary ss
      JOIN cycles c ON c.id=ss.cycle_id AND c.status='evaluated'
      JOIN draws d ON d.lottery_id=? AND d.draw_date=ss.draw_date
      LEFT JOIN ticket_summary ts ON ts.cycle_id=ss.cycle_id
      LEFT JOIN ranked_strategies rs ON rs.cycle_id=ss.cycle_id AND rs.strategy_rank=1
      LEFT JOIN strategies s ON s.id=rs.strategy_id
      ORDER BY ss.draw_date DESC
      LIMIT ? OFFSET ?
    `).bind(lotteryId, lotteryId, lotteryId, lotteryId, limit, offset),
  ]);

  const total = number(countResult.results[0]?.total);
  const items = rowsResult.results.map(row => {
    const expected = number(row.evaluated_combinations);
    const available = number(row.available_combinations);
    const detailRatio = coverage(available, expected);
    const totalWon = number(row.total_won);
    return {
      cycle_id: number(row.cycle_id),
      draw: drawPayload(row),
      total_won: totalWon,
      total_cost: expected * ticketCost,
      roi: lifetimeRoi(totalWon, expected, ticketCost),
      evaluated_combinations: expected,
      combinations_available: available > 0,
      detail_coverage: detailRatio,
      winning_combinations: detailRatio === 1 ? number(row.winning_combinations) : null,
      best_match: detailRatio === 1 ? {
        white: Math.floor(number(row.best_match_score) / 2),
        extra: number(row.best_match_score) % 2,
      } : null,
      best_strategy: row.best_strategy_id ? {
        strategy_id: row.best_strategy_id,
        name: row.best_strategy_name,
        total_won: number(row.best_strategy_total_won),
        roi: rounded(row.best_strategy_roi),
      } : null,
    };
  });

  return json({
    game: gamePayload(game),
    pagination: { limit, offset, total, has_more: offset + items.length < total },
    items,
  });
}

async function analysisDetail(drawDate, env, game) {
  if (!validDrawDate(drawDate)) return json({ error: 'draw date must use YYYY-MM-DD' }, 400);
  const lotteryId = game.id;
  const ticketCost = TICKET_COSTS[lotteryId];
  const cycle = await env.DB.prepare(`
    SELECT c.id, c.draw_date, c.status,
           d.n1, d.n2, d.n3, d.n4, d.n5, d.extra
    FROM cycles c
    JOIN draws d ON d.lottery_id=c.lottery_id AND d.draw_date=c.draw_date
    WHERE c.lottery_id=? AND c.draw_date=? AND c.status='evaluated'
    LIMIT 1
  `).bind(lotteryId, drawDate).first();
  if (!cycle) return json({ error: 'evaluated analysis not found' }, 404);

  const [strategiesResult, combinationsResult, distributionResult] = await env.DB.batch([
    env.DB.prepare(`
      WITH ticket_detail AS (
        SELECT strategy_id, COUNT(*) AS available_combinations,
               SUM(CASE WHEN prize_amount>0 THEN 1 ELSE 0 END) AS winning_combinations,
               MAX(matches_white * 2 + matches_extra) AS best_match_score
        FROM tickets WHERE cycle_id=? AND evaluated=1
        GROUP BY strategy_id
      )
      SELECT ss.strategy_id, s.name, s.description,
             ss.tickets_count, ss.matches_3, ss.matches_4, ss.matches_5,
             ss.total_prize, ss.roi, ss.weight_before, ss.weight_after,
             COALESCE(td.available_combinations,0) AS available_combinations,
             COALESCE(td.winning_combinations,0) AS winning_combinations,
             td.best_match_score
      FROM strategy_stats ss
      JOIN strategies s ON s.id=ss.strategy_id
      LEFT JOIN ticket_detail td ON td.strategy_id=ss.strategy_id
      WHERE ss.cycle_id=?
      ORDER BY ss.total_prize DESC, ss.roi DESC, ss.strategy_id ASC
    `).bind(cycle.id, cycle.id),
    env.DB.prepare(`
      SELECT t.id, t.strategy_id, s.name AS strategy_name,
             t.n1, t.n2, t.n3, t.n4, t.n5, t.extra, t.confidence,
             t.matches_white, t.matches_extra, t.prize_level, t.prize_amount,
             ROW_NUMBER() OVER (
               PARTITION BY t.strategy_id ORDER BY t.confidence DESC, t.id ASC
             ) AS strategy_position
      FROM tickets t
      JOIN strategies s ON s.id=t.strategy_id
      WHERE t.cycle_id=? AND t.evaluated=1
      ORDER BY t.strategy_id ASC, strategy_position ASC
    `).bind(cycle.id),
    env.DB.prepare(`
      SELECT matches_white, matches_extra, prize_level,
             COUNT(*) AS combinations,
             COALESCE(SUM(prize_amount),0) AS total_won
      FROM tickets WHERE cycle_id=? AND evaluated=1
      GROUP BY matches_white, matches_extra, prize_level
      ORDER BY matches_white DESC, matches_extra DESC, total_won DESC
    `).bind(cycle.id),
  ]);

  const expected = strategiesResult.results.reduce((sum, row) => sum + number(row.tickets_count), 0);
  const available = combinationsResult.results.length;
  const totalWon = strategiesResult.results.reduce((sum, row) => sum + number(row.total_prize), 0);
  const detailRatio = coverage(available, expected);

  const strategies = strategiesResult.results.map((row, index) => {
    const strategyExpected = number(row.tickets_count);
    const strategyAvailable = number(row.available_combinations);
    const strategyCoverage = coverage(strategyAvailable, strategyExpected);
    return {
      rank: index + 1,
      strategy_id: row.strategy_id,
      name: row.name,
      description: row.description || '',
      evaluated_combinations: strategyExpected,
      total_won: number(row.total_prize),
      roi: rounded(row.roi),
      weight_before: rounded(row.weight_before, 6),
      weight_after: rounded(row.weight_after, 6),
      matches: {
        three: number(row.matches_3),
        four: number(row.matches_4),
        five: number(row.matches_5),
      },
      detail_coverage: strategyCoverage,
      winning_combinations: strategyCoverage === 1 ? number(row.winning_combinations) : null,
      best_match: strategyCoverage === 1 ? {
        white: Math.floor(number(row.best_match_score) / 2),
        extra: number(row.best_match_score) % 2,
      } : null,
    };
  });

  const combinations = combinationsResult.results.map(row => ({
    id: number(row.id),
    strategy_id: row.strategy_id,
    strategy_name: row.strategy_name,
    strategy_position: number(row.strategy_position),
    numbers: [row.n1, row.n2, row.n3, row.n4, row.n5].filter(n => n !== null && n !== undefined).map(number),
    extra: row.extra == null ? null : number(row.extra),
    analytical_score: number(row.confidence),
    score_scope: 'strategy_internal',
    result: {
      white_matches: number(row.matches_white),
      extra_match: number(row.matches_extra),
      prize_level: row.prize_level || 'no_prize',
      prize_amount: number(row.prize_amount),
    },
  }));

  return json({
    game: gamePayload(game),
    draw: drawPayload(cycle),
    summary: {
      total_won: totalWon,
      total_cost: expected * ticketCost,
      roi: lifetimeRoi(totalWon, expected, ticketCost),
      evaluated_combinations: expected,
      available_combinations: available,
      combinations_available: available > 0,
      detail_coverage: detailRatio,
    },
    strategies,
    distribution: distributionResult.results.map(row => ({
      white_matches: number(row.matches_white),
      extra_match: number(row.matches_extra),
      prize_level: row.prize_level || 'no_prize',
      combinations: number(row.combinations),
      total_won: number(row.total_won),
    })),
    combinations,
  });
}

async function strategyRankings(env, game) {
  const lotteryId = game.id;
  const ticketCost = TICKET_COSTS[lotteryId];
  const { results } = await env.DB.prepare(`
    WITH stats AS (
      SELECT strategy_id, COUNT(*) AS evaluated_draws,
             SUM(tickets_count) AS evaluated_combinations,
             SUM(total_prize) AS total_won,
             SUM(matches_3) AS matches_3,
             SUM(matches_4) AS matches_4,
             SUM(matches_5) AS matches_5
      FROM strategy_stats WHERE lottery_id=? GROUP BY strategy_id
    ),
    ticket_stats AS (
      SELECT strategy_id, COUNT(*) AS available_combinations,
             SUM(CASE WHEN prize_amount>0 THEN 1 ELSE 0 END) AS winning_combinations,
             MAX(matches_white * 2 + matches_extra) AS best_match_score
      FROM tickets WHERE lottery_id=? AND evaluated=1 GROUP BY strategy_id
    ),
    recent_rows AS (
      SELECT strategy_id, draw_date, total_prize, roi,
             ROW_NUMBER() OVER (PARTITION BY strategy_id ORDER BY draw_date DESC) AS recent_rank
      FROM strategy_stats WHERE lottery_id=?
    ),
    trends AS (
      SELECT strategy_id,
             MAX(CASE WHEN recent_rank=1 THEN total_prize END) AS latest_total_won,
             MAX(CASE WHEN recent_rank=2 THEN total_prize END) AS previous_total_won,
             MAX(CASE WHEN recent_rank=1 THEN roi END) AS latest_roi,
             MAX(CASE WHEN recent_rank=2 THEN roi END) AS previous_roi
      FROM recent_rows WHERE recent_rank<=2 GROUP BY strategy_id
    )
    SELECT s.id AS strategy_id, s.name, s.description, s.status, s.current_weight,
           COALESCE(st.evaluated_draws,0) AS evaluated_draws,
           COALESCE(st.evaluated_combinations,0) AS evaluated_combinations,
           COALESCE(st.total_won,0) AS total_won,
           COALESCE(st.matches_3,0) AS matches_3,
           COALESCE(st.matches_4,0) AS matches_4,
           COALESCE(st.matches_5,0) AS matches_5,
           COALESCE(ts.available_combinations,0) AS available_combinations,
           COALESCE(ts.winning_combinations,0) AS winning_combinations,
           ts.best_match_score,
           tr.latest_total_won, tr.previous_total_won, tr.latest_roi, tr.previous_roi
    FROM strategies s
    LEFT JOIN stats st ON st.strategy_id=s.id
    LEFT JOIN ticket_stats ts ON ts.strategy_id=s.id
    LEFT JOIN trends tr ON tr.strategy_id=s.id
    WHERE s.lottery_id=? AND s.status!='archived'
  `).bind(lotteryId, lotteryId, lotteryId, lotteryId).all();

  const rowsWithEvidence = results.filter(row => number(row.evaluated_combinations) > 0);
  const globalCombinations = rowsWithEvidence.reduce(
    (sum, row) => sum + number(row.evaluated_combinations), 0
  );
  const globalWon = rowsWithEvidence.reduce(
    (sum, row) => sum + number(row.total_won), 0
  );
  const globalDraws = rowsWithEvidence.reduce(
    (sum, row) => sum + number(row.evaluated_draws), 0
  );
  const globalWonRate = globalCombinations > 0 ? globalWon / globalCombinations : 0;
  const averageCombinationsPerDraw = globalDraws > 0
    ? globalCombinations / globalDraws
    : 0;
  const priorCombinations = averageCombinationsPerDraw * RANKING_PRIOR_DRAWS;

  const rankedResults = results.map(row => {
    const combinations = number(row.evaluated_combinations);
    const adjustedWonRate = combinations > 0 && priorCombinations > 0
      ? (number(row.total_won) + priorCombinations * globalWonRate)
        / (combinations + priorCombinations)
      : globalWonRate;
    return {
      row,
      hasEvidence: combinations > 0,
      hasPrize: number(row.total_won) > 0,
      expectedWon: adjustedWonRate * priorCombinations,
      lifetimeRoi: lifetimeRoi(number(row.total_won), combinations, ticketCost),
    };
  }).sort((a, b) => {
    if (a.hasPrize !== b.hasPrize) return a.hasPrize ? -1 : 1;
    if (a.hasEvidence !== b.hasEvidence) return a.hasEvidence ? -1 : 1;
    if (b.expectedWon !== a.expectedWon) return b.expectedWon - a.expectedWon;
    const aRoi = a.lifetimeRoi == null ? -Infinity : a.lifetimeRoi;
    const bRoi = b.lifetimeRoi == null ? -Infinity : b.lifetimeRoi;
    if (bRoi !== aRoi) return bRoi - aRoi;
    return String(a.row.strategy_id).localeCompare(String(b.row.strategy_id));
  });

  const rankings = rankedResults.map(({ row, expectedWon }, index) => {
    const expected = number(row.evaluated_combinations);
    const available = number(row.available_combinations);
    const detailRatio = coverage(available, expected);
    const coveredWinRate = available > 0
      ? rounded(number(row.winning_combinations) * 100 / available, 2)
      : null;
    const aggregateBestWhite = number(row.matches_5) > 0 ? 5
      : number(row.matches_4) > 0 ? 4
        : number(row.matches_3) > 0 ? 3 : null;
    return {
      rank: index + 1,
      strategy_id: row.strategy_id,
      name: row.name,
      description: row.description || '',
      status: row.status,
      current_weight: rounded(row.current_weight, 6),
      evaluated_draws: number(row.evaluated_draws),
      evaluated_combinations: expected,
      total_won: number(row.total_won),
      expected_won: rounded(expectedWon),
      total_cost: expected * ticketCost,
      lifetime_roi: lifetimeRoi(number(row.total_won), expected, ticketCost),
      detail_coverage: {
        expected_combinations: expected,
        available_combinations: available,
        ratio: detailRatio,
      },
      winning_combinations: detailRatio === 1 ? number(row.winning_combinations) : null,
      win_rate: detailRatio === 1 ? coveredWinRate : null,
      covered_winning_combinations: number(row.winning_combinations),
      covered_win_rate: coveredWinRate,
      covered_best_match: available > 0 ? {
        white: Math.floor(number(row.best_match_score) / 2),
        extra: number(row.best_match_score) % 2,
      } : null,
      best_match: detailRatio === 1 ? {
        white: Math.floor(number(row.best_match_score) / 2),
        extra: number(row.best_match_score) % 2,
      } : null,
      aggregate_best_white_match: aggregateBestWhite,
      credibility: {
        evaluated_draws: number(row.evaluated_draws),
        threshold: 20,
        factor: Math.min(1, number(row.evaluated_draws) / 20),
        mature: number(row.evaluated_draws) >= 20,
      },
      trend: {
        latest_total_won: row.latest_total_won == null ? null : number(row.latest_total_won),
        previous_total_won: row.previous_total_won == null ? null : number(row.previous_total_won),
        total_won_delta: row.latest_total_won == null || row.previous_total_won == null
          ? null : number(row.latest_total_won) - number(row.previous_total_won),
        latest_roi: row.latest_roi == null ? null : rounded(row.latest_roi),
        previous_roi: row.previous_roi == null ? null : rounded(row.previous_roi),
        roi_delta: row.latest_roi == null || row.previous_roi == null
          ? null : rounded(number(row.latest_roi) - number(row.previous_roi)),
      },
    };
  });

  return json({
    game: gamePayload(game),
    ordering: {
      primary: 'empirical_bayes_expected_won_desc',
      description: `Estrategias con WON positivo primero; dentro de cada grupo, WON esperado proyectado a ${RANKING_PRIOR_DRAWS} sorteos y ajustado hacia el promedio global según la evidencia disponible.`,
      prior_draws: RANKING_PRIOR_DRAWS,
      prior_combinations: rounded(priorCombinations),
      tie_breakers: ['lifetime_roi_desc', 'strategy_id_asc'],
    },
    rankings,
  });
}

async function nextDrawAnalysis(url, env, game) {
  const pagination = parsePagination(url, { defaultLimit: 10, maxLimit: 100 });
  if (pagination.error) return json({ error: pagination.error }, 400);
  const { limit, offset } = pagination;
  const lotteryId = game.id;
  const strategyId = url.searchParams.get('strategy');

  if (strategyId) {
    const strategy = await env.DB.prepare(
      `SELECT id FROM strategies WHERE id=? AND lottery_id=? AND status!='archived'`
    ).bind(strategyId, lotteryId).first();
    if (!strategy) return json({ error: 'strategy does not belong to this game' }, 400);
  }

  const cycle = await env.DB.prepare(`
    SELECT id, draw_date, tickets_total
    FROM cycles WHERE lottery_id=? AND status='generated'
    ORDER BY draw_date DESC LIMIT 1
  `).bind(lotteryId).first();
  if (!cycle) return json({ game: gamePayload(game), found: false });

  const [countResult, rowsResult, jackpotResult, strategiesResult] = await env.DB.batch([
    env.DB.prepare(`
      SELECT COUNT(*) AS total FROM tickets
      WHERE cycle_id=? AND evaluated=0 AND (? IS NULL OR strategy_id=?)
    `).bind(cycle.id, strategyId, strategyId),
    env.DB.prepare(`
      WITH ranked_combinations AS (
        SELECT t.id, t.strategy_id, t.n1, t.n2, t.n3, t.n4, t.n5, t.extra,
               t.confidence,
               ROW_NUMBER() OVER (
                 ORDER BY t.confidence DESC, t.id ASC
               ) AS pool_position,
               ROW_NUMBER() OVER (
                 PARTITION BY t.strategy_id ORDER BY t.confidence DESC, t.id ASC
               ) AS strategy_position
        FROM tickets t WHERE t.cycle_id=? AND t.evaluated=0
      )
      SELECT rc.*, s.name AS strategy_name, s.description AS strategy_description
      FROM ranked_combinations rc
      JOIN strategies s ON s.id=rc.strategy_id
      WHERE (? IS NULL OR rc.strategy_id=?)
      ORDER BY rc.pool_position ASC
      LIMIT ? OFFSET ?
    `).bind(cycle.id, strategyId, strategyId, limit, offset),
    env.DB.prepare(`
      SELECT amount, cash_value, source, last_status, last_success_at
      FROM jackpots WHERE lottery_id=?
    `).bind(lotteryId),
    env.DB.prepare(`
      SELECT id, name, description
      FROM strategies
      WHERE lottery_id=? AND status!='archived'
      ORDER BY name ASC
    `).bind(lotteryId),
  ]);

  const total = number(countResult.results[0]?.total);
  const items = rowsResult.results.map(row => ({
    display_order: number(row.pool_position),
    id: number(row.id),
    strategy_id: row.strategy_id,
    strategy_name: row.strategy_name,
    strategy_description: row.strategy_description || '',
    pool_position: number(row.pool_position),
    strategy_position: number(row.strategy_position),
    numbers: [row.n1, row.n2, row.n3, row.n4, row.n5].filter(n => n !== null && n !== undefined).map(number),
    extra: row.extra == null ? null : number(row.extra),
    analytical_score: number(row.confidence),
    score_scope: 'strategy_internal',
  }));

  return json({
    game: gamePayload(game),
    found: true,
    draw_date: cycle.draw_date,
    jackpot: jackpotPayload(jackpotResult.results[0]),
    expected_combinations: number(cycle.tickets_total),
    pagination: { limit, offset, total, has_more: offset + items.length < total },
    filter: { strategy: strategyId || null },
    ordering: {
      type: 'pool_position_by_internal_score_desc',
      description: 'Pool position is a unique draw-local number ordered by raw internal score descending; ticket ID breaks ties.',
    },
    strategies: strategiesResult.results.map(row => ({
      id: row.id,
      name: row.name,
      description: row.description || '',
    })),
    items,
  });
}

async function listActiveGames(db) {
  const { results } = await db.prepare(`
    SELECT id, name, draw_days, white_ball_count, white_ball_max,
           extra_ball_name, extra_ball_max, active, game_type, jurisdiction
    FROM lotteries WHERE active=1 ORDER BY created_at ASC
  `).all();
  return json((results || []).map(gamePayload));
}

export async function handlePresentationAPI(path, url, env) {
  if (path === '/api/games') return listActiveGames(env.DB);

  const detailPrefix = '/api/analyses/';
  const isDetail = path.startsWith(detailPrefix);
  const supported = path === '/api/overview'
    || path === '/api/analyses'
    || path === '/api/strategy-rankings'
    || path === '/api/next-draw-analysis'
    || isDetail;
  if (!supported) return null;

  const lotteryId = url.searchParams.get('game') || 'powerball';
  const game = await loadGame(env.DB, lotteryId);
  if (!game || TICKET_COSTS[lotteryId] == null) {
    return json({ error: 'unknown or inactive game' }, 400);
  }

  if (path === '/api/overview') return overview(url, env, game);
  if (path === '/api/analyses') return analyses(url, env, game);
  if (path === '/api/strategy-rankings') return strategyRankings(env, game);
  if (path === '/api/next-draw-analysis') return nextDrawAnalysis(url, env, game);

  let drawDate;
  try {
    drawDate = decodeURIComponent(path.slice(detailPrefix.length));
  } catch {
    return json({ error: 'draw date must use YYYY-MM-DD' }, 400);
  }
  return analysisDetail(drawDate, env, game);
}
