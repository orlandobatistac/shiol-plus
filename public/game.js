const API = '';
const GAME = new URLSearchParams(location.search).get('game') || 'powerball';
const ET_TZ = 'America/New_York';
const DRAW_HOUR_ET = GAME === 'cash5' ? 23 : (GAME === 'mega_millions' ? 23 : 22);
const DRAW_MIN_ET = GAME === 'cash5' ? 22 : (GAME === 'mega_millions' ? 0 : 59);
const DAY_ABBR = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

let gameInfoPromise = null;
let countdownTimer = null;
let overviewPromise = null;
let historyOffset = 0;
let historyTotal = 0;
let selectedAnalysis = null;
let analysisLastFocused = null;
const HISTORY_LIMIT = 10;
const NEXT_ANALYSIS_LIMIT = 10;
let nextAnalysisOffset = 0;
let nextAnalysisTotal = 0;
let nextAnalysisStrategy = 'all';
let nextAnalysisStrategies = [];

async function api(path) {
  try {
    const response = await fetch(API + path);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return await response.json();
  } catch (error) {
    console.error('API error:', path, error);
    return null;
  }
}

function money(value) {
  const number = Number(value || 0);
  if (number >= 1000000000) return '$' + (number / 1000000000).toFixed(1) + 'B';
  if (number >= 1000000) return '$' + (number / 1000000).toFixed(1) + 'M';
  if (number >= 1000) return '$' + (number / 1000).toFixed(0) + 'K';
  return '$' + number.toLocaleString();
}

function moneyExact(value) {
  return '$' + Number(value || 0).toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function roi(value) {
  const number = Number(value || 0);
  const percent = (number * 100).toFixed(1);
  return '<span class="' + (number >= 0 ? 'pos' : 'neg') + '">' +
    (number >= 0 ? '+' : '') + percent + '%</span>';
}

function isBaseline(strategyId) {
  return String(strategyId || '').replace(/_(mega_millions|cash5|pick3|pick4)$/, '') === 'random_baseline';
}

function strategyName(value) {
  const normalized = String(value || '').replace(/_(mega_millions|cash5|pick3|pick4)$/, '');
  const names = {
    xgboost_ml: 'XGBoost ML',
    hybrid_ensemble: 'Hybrid Ensemble',
    frequency_weighted: 'Frequency Weighted',
    intelligent_scoring: 'Intelligent Scoring',
    coverage_optimizer: 'Coverage Optimizer',
    cooccurrence: 'Cooccurrence',
    range_balanced: 'Range Balanced',
    random_baseline: 'Random Baseline',
    wheeling: 'Wheeling'
  };
  return names[normalized] || normalized.replace(/_/g, ' ').replace(/\b\w/g, function (character) {
    return character.toUpperCase();
  });
}

function strategyDescription(value) {
  const normalized = String(value || '').replace(/_(mega_millions|cash5|pick3|pick4)$/, '');
  const descriptions = {
    xgboost_ml: 'Machine-learning model trained on historical draws',
    hybrid_ensemble: '70% XGBoost + 30% co-occurrence',
    frequency_weighted: 'Historical frequency weighting',
    intelligent_scoring: 'Time-decay scoring with gap bonus',
    coverage_optimizer: 'Maximizes coverage while reducing repetition',
    cooccurrence: 'Frequently recurring number pairs',
    range_balanced: 'Balanced low, mid and high ranges',
    random_baseline: 'Scientific control using random selection',
    wheeling: 'Covering design (lottery wheel) over a hot-number pool'
  };
  return descriptions[normalized] || 'Independent analytical strategy';
}

function titleCase(value) {
  return String(value || '').replace(/_/g, ' ').replace(/\b\w/g, function (character) {
    return character.toUpperCase();
  });
}

function dateLabel(value, options) {
  if (!value) return '';
  const date = new Date(value.length === 10 ? value + 'T12:00:00Z' : value);
  return new Intl.DateTimeFormat('en-US', options || {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
  }).format(date);
}

function ballsHTML(numbers, extra, isCompact) {
  const isDigit = (GAME === 'pick3' || GAME === 'pick4');
  const cls = isCompact ? 'ball ball-sm' : 'ball';
  const digitStyle = isDigit ? 'border-radius:6px; font-weight:800;' : '';
  const whiteBalls = (numbers || []).map(function (number) {
    const text = isDigit ? String(number) : String(number).padStart(2, '0');
    return '<span class="' + cls + '" style="' + digitStyle + '">' + text + '</span>';
  }).join('');
  const extraBall = extra == null ? '' :
    '<span class="' + cls + ' extra">' + String(extra).padStart(2, '0') + '</span>';
  return whiteBalls + extraBall;
}

function stateMarkup(type, title, message) {
  return [
    '<div class="ui-state ui-state-' + type + '" role="status">',
      '<span class="ui-state-marker" aria-hidden="true"></span>',
      '<div><strong>' + title + '</strong><p>' + message + '</p></div>',
    '</div>'
  ].join('');
}

function getGameInfo() {
  if (!gameInfoPromise) {
    gameInfoPromise = api('/api/games').then(function (games) {
      const game = games && games.find(function (item) { return item.id === GAME; });
      return game || {
        id: GAME,
        name: strategyName(GAME),
        draw_days: 'mon,wed,sat',
        active: false
      };
    });
  }
  return gameInfoPromise;
}

function getOverview() {
  if (!overviewPromise) overviewPromise = api('/api/overview?game=' + GAME);
  return overviewPromise;
}

async function renderGameIdentity() {
  const game = await getGameInfo();
  document.title = 'SHIOL+ | ' + game.name + ' strategy report';
  document.body.classList.toggle('game-mega', GAME === 'mega_millions');
  document.body.classList.toggle('game-cash5', GAME === 'cash5');

  const title = document.getElementById('report-title');
  const description = document.getElementById('report-description');
  title.textContent = game.name + ' strategy report';
  description.textContent =
    'Historical strategy performance and analytical combinations prepared for the next ' +
    game.name + ' drawing.';

  document.querySelectorAll('.game-switcher a').forEach(function (link) {
    const active = link.dataset.game === GAME;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
  });

}

function getZonedParts(date) {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TZ,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    weekday: 'short'
  });
  const parts = {};
  formatter.formatToParts(date).forEach(function (part) {
    parts[part.type] = part.value;
  });
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    second: Number(parts.second),
    weekday: DAY_ABBR[parts.weekday.toLowerCase().slice(0, 3)]
  };
}

function drawDateTime(drawDate) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(drawDate || ''))) return null;
  const parts = drawDate.split('-').map(Number);
  const wallTime = Date.UTC(parts[0], parts[1] - 1, parts[2], DRAW_HOUR_ET, DRAW_MIN_ET, 0);
  const guess = new Date(wallTime);
  const zoned = getZonedParts(guess);
  const representedAsUtc = Date.UTC(
    zoned.year, zoned.month - 1, zoned.day, zoned.hour, zoned.minute, zoned.second
  );
  return new Date(wallTime - (representedAsUtc - guess.getTime()));
}

function renderCountdown(drawDate) {
  const value = document.getElementById('countdown-value');
  const label = document.getElementById('next-draw-label');
  const target = drawDateTime(drawDate);

  function tick() {
    if (!target) {
      value.textContent = 'Schedule unavailable';
      label.textContent = 'No generated draw is currently available';
      return;
    }

    const difference = Math.max(0, target.getTime() - Date.now());
    const days = Math.floor(difference / 86400000);
    const hours = Math.floor((difference % 86400000) / 3600000);
    const minutes = Math.floor((difference % 3600000) / 60000);

    value.textContent = new Intl.DateTimeFormat('en-US', {
      timeZone: ET_TZ,
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    }).format(target);
    label.textContent =
      'In ' + days + 'd ' + hours + 'h ' + minutes + 'm - 10:59 PM ET';
  }

  tick();
  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(tick, 30000);
}

async function renderOverview() {
  const amount = document.getElementById('jackpot-amount');
  const sub = document.getElementById('jackpot-sub');
  const data = await getOverview();

  if (!data) {
    amount.textContent = 'Not available';
    sub.textContent = 'Jackpot data is temporarily unavailable';
    renderCountdown(null);
    document.getElementById('draw-balls').innerHTML =
      '<span class="summary-secondary">No result available</span>';
    document.getElementById('overview-total-won').textContent = 'Not available';
    document.getElementById('overview-total-cost').textContent = 'Evaluation summary unavailable';
    document.getElementById('overview-draws').textContent = 'Not available';
    document.getElementById('overview-combinations').textContent = 'Evaluation summary unavailable';
    document.getElementById('overview-leader').textContent = 'Not available';
    document.getElementById('overview-leader-note').textContent = 'Historical ranking unavailable';
    return;
  }

  if (data.jackpot && data.jackpot.found) {
    amount.textContent = money(data.jackpot.amount);
    sub.textContent = (data.jackpot.cash_value == null ? 'Estimated jackpot' :
      'Cash value ' + money(data.jackpot.cash_value)) +
      (data.jackpot.stale ? ' - estimate may be outdated' : '');
  } else {
    amount.textContent = 'Not available';
    sub.textContent = 'No current estimate';
  }

  renderCountdown(data.next_draw && data.next_draw.found ? data.next_draw.draw_date : null);

  if (data.last_result) {
    document.getElementById('draw-balls').innerHTML =
      ballsHTML(data.last_result.numbers, data.last_result.extra);
    document.getElementById('draw-date').textContent = '- ' + dateLabel(data.last_result.draw_date, {
      month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
    });
  } else {
    document.getElementById('draw-balls').innerHTML =
      '<span class="summary-secondary">No result available</span>';
  }

  const performance = data.performance || {};
  const draws = Number(performance.evaluated_draws || 0);
  const combinations = Number(performance.evaluated_combinations || 0);
  document.getElementById('overview-total-won').textContent = money(performance.total_won);
  document.getElementById('overview-total-cost').textContent =
    moneyExact(performance.total_cost) + ' evaluation cost since launch';
  document.getElementById('overview-draws').textContent =
    draws.toLocaleString() + (draws === 1 ? ' draw' : ' draws');
  document.getElementById('overview-combinations').textContent =
    combinations.toLocaleString() + ' combinations evaluated';

  if (data.top_strategy) {
    document.getElementById('overview-leader').textContent =
      strategyName(data.top_strategy.strategy_id || data.top_strategy.name);
    document.getElementById('overview-leader-note').textContent =
      money(data.top_strategy.total_won) + ' in lifetime prizes';
  } else {
    document.getElementById('overview-leader').textContent = 'Not available';
    document.getElementById('overview-leader-note').textContent = 'No evaluated strategy results yet';
  }
}

function matchLabel(match, extraName) {
  if (!match) return 'Detail unavailable';
  const white = Number(match.white || 0);
  return white + ' white' + (match.extra ? ' + ' + (extraName || 'extra ball') : '');
}

function analysisResultLabel(result, extraName) {
  if (!result) return 'Not evaluated';
  const white = Number(result.white_matches || 0);
  const parts = [white + ' white'];
  if (result.extra_match) parts.push(extraName || 'extra ball');
  if (Number(result.prize_amount || 0) > 0) parts.push(money(result.prize_amount));
  return parts.join(' + ');
}

async function renderHistory() {
  const body = document.getElementById('history-body');
  document.getElementById('history-prev').disabled = true;
  document.getElementById('history-next').disabled = true;
  body.innerHTML = stateMarkup('loading', 'Loading draw history', 'Retrieving evaluated analyses.');
  const data = await api('/api/analyses?game=' + GAME + '&limit=' + HISTORY_LIMIT + '&offset=' + historyOffset);

  if (!data || !data.items) {
    historyTotal = 0;
    body.innerHTML = stateMarkup('error', 'Draw history unavailable', 'Please retry when the data service is available.');
    updateHistoryPagination(0);
    return;
  }

  historyTotal = Number(data.pagination && data.pagination.total || 0);
  if (!data.items.length) {
    body.innerHTML = stateMarkup('empty', 'No evaluated drawings yet', 'Completed analyses will appear here after a published draw.');
    updateHistoryPagination(0);
    return;
  }

  body.innerHTML = data.items.map(function (analysis) {
    const draw = analysis.draw || {};
    const detailComplete = Number(analysis.detail_coverage || 0) === 1;
    const bestStrategy = analysis.best_strategy ?
      strategyName(analysis.best_strategy.strategy_id || analysis.best_strategy.name) : 'Not available';
    return [
      '<div class="history-row" role="row">',
        '<div class="history-result" role="cell">',
          '<strong class="history-date">' + dateLabel(draw.draw_date) + '</strong>',
          '<div class="draw-balls">' + ballsHTML(draw.numbers, draw.extra, true) + '</div>',
        '</div>',
        '<div class="history-metric" role="cell"><strong style="font-family: var(--font-mono); font-size: 14px;">' + money(analysis.total_won) + '</strong></div>',
        '<div class="history-metric" role="cell"><span style="font-family: var(--font-mono);">' +
          (detailComplete ? Number(analysis.winning_combinations || 0).toLocaleString() : 'Not retained') + '</span></div>',
        '<div class="history-metric" role="cell"><strong>' + bestStrategy + '</strong></div>',
        '<div class="history-metric" role="cell"><span class="match-tag">' +
          (detailComplete ? matchLabel(analysis.best_match, data.game.extra_ball_name) : 'Partial detail') + '</span></div>',
        '<div class="history-action" role="cell">',
          '<button class="pagination-button view-analysis-button" type="button" data-draw-date="' + draw.draw_date + '">View Analysis</button>',
        '</div>',
      '</div>'
    ].join('');
  }).join('');

  body.querySelectorAll('.view-analysis-button').forEach(function (button) {
    button.addEventListener('click', function () { openAnalysisModal(button.dataset.drawDate); });
  });
  updateHistoryPagination(data.items.length);
}

function updateHistoryPagination(visibleCount) {
  const start = historyTotal && visibleCount ? historyOffset + 1 : 0;
  const end = visibleCount ? historyOffset + visibleCount : 0;
  const page = Math.floor(historyOffset / HISTORY_LIMIT) + 1;
  const pageTotal = Math.max(1, Math.ceil(historyTotal / HISTORY_LIMIT));
  document.getElementById('history-count').textContent =
    'Showing ' + start + '-' + end + ' of ' + historyTotal + ' evaluated draws';
  document.getElementById('history-page').textContent = 'Page ' + page + ' of ' + pageTotal;
  document.getElementById('history-prev').disabled = historyOffset === 0;
  document.getElementById('history-next').disabled = historyOffset + visibleCount >= historyTotal;
}

function initHistoryPagination() {
  document.getElementById('history-prev').addEventListener('click', function () {
    historyOffset = Math.max(0, historyOffset - HISTORY_LIMIT);
    renderHistory();
  });
  document.getElementById('history-next').addEventListener('click', function () {
    if (historyOffset + HISTORY_LIMIT >= historyTotal) return;
    historyOffset += HISTORY_LIMIT;
    renderHistory();
  });
}

function summaryPanel(data) {
  const summary = data.summary || {};
  const coverage = Math.round(Number(summary.detail_coverage || 0) * 100);
  const roiVal = summary.roi == null ? 0 : Number(summary.roi);
  const roiClass = roiVal >= 0 ? 'pos' : 'neg';
  const roiText = summary.roi == null ? 'Not available' : (roiVal * 100).toFixed(1) + '%';

  return [
    '<section id="analysis-panel-summary" class="analysis-panel active" role="tabpanel" aria-labelledby="analysis-tab-summary">',
      '<div class="analysis-summary-grid">',
        '<div><span>Total Won</span><strong style="color: var(--mega);">' + money(summary.total_won) + '</strong></div>',
        '<div><span>Theoretical Cost</span><strong>' + moneyExact(summary.total_cost) + '</strong></div>',
        '<div><span>Evaluated Combinations</span><strong>' + Number(summary.evaluated_combinations || 0).toLocaleString() + '</strong></div>',
        '<div><span>Return / ROI</span><strong class="' + roiClass + '">' + (roiVal >= 0 ? '+' : '') + roiText + '</strong></div>',
      '</div>',
      '<div class="coverage-note ' + (coverage < 100 ? 'is-partial' : '') + '">',
        '<strong>' + coverage + '% detail retained</strong>',
        '<p>' + (coverage < 100 ?
          'Strategy totals are complete, though individual combinations were not retained for all historical draws.' :
          'All evaluated combinations are available for this draw.') + '</p>',
      '</div>',
    '</section>'
  ].join('');
}

function strategiesPanel(data) {
  return [
    '<section id="analysis-panel-strategies" class="analysis-panel" role="tabpanel" aria-labelledby="analysis-tab-strategies" hidden>',
      '<div class="ranking-table-wrap">',
        '<table class="data-table ranking-table">',
          '<thead>',
            '<tr>',
              '<th style="width: 50px;">Pos</th>',
              '<th>Strategy</th>',
              '<th style="text-align: right;">Total Won</th>',
              '<th style="text-align: right;">ROI</th>',
              '<th>Best Match</th>',
            '</tr>',
          '</thead>',
          '<tbody>',
            (data.strategies || []).map(function (strategy, index) {
              const roiVal = Number(strategy.roi || 0);
              const roiClass = roiVal >= 0 ? 'pos' : 'neg';
              const roiText = (roiVal * 100).toFixed(1) + '%';
              const rankClass = index === 0 ? 'rank-1' : (index === 1 ? 'rank-2' : (index === 2 ? 'rank-3' : 'rank-other'));

              return [
                '<tr>',
                  '<td><span class="rank-badge ' + rankClass + '">#' + strategy.rank + '</span></td>',
                  '<td><strong style="color: var(--ink);">' + strategyName(strategy.strategy_id || strategy.name) + '</strong></td>',
                  '<td style="text-align: right; font-weight: 700; font-family: var(--font-mono);">' + money(strategy.total_won) + '</td>',
                  '<td style="text-align: right;"><span class="' + roiClass + '">' + (roiVal >= 0 ? '+' : '') + roiText + '</span></td>',
                  '<td><span class="match-tag">' + matchLabel(strategy.best_match, data.game.extra_ball_name) + '</span></td>',
                '</tr>'
              ].join('');
            }).join(''),
          '</tbody>',
        '</table>',
      '</div>',
    '</section>'
  ].join('');
}

function combinationsPanel(data) {
  const strategies = data.strategies || [];
  return [
    '<section id="analysis-panel-combinations" class="analysis-panel" role="tabpanel" aria-labelledby="analysis-tab-combinations" hidden>',
      '<div class="control-row analysis-filters" style="margin-bottom: 16px;">',
        '<label style="font-weight: 600; display: flex; align-items: center; gap: 8px;">Strategy:',
          '<select id="analysis-strategy-filter" class="filter-control">',
            '<option value="all">All strategies</option>',
            strategies.map(function (strategy) {
              return '<option value="' + strategy.strategy_id + '">' + strategyName(strategy.strategy_id || strategy.name) + '</option>';
            }).join(''),
          '</select>',
        '</label>',
        '<label style="font-weight: 600; display: flex; align-items: center; gap: 8px;">Result:',
          '<select id="analysis-result-filter" class="filter-control">',
            '<option value="all">All results</option>',
            '<option value="winning" selected>Winning combinations</option>',
            '<option value="no_prize">No prize</option>',
          '</select>',
        '</label>',
        '<span id="analysis-combination-count" class="filter-count" style="margin-left: auto; font-size: 12px; color: var(--muted); font-weight: 600;"></span>',
      '</div>',
      '<div id="analysis-combinations-list" class="analysis-combinations-list"></div>',
    '</section>'
  ].join('');
}

function distributionPanel(data) {
  const rows = data.distribution || [];
  return [
    '<section id="analysis-panel-distribution" class="analysis-panel" role="tabpanel" aria-labelledby="analysis-tab-distribution" hidden>',
      '<div class="ranking-table-wrap">',
        rows.length ? [
          '<table class="data-table ranking-table">',
            '<thead>',
              '<tr>',
                '<th>Match Category</th>',
                '<th style="text-align: right;">Combinaciones</th>',
                '<th style="text-align: right;">Premios Ganados</th>',
              '</tr>',
            '</thead>',
            '<tbody>',
              rows.map(function (row) {
                return [
                  '<tr>',
                    '<td><span class="match-tag">' + matchLabel({ white: row.white_matches, extra: row.extra_match }, data.game.extra_ball_name) + '</span></td>',
                    '<td style="text-align: right; font-family: var(--font-mono);">' + Number(row.combinations || 0).toLocaleString() + ' combinations</td>',
                    '<td style="text-align: right; font-weight: 700; font-family: var(--font-mono); color: var(--mega);">' + money(row.total_won) + '</td>',
                  '</tr>'
                ].join('');
              }).join(''),
            '</tbody>',
          '</table>'
        ].join('') : stateMarkup('empty', 'No distribution detail retained', 'Strategy totals remain available in the Summary tab.'),
      '</div>',
    '</section>'
  ].join('');
}

function renderCombinationList() {
  if (!selectedAnalysis) return;
  const list = document.getElementById('analysis-combinations-list');
  const count = document.getElementById('analysis-combination-count');
  if (!list || !count) return;
  const strategyFilter = document.getElementById('analysis-strategy-filter').value;
  const resultFilter = document.getElementById('analysis-result-filter').value;
  const items = (selectedAnalysis.combinations || []).filter(function (item) {
    const strategyMatch = strategyFilter === 'all' || item.strategy_id === strategyFilter;
    const winning = Number(item.result && item.result.prize_amount || 0) > 0;
    const resultMatch = resultFilter === 'all' || (resultFilter === 'winning' ? winning : !winning);
    return strategyMatch && resultMatch;
  });

  count.textContent = 'Showing ' + items.length + ' of ' + (selectedAnalysis.combinations || []).length + ' combinations';
  if (!items.length) {
    list.innerHTML = stateMarkup(
      selectedAnalysis.combinations && selectedAnalysis.combinations.length ? 'empty' : 'empty',
      selectedAnalysis.combinations && selectedAnalysis.combinations.length ? 'No combinations match the filters' : 'Combination detail not retained',
      selectedAnalysis.combinations && selectedAnalysis.combinations.length ? 'Try another strategy or result.' : 'Full totals are available in Summary and Strategies.'
    );
    return;
  }

  list.innerHTML = [
    '<div class="ranking-table-wrap">',
      '<table class="data-table ranking-table">',
        '<thead>',
          '<tr>',
            '<th style="width: 50px;">Pos</th>',
            '<th>Strategy</th>',
            '<th>Combination</th>',
            '<th>Result</th>',
            '<th style="text-align: right;">Premio</th>',
          '</tr>',
        '</thead>',
        '<tbody>',
          items.map(function (item) {
            const winning = Number(item.result && item.result.prize_amount || 0) > 0;
            const prizeAmount = Number(item.result && item.result.prize_amount || 0);

            return [
              '<tr class="' + (winning ? 'is-winning-row' : '') + '">',
                '<td><strong style="color: var(--accent); font-family: var(--font-mono);">#' + item.strategy_position + '</strong></td>',
                '<td><strong style="color: var(--ink);">' + strategyName(item.strategy_id || item.strategy_name) + '</strong></td>',
                '<td><div class="draw-balls">' + ballsHTML(item.numbers, item.extra, true) + '</div></td>',
                '<td><span class="match-tag">' + analysisResultLabel(item.result, selectedAnalysis.game.extra_ball_name) + '</span></td>',
                '<td style="text-align: right; font-weight: 700; font-family: var(--font-mono); color: ' + (winning ? 'var(--positive)' : 'var(--muted)') + ';">' + (winning ? money(prizeAmount) : '$0') + '</td>',
              '</tr>'
            ].join('');
          }).join(''),
        '</tbody>',
      '</table>',
    '</div>'
  ].join('');
}

function activateAnalysisTab(panelName, focusTab) {
  document.querySelectorAll('.analysis-tab').forEach(function (tab) {
    const active = tab.dataset.panel === panelName;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    if (active && focusTab) tab.focus();
  });
  document.querySelectorAll('.analysis-panel').forEach(function (panel) {
    const active = panel.id === 'analysis-panel-' + panelName;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function renderAnalysisDetail(data) {
  selectedAnalysis = data;
  document.getElementById('analysis-modal-sub').textContent = dateLabel(data.draw.draw_date) +
    ' · ' + Number(data.summary.evaluated_combinations || 0).toLocaleString() + ' evaluated combinations';
  document.getElementById('analysis-modal-balls').innerHTML = ballsHTML(data.draw.numbers, data.draw.extra, true);
  document.getElementById('analysis-modal-content').innerHTML =
    summaryPanel(data) + strategiesPanel(data) + combinationsPanel(data) + distributionPanel(data);
  document.getElementById('analysis-strategy-filter').addEventListener('change', renderCombinationList);
  document.getElementById('analysis-result-filter').addEventListener('change', renderCombinationList);
  renderCombinationList();
  activateAnalysisTab('summary', false);
}

async function openAnalysisModal(drawDate) {
  const overlay = document.getElementById('analysis-modal-overlay');
  analysisLastFocused = document.activeElement;
  selectedAnalysis = null;
  document.getElementById('analysis-modal-title').textContent = 'Draw Analysis';
  document.getElementById('analysis-modal-sub').textContent = 'Loading analysis for ' + dateLabel(drawDate) + '...';
  document.getElementById('analysis-modal-balls').innerHTML = '';
  document.getElementById('analysis-modal-content').innerHTML = stateMarkup(
    'loading', 'Loading draw analysis', 'Assembling evaluated results...'
  );
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  overlay.focus({ preventScroll: true });
  document.getElementById('analysis-modal-close').focus();

  const data = await api('/api/analyses/' + encodeURIComponent(drawDate) + '?game=' + GAME);
  if (!data || data.error) {
    document.getElementById('analysis-modal-content').innerHTML = stateMarkup(
      'error', 'Analysis unavailable', 'Could not load this evaluated draw. Please retry.'
    );
    return;
  }
  document.getElementById('analysis-modal-title').textContent = 'Draw Analysis - ' + dateLabel(data.draw.draw_date);
  renderAnalysisDetail(data);
}

function closeAnalysisModal() {
  const overlay = document.getElementById('analysis-modal-overlay');
  if (!overlay.classList.contains('open')) return;
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  selectedAnalysis = null;
  if (analysisLastFocused && typeof analysisLastFocused.focus === 'function') analysisLastFocused.focus();
}

function analysisFocusableElements() {
  return Array.from(document.querySelectorAll(
    '#analysis-modal-overlay.open button:not([disabled]), #analysis-modal-overlay.open select:not([disabled])'
  )).filter(function (element) { return !element.hidden && element.offsetParent !== null; });
}

function initAnalysisModal() {
  const overlay = document.getElementById('analysis-modal-overlay');
  document.getElementById('analysis-modal-close').addEventListener('click', closeAnalysisModal);
  overlay.addEventListener('click', function (event) {
    if (event.target === overlay) closeAnalysisModal();
  });
  // Capture Escape during the capture phase so it closes the modal even if
  // focus is inside a tab, select or other interactive element.
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && overlay.classList.contains('open')) {
      event.stopPropagation();
      closeAnalysisModal();
    }
  }, true);
  document.querySelectorAll('.analysis-tab').forEach(function (tab) {
    tab.addEventListener('click', function () { activateAnalysisTab(tab.dataset.panel, false); });
    tab.addEventListener('keydown', function (event) {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const tabs = Array.from(document.querySelectorAll('.analysis-tab'));
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = (tabs.indexOf(tab) + direction + tabs.length) % tabs.length;
      activateAnalysisTab(tabs[next].dataset.panel, true);
    });
  });
  document.addEventListener('keydown', function (event) {
    if (!overlay.classList.contains('open')) return;
    if (event.key === 'Escape') {
      closeAnalysisModal();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = analysisFocusableElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

function initReportDetailsModal() {
  const modal = document.getElementById('report-details-modal');
  const content = document.getElementById('report-details-content');
  content.appendChild(document.getElementById('rankings-details'));
  content.appendChild(document.getElementById('last-cycle'));
  const openButtons = Array.from(document.querySelectorAll('[data-report-details-open]'));
  let lastFocused = null;
  const close = function () {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
    if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
  };
  openButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      lastFocused = button;
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('modal-open');
      document.getElementById('report-details-close').focus();
    });
  });
  document.getElementById('report-details-close').addEventListener('click', close);
  modal.addEventListener('click', function (event) { if (event.target === modal) close(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && modal.classList.contains('open')) close();
  });
}

async function renderRankings() {
  const data = await api('/api/strategy-rankings?game=' + GAME);
  const body = document.getElementById('podium');
  const rankings = data && data.rankings;

  if (!rankings || !rankings.length) {
    body.innerHTML = stateMarkup(
      rankings ? 'empty' : 'error',
      rankings ? 'No historical ranking yet' : 'Historical ranking unavailable',
      rankings ? 'The ranking will appear after evaluated drawings.' : 'Please retry when the data service is available.'
    );
    document.getElementById('rankings-count').textContent = 'Showing 0 of 0 strategies';
    document.getElementById('rankings-coverage').textContent = '';
    return;
  }

  const tableHTML = [
    '<div class="ranking-table-wrap">',
      '<table class="data-table ranking-table">',
        '<thead>',
          '<tr>',
            '<th style="width: 50px;">Pos</th>',
            '<th>Model / Strategy</th>',
            '<th style="text-align: right;">Total Won</th>',
            '<th style="text-align: right;">Lifetime ROI</th>',
            '<th style="text-align: right;">Winning Combinations</th>',
            '<th style="text-align: right;">Evaluated Draws</th>',
            '<th>Best Match</th>',
          '</tr>',
        '</thead>',
        '<tbody>',
          rankings.map(function (strategy) {
            const pos = strategy.rank;
            const isTop = pos <= 3;
            const rankClass = pos === 1 ? 'gold' : (pos === 2 ? 'silver' : (pos === 3 ? 'bronze' : 'rank-other'));
            const isBase = isBaseline(strategy.strategy_id || strategy.name);
            const totalWon = Number(strategy.total_won || 0);
            const coverage = Number(strategy.detail_coverage && strategy.detail_coverage.ratio || 0);
            const complete = coverage === 1;
            const winningCombinations = complete ? Number(strategy.winning_combinations || 0).toLocaleString() :
              Number(strategy.covered_winning_combinations || 0).toLocaleString();
            const bestMatch = strategy.best_match || strategy.covered_best_match;
            const bestResult = bestMatch ? matchLabel(bestMatch, data.game.extra_ball_name) : 'Not retained';
            const roiVal = Number(strategy.lifetime_roi || 0);
            const roiClass = roiVal >= 0 ? 'pos' : 'neg';
            const roiText = (roiVal * 100).toFixed(1) + '%';

            const rowClasses = [
              isTop ? 'rank-top-row rank-top-' + pos : '',
              isBase ? 'baseline-row' : '',
            ].filter(Boolean).join(' ');

            return [
              '<tr' + (rowClasses ? ' class="' + rowClasses + '"' : '') + '>',
                '<td><span class="rank-badge ' + rankClass + '">#' + pos + '</span></td>',
                '<td>',
                  '<strong style="font-size: 13.5px; display: block; color: var(--ink);">' + strategyName(strategy.strategy_id || strategy.name) + '</strong>',
                  (isBase ? '<span class="baseline-chip">Benchmark</span>' : '<small style="color: var(--muted); font-size: 11px;">' + strategyDescription(strategy.strategy_id || strategy.name) + '</small>'),
                '</td>',
                '<td style="text-align: right; font-weight: 700; font-family: var(--font-mono);">' + money(totalWon) + '</td>',
                '<td style="text-align: right;"><span class="' + roiClass + '">' + (roiVal >= 0 ? '+' : '') + roiText + '</span></td>',
                '<td style="text-align: right; font-family: var(--font-mono);">' + winningCombinations + '</td>',
                '<td style="text-align: right; font-family: var(--font-mono);">' + Number(strategy.evaluated_draws || 0).toLocaleString() + '</td>',
                '<td><span class="match-tag">' + bestResult + '</span></td>',
              '</tr>'
            ].join('');
          }).join(''),
        '</tbody>',
      '</table>',
    '</div>'
  ].join('');

  body.innerHTML = tableHTML;

  const expected = rankings.reduce(function (sum, strategy) {
    return sum + Number(strategy.detail_coverage && strategy.detail_coverage.expected_combinations || 0);
  }, 0);
  const available = rankings.reduce(function (sum, strategy) {
    return sum + Number(strategy.detail_coverage && strategy.detail_coverage.available_combinations || 0);
  }, 0);
  const coveragePercent = expected ? Math.round(available * 100 / expected) : 0;
  document.getElementById('rankings-count').textContent =
    'Showing 1-' + rankings.length + ' of ' + rankings.length + ' strategies · ordered by statistical performance';
  document.getElementById('rankings-coverage').textContent = coveragePercent === 100
    ? 'Winning combinations, win rate and best result cover the full evaluation period.'
    : 'Combination-level metrics cover ' + coveragePercent + '% of the period; prize totals, cost, ROI and evaluated counts are complete.';
}

function sparklineSvg(values) {
  if (!values || values.length < 2) return '<span class="spark-empty">No trend</span>';
  const width = 72;
  const height = 24;
  const padding = 3;
  const min = Math.min.apply(null, values);
  const max = Math.max.apply(null, values);
  const range = max - min || 1;
  const step = (width - padding * 2) / (values.length - 1);
  const points = values.map(function (value, index) {
    const x = padding + index * step;
    const y = height - padding - ((value - min) / range) * (height - padding * 2);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  const color = values[values.length - 1] >= values[0] ? 'var(--positive)' : 'var(--negative)';
  return '<svg class="sparkline" viewBox="0 0 72 24" width="72" height="24" aria-hidden="true">' +
    '<polyline points="' + points + '" fill="none" style="stroke:' + color +
    ';stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"></polyline></svg>';
}

async function renderSparklines(ids) {
  const histories = await Promise.all(ids.map(function (id) {
    return api('/api/history?game=' + GAME + '&strategy=' + id + '&limit=12');
  }));

  ids.forEach(function (id, index) {
    const cell = document.getElementById('spark-' + id);
    const rows = histories[index];
    if (!cell) return;
    if (!rows || !rows.length) {
      cell.innerHTML = '<span class="spark-empty">No trend</span>';
      return;
    }
    const values = rows.slice().reverse().map(function (row) {
      return Number(row.weight_after || 0);
    });
    cell.innerHTML = sparklineSvg(values);
  });
}

async function renderTechnicalStrategies() {
  const strategies = await api('/api/strategies?game=' + GAME);
  const body = document.getElementById('strategies-body');

  if (!strategies || !strategies.length) {
    body.innerHTML = '<tr><td colspan="7">No strategy data available.</td></tr>';
    return;
  }

  const maxWeight = Math.max.apply(null, strategies.map(function (strategy) {
    return Number(strategy.current_weight || 0);
  }));

  body.innerHTML = strategies.map(function (strategy, index) {
    const weight = Number(strategy.current_weight || 0);
    const fill = maxWeight ? (weight / maxWeight * 100).toFixed(1) : 0;
    const statusText = String(strategy.status || 'active') === 'active' ? 'Active' : 'Inactive';
    return [
      '<tr>',
        '<td><strong style="color: var(--accent); font-family: var(--font-mono);">#' + (index + 1) + '</strong></td>',
        '<td><strong style="color: var(--ink);">' + strategyName(strategy.id || strategy.name) + '</strong></td>',
        '<td><span class="pill">' + statusText + '</span></td>',
        '<td><div class="weight-bar-wrap"><div class="weight-bar"><div class="weight-fill" style="width:' +
          fill + '%"></div></div><span class="weight-val">' + weight.toFixed(4) + '</span></div></td>',
        '<td id="spark-' + strategy.id + '"><span class="spark-empty">Loading</span></td>',
        '<td>' + roi(strategy.avg_roi) + '</td>',
        '<td style="font-weight: 700; font-family: var(--font-mono); color: var(--mega);">' + money(strategy.lifetime_prize || 0) + '</td>',
      '</tr>'
    ].join('');
  }).join('');

  renderSparklines(strategies.map(function (strategy) { return strategy.id; }));
}

async function renderLastCycle() {
  const data = await api('/api/latest-cycle?game=' + GAME);
  const body = document.getElementById('cycle-body');
  const meta = document.getElementById('cycle-meta');

  if (!data || data.message) {
    meta.textContent = '';
    body.innerHTML = '<tr><td colspan="8">No evaluated cycle available.</td></tr>';
    return;
  }

  const cycle = data.cycle;
  const results = data.strategy_results || [];
  meta.textContent = 'Draw on ' + dateLabel(cycle.draw_date) + ': ' +
    [cycle.n1, cycle.n2, cycle.n3, cycle.n4, cycle.n5].join(' - ') +
    ' / PB ' + cycle.pb;

  body.innerHTML = results.map(function (result) {
    const delta = Number(result.weight_after || 0) - Number(result.weight_before || 0);
    return [
      '<tr>',
        '<td><strong style="color: var(--ink);">' + strategyName(result.strategy_id) + '</strong></td>',
        '<td style="font-family: var(--font-mono);">' + result.tickets_count + '</td>',
        '<td style="font-family: var(--font-mono);">' + Number(result.matches_3 || 0) + '</td>',
        '<td style="font-family: var(--font-mono);">' + Number(result.matches_4 || 0) + '</td>',
        '<td style="font-family: var(--font-mono);">' + Number(result.matches_5 || 0) + '</td>',
        '<td style="font-weight: 700; font-family: var(--font-mono); color: var(--mega);">' + money(result.total_prize || 0) + '</td>',
        '<td>' + roi(result.roi) + '</td>',
        '<td><span class="' + (delta >= 0 ? 'pos' : 'neg') + '">' +
          (delta >= 0 ? '+' : '') + delta.toFixed(4) + '</span></td>',
      '</tr>'
    ].join('');
  }).join('');
}

function parseNumbers(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return String(value).split(/[ ,\-]+/).map(Number).filter(Boolean).slice(0, 5);
  }
}

function prizeLabel(value) {
  const normalized = String(value || '').toLowerCase().replace(/\s/g, '');
  if (normalized === 'match0+pb') return 'Powerball';
  if (normalized === 'match1+pb') return '1 match + PB';
  if (normalized === 'match2+pb') return '2 matches + PB';
  if (normalized === 'match3') return '3 matches';
  if (normalized === 'match3+pb') return '3 matches + PB';
  if (normalized === 'match4') return '4 matches';
  if (normalized === 'match4+pb') return '4 matches + PB';
  if (normalized === 'match5') return '5 matches';
  if (normalized === 'jackpot') return 'Jackpot';
  return String(value || 'Verified prize').replace(/\+/g, ' + ');
}

async function renderWins() {
  const data = await api('/api/wins?game=' + GAME);
  const list = document.getElementById('wins-grid');
  const total = document.getElementById('wins-total');

  if (!data || !data.total_count) {
    total.textContent = '';
    list.innerHTML = stateMarkup(
      data ? 'empty' : 'error',
      data ? 'No recent wins yet' : 'Recent wins unavailable',
      data ? 'Verified wins will appear after draws are evaluated.' : 'Retry when the service is available.'
    );
    return;
  }

  total.innerHTML = '<strong style="color: var(--mega); font-size: 16px;">' + money(data.total_amount) + '</strong> earned across <strong style="color: var(--ink); font-size: 13.5px;">' +
    Number(data.total_count).toLocaleString() + ' wins</strong>';

  list.innerHTML = (data.wins || []).slice(0, 6).map(function (win) {
    const numbers = parseNumbers(win.numbers);
    return [
      '<div class="win-card">',
        '<div class="win-card-head">',
          '<div class="win-card-meta">',
            '<span class="win-card-date">' + dateLabel(win.draw_date || (win.created_at || '').slice(0, 10)) + '</span>',
            '<span class="win-card-strategy">' + strategyName(win.strategy_id) + '</span>',
            '<span class="match-tag">' + prizeLabel(win.prize_level) + '</span>',
          '</div>',
          '<span class="win-card-amount">+' + money(win.prize_amount || 0) + '</span>',
        '</div>',
        '<div class="draw-balls">' + ballsHTML(numbers, win.extra, true) + '</div>',
      '</div>'
    ].join('');
  }).join('');
}

function internalScore(value) {
  const score = Number(value || 0);
  return (score <= 1 ? score * 100 : score).toFixed(1) + '%';
}

function updateNextAnalysisFilter() {
  const select = document.getElementById('next-analysis-strategy');
  select.innerHTML = '<option value="all">All 160 combinations</option>' +
    nextAnalysisStrategies.map(function (strategy) {
      return '<option value="' + strategy.id + '">' + strategyName(strategy.id) + ' (20 combinations)</option>';
    }).join('');
  select.value = nextAnalysisStrategy;
  select.disabled = false;
}

function updateNextAnalysisPagination(visibleCount) {
  const start = nextAnalysisTotal && visibleCount ? nextAnalysisOffset + 1 : 0;
  const end = visibleCount ? nextAnalysisOffset + visibleCount : 0;
  const page = Math.floor(nextAnalysisOffset / NEXT_ANALYSIS_LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(nextAnalysisTotal / NEXT_ANALYSIS_LIMIT));
  document.getElementById('next-analysis-count').textContent =
    'Showing ' + start + '-' + end + ' of ' + nextAnalysisTotal + ' analytical combinations';
  document.getElementById('next-analysis-page').textContent = 'Page ' + page + ' of ' + pages;
  document.getElementById('next-analysis-prev').disabled = nextAnalysisOffset === 0;
  document.getElementById('next-analysis-next').disabled = nextAnalysisOffset + visibleCount >= nextAnalysisTotal;
}

async function renderNextAnalysis() {
  const context = document.getElementById('next-analysis-context');
  const list = document.getElementById('next-analysis-list');
  document.getElementById('next-analysis-prev').disabled = true;
  document.getElementById('next-analysis-next').disabled = true;
  list.innerHTML = stateMarkup('loading', 'Loading combinations', 'Preparing the first page of the analysis.');
  const strategyQuery = nextAnalysisStrategy === 'all' ? '' : '&strategy=' + encodeURIComponent(nextAnalysisStrategy);
  const data = await api('/api/next-draw-analysis?game=' + GAME + '&limit=' + NEXT_ANALYSIS_LIMIT +
    '&offset=' + nextAnalysisOffset + strategyQuery);

  if (!data) {
    context.innerHTML = stateMarkup('error', 'Next draw unavailable', 'Retry when the service is available.');
    list.innerHTML = stateMarkup('error', 'Analysis unavailable', 'Could not load the combinations.');
    nextAnalysisTotal = 0;
    updateNextAnalysisPagination(0);
    return;
  }
  if (!data.found) {
    context.innerHTML = stateMarkup('empty', 'Next cycle not generated yet', 'The 160 combinations will appear once the cycle is ready.');
    list.innerHTML = stateMarkup('empty', 'No analysis yet', 'Temporary cycle status.');
    document.getElementById('next-analysis-strategy').disabled = true;
    nextAnalysisTotal = 0;
    updateNextAnalysisPagination(0);
    return;
  }

  context.innerHTML = [
    '<div><span>Next Draw</span><strong>' + dateLabel(data.draw_date) + '</strong></div>',
    '<div><span>Estimated Jackpot</span><strong style="color: var(--mega);">' + (data.jackpot && data.jackpot.found ? money(data.jackpot.amount) : 'Not available') + '</strong></div>',
    '<div><span>Analysis Status</span><strong style="color: var(--positive);">' + Number(data.expected_combinations || 0).toLocaleString() + ' combinations ready</strong></div>'
  ].join('');

  if (nextAnalysisStrategy === 'all' && nextAnalysisOffset === 0 && !nextAnalysisStrategies.length) {
    nextAnalysisStrategies = data.strategies || [];
    updateNextAnalysisFilter();
  }

  nextAnalysisTotal = Number(data.pagination && data.pagination.total || 0);
  const items = data.items || [];
  if (!items.length) {
    list.innerHTML = stateMarkup('empty', 'No combinations on this page', 'Choose another page or strategy.');
    updateNextAnalysisPagination(0);
    return;
  }
  list.innerHTML = items.map(function (item) {
    const scoreNum = Number(item.analytical_score || 0);
    const scorePct = (scoreNum <= 1 ? scoreNum * 100 : scoreNum).toFixed(1);
    return [
      '<div class="next-analysis-row" role="row">',
        '<div class="next-analysis-position" role="cell"><strong style="color: var(--accent); font-family: var(--font-mono); font-size: 14px;">#' + item.pool_position + '</strong></div>',
        '<div class="draw-balls" role="cell">' + ballsHTML(item.numbers, item.extra, true) + '</div>',
        '<div class="next-analysis-method" role="cell"><strong>' + strategyName(item.strategy_id || item.strategy_name) + '</strong></div>',
        '<div class="next-analysis-score" role="cell">',
          '<div class="score-meter">',
            '<span class="score-num">' + scorePct + '%</span>',
            '<div class="meter-bar"><div class="meter-fill" style="width:' + scorePct + '%"></div></div>',
          '</div>',
        '</div>',
      '</div>'
    ].join('');
  }).join('');
  updateNextAnalysisPagination(items.length);
}

function initNextAnalysis() {
  document.getElementById('next-analysis-strategy').addEventListener('change', function (event) {
    nextAnalysisStrategy = event.target.value;
    nextAnalysisOffset = 0;
    renderNextAnalysis();
  });
  document.getElementById('next-analysis-prev').addEventListener('click', function () {
    nextAnalysisOffset = Math.max(0, nextAnalysisOffset - NEXT_ANALYSIS_LIMIT);
    renderNextAnalysis();
  });
  document.getElementById('next-analysis-next').addEventListener('click', function () {
    if (nextAnalysisOffset + NEXT_ANALYSIS_LIMIT >= nextAnalysisTotal) return;
    nextAnalysisOffset += NEXT_ANALYSIS_LIMIT;
    renderNextAnalysis();
  });
}

function initScrollSpy() {
  const links = Array.from(document.querySelectorAll('.nav-link'));
  const sections = Array.from(document.querySelectorAll(
    '#overview, #draw-history, #rankings, #next-analysis'
  ));
  let scheduled = false;

  function updateActiveSection() {
    const activationLine = window.scrollY + (window.innerWidth <= 820 ? 160 : 176);
    let activeSection = sections[0];
    sections.forEach(function (section) {
      if (section.offsetTop <= activationLine) activeSection = section;
    });
    links.forEach(function (link) {
      const active = link.getAttribute('href') === '#' + activeSection.id;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    scheduled = false;
  }

  window.addEventListener('scroll', function () {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(updateActiveSection);
  }, { passive: true });
  window.addEventListener('resize', updateActiveSection);
  updateActiveSection();
}

function initDisclaimerModal() {
  const overlay = document.getElementById('disclaimer-modal');
  if (!overlay) return;
  const closeBtn = document.getElementById('disclaimer-modal-close');
  document.querySelectorAll('[data-disclaimer-open]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault();
      overlay.classList.add('open');
      overlay.setAttribute('aria-hidden', 'false');
      closeBtn.focus();
    });
  });
  closeBtn.addEventListener('click', function () {
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
  });
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) {
      overlay.classList.remove('open');
      overlay.setAttribute('aria-hidden', 'true');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && overlay.classList.contains('open')) {
      overlay.classList.remove('open');
      overlay.setAttribute('aria-hidden', 'true');
    }
  });
}

async function init() {
  initHistoryPagination();
  initDisclaimerModal();
  initAnalysisModal();
  initReportDetailsModal();
  initNextAnalysis();
  await Promise.all([
    renderGameIdentity(),
    renderOverview(),
    renderHistory(),
    renderRankings(),
    renderTechnicalStrategies(),
    renderNextAnalysis(),
    renderLastCycle(),
    renderWins()
  ]);
  initScrollSpy();
  const status = document.getElementById('report-status');
  if (status) status.textContent = 'Report ready';
}

init();

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function (err) {
      console.log('Service Worker reg error:', err);
    });
  });
}

// PWA Install Handler
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', function (event) {
  event.preventDefault();
  deferredPrompt = event;
  const btn = document.getElementById('pwa-install-btn');
  if (btn) {
    btn.style.display = 'inline-flex';
    btn.addEventListener('click', function () {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function () {
        deferredPrompt = null;
        btn.style.display = 'none';
      });
    });
  }
});
