const API = '';
const GAME = new URLSearchParams(location.search).get('game') || 'powerball';
const ET_TZ = 'America/New_York';
const DRAW_HOUR_ET = 22;
const DRAW_MIN_ET = 59;
const DAY_ABBR = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };

let gameInfoPromise = null;
let countdownTimer = null;
let strategyNamesCache = {};
let lastFocusedElement = null;

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

function roi(value) {
  const number = Number(value || 0);
  const percent = (number * 100).toFixed(1);
  return '<span class="' + (number >= 0 ? 'pos' : 'neg') + '">' +
    (number >= 0 ? '+' : '') + percent + '%</span>';
}

function strategyName(value) {
  const normalized = String(value || '').replace(/_mega_millions$/, '');
  const names = {
    xgboost_ml: 'XGBoost ML',
    hybrid_ensemble: 'Hybrid Ensemble',
    frequency_weighted: 'Frequency Weighted',
    intelligent_scoring: 'Intelligent Scoring',
    coverage_optimizer: 'Coverage Optimizer',
    cooccurrence: 'Cooccurrence',
    range_balanced: 'Range Balanced',
    random_baseline: 'Random Baseline'
  };
  return names[normalized] || normalized.replace(/_/g, ' ').replace(/\b\w/g, function (character) {
    return character.toUpperCase();
  });
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

function ballsHTML(numbers, extra) {
  const whiteBalls = (numbers || []).map(function (number) {
    return '<span class="ball">' + String(number).padStart(2, '0') + '</span>';
  }).join('');
  const extraBall = extra == null ? '' :
    '<span class="ball extra">' + String(extra).padStart(2, '0') + '</span>';
  return whiteBalls + extraBall;
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

async function renderGameIdentity() {
  const game = await getGameInfo();
  document.title = 'SHIOL+ | ' + game.name + ' strategy report';
  document.body.classList.toggle('game-mega', GAME === 'mega_millions');

  const title = document.getElementById('report-title');
  const description = document.getElementById('report-description');
  title.textContent = game.name + ' strategy report';
  description.textContent =
    'Eight strategies measured by win rate and total prizes across evaluated ' +
    game.name + ' tickets.';

  document.querySelectorAll('.game-switcher a').forEach(function (link) {
    const active = link.dataset.game === GAME;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
  });

  const footer = document.getElementById('page-footer');
  if (footer) {
    footer.innerHTML =
      '<span>SHIOL+ v9</span><span>' + game.name +
      ' data updates after every published draw.</span>';
  }
}

async function renderDraw() {
  const draws = await api('/api/draws?game=' + GAME + '&limit=1');
  if (!draws || !draws.length) {
    document.getElementById('draw-balls').innerHTML =
      '<span class="summary-secondary">No result available</span>';
    return;
  }
  const draw = draws[0];
  document.getElementById('draw-balls').innerHTML =
    ballsHTML([draw.n1, draw.n2, draw.n3, draw.n4, draw.n5], draw.pb);
  document.getElementById('draw-date').textContent = '- ' + dateLabel(draw.draw_date, {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
  });
}

function getEtNowParts() {
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
  formatter.formatToParts(new Date()).forEach(function (part) {
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

function nextDrawDate(drawDays) {
  const targets = new Set(drawDays.map(function (day) {
    return DAY_ABBR[day.trim().toLowerCase()];
  }));
  const now = new Date();
  const et = getEtNowParts();
  const etNowAsUtc = Date.UTC(et.year, et.month - 1, et.day, et.hour, et.minute, et.second);
  const offsetMs = now.getTime() - etNowAsUtc;

  for (let addDays = 0; addDays <= 7; addDays += 1) {
    const weekday = (et.weekday + addDays) % 7;
    if (!targets.has(weekday)) continue;
    const targetWallAsUtc = Date.UTC(
      et.year, et.month - 1, et.day + addDays, DRAW_HOUR_ET, DRAW_MIN_ET, 0
    );
    const target = new Date(targetWallAsUtc + offsetMs);
    if (target.getTime() > now.getTime()) return target;
  }
  return null;
}

async function renderCountdown() {
  const game = await getGameInfo();
  const drawDays = game.draw_days.split(',');
  const value = document.getElementById('countdown-value');
  const label = document.getElementById('next-draw-label');

  function tick() {
    const target = nextDrawDate(drawDays);
    if (!target) {
      value.textContent = 'Schedule unavailable';
      label.textContent = '';
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

async function renderJackpot() {
  const amount = document.getElementById('jackpot-amount');
  const sub = document.getElementById('jackpot-sub');
  const data = await api('/api/jackpot?game=' + GAME);

  if (!data || !data.found) {
    amount.textContent = 'Not available';
    sub.textContent = 'No current estimate';
    return;
  }

  amount.textContent = money(data.amount);
  sub.textContent = 'Cash value ' + money(data.cash_value) +
    (data.stale ? ' - estimate may be outdated' : '');
}

async function renderRankings() {
  const data = await api('/api/ticket-performance?game=' + GAME);
  const body = document.getElementById('podium');

  if (!data || !data.length) {
    body.innerHTML = '<div class="empty-state">No evaluated tickets yet.</div>';
    return;
  }

  body.innerHTML = data.map(function (strategy, index) {
    const totalWon = Number(strategy.total_won || 0);
    return [
      '<div class="ranking-row ' + (index === 0 ? 'is-leading' : '') + '" role="row">',
        '<span class="ranking-rank">' + (index + 1) + '</span>',
        '<span class="ranking-name">' + strategyName(strategy.strategy_id) + '</span>',
        '<span class="metric">' + Number(strategy.win_rate || 0).toFixed(1) + '%</span>',
        '<span class="metric desktop-only">' + Number(strategy.total_tickets || 0).toLocaleString() + '</span>',
        '<span class="metric ' + (totalWon > 0 ? 'positive' : '') + '">' + money(totalWon) + '</span>',
      '</div>'
    ].join('');
  }).join('');
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
    return [
      '<tr>',
        '<td>' + (index + 1) + '</td>',
        '<td><strong>' + strategyName(strategy.id || strategy.name) + '</strong></td>',
        '<td><span class="pill">' + String(strategy.status || 'active') + '</span></td>',
        '<td><div class="weight-bar-wrap"><div class="weight-bar"><div class="weight-fill" style="width:' +
          fill + '%"></div></div><span class="weight-val">' + weight.toFixed(4) + '</span></div></td>',
        '<td id="spark-' + strategy.id + '"><span class="spark-empty">Loading</span></td>',
        '<td>' + roi(strategy.avg_roi) + '</td>',
        '<td>' + money(strategy.lifetime_prize || 0) + '</td>',
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
  meta.textContent = 'Draw ' + dateLabel(cycle.draw_date) + ': ' +
    [cycle.n1, cycle.n2, cycle.n3, cycle.n4, cycle.n5].join(' - ') +
    ' / ' + cycle.pb;

  body.innerHTML = results.map(function (result) {
    const delta = Number(result.weight_after || 0) - Number(result.weight_before || 0);
    return [
      '<tr>',
        '<td>' + strategyName(result.strategy_id) + '</td>',
        '<td>' + result.tickets_count + '</td>',
        '<td>' + Number(result.matches_3 || 0) + '</td>',
        '<td>' + Number(result.matches_4 || 0) + '</td>',
        '<td>' + Number(result.matches_5 || 0) + '</td>',
        '<td>' + money(result.total_prize || 0) + '</td>',
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
  if (normalized === 'match1+pb') return '1 number + Powerball';
  if (normalized === 'match2+pb') return '2 numbers + Powerball';
  if (normalized === 'match3') return '3 numbers';
  if (normalized === 'match3+pb') return '3 numbers + Powerball';
  if (normalized === 'match4') return '4 numbers';
  if (normalized === 'match4+pb') return '4 numbers + Powerball';
  if (normalized === 'match5') return '5 numbers';
  if (normalized === 'jackpot') return 'Jackpot';
  return titleCase(String(value || 'Verified prize').replace(/\+/g, ' + '));
}

async function renderWins() {
  const data = await api('/api/wins?game=' + GAME);
  const list = document.getElementById('wins-grid');
  const total = document.getElementById('wins-total');

  if (!data || !data.total_count) {
    total.textContent = '';
    list.innerHTML = '<div class="empty-state">No verified prizes recorded yet.</div>';
    return;
  }

  total.innerHTML = '<strong>' + money(data.total_amount) + '</strong> across ' +
    Number(data.total_count).toLocaleString() + ' wins';

  list.innerHTML = (data.wins || []).slice(0, 6).map(function (win) {
    const numbers = parseNumbers(win.numbers);
    return [
      '<div class="win-row">',
        '<span class="win-date">' + dateLabel(win.draw_date || (win.created_at || '').slice(0, 10), {
          month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
        }) + '</span>',
        '<span class="win-strategy">' + strategyName(win.strategy_id) + '</span>',
        '<span class="win-match">' + prizeLabel(win.prize_level) + '</span>',
        '<span class="win-numbers"><span class="draw-balls">' +
          ballsHTML(numbers, win.extra) + '</span></span>',
        '<span class="win-amount">' + money(win.prize_amount || 0) + '</span>',
      '</div>'
    ].join('');
  }).join('');
}

async function renderNextTickets() {
  const strategies = await api('/api/strategies?game=' + GAME);
  const list = document.getElementById('next-tickets-grid');
  const toggle = document.getElementById('tickets-toggle');

  if (!strategies || !strategies.length) {
    list.innerHTML = '<div class="empty-state">No strategies are available.</div>';
    return;
  }

  strategies.forEach(function (strategy) {
    strategyNamesCache[strategy.id] = strategyName(strategy.id);
  });

  const previews = await Promise.all(strategies.map(function (strategy) {
    return api('/api/upcoming-tickets?game=' + GAME + '&strategy=' + strategy.id);
  }));

  list.innerHTML = strategies.map(function (strategy, index) {
    const previewData = previews[index];
    const ticket = previewData && previewData.found && previewData.tickets.length ?
      previewData.tickets[0] : null;
    const classes = 'strategy-ticket-row' + (index >= 3 ? ' is-extra' : '');
    return [
      '<button class="' + classes + '" type="button" data-strategy="' + strategy.id + '"' +
        (ticket ? '' : ' disabled') + '>',
        '<span class="strategy-name">' + strategyName(strategy.id) + '</span>',
        '<span class="draw-balls">' + (ticket ?
          ballsHTML([ticket.n1, ticket.n2, ticket.n3, ticket.n4, ticket.n5], ticket.extra) :
          '<span class="summary-secondary">Not generated yet</span>') + '</span>',
        '<span class="ticket-action">' + (ticket ? 'View 20' : 'Unavailable') + '</span>',
      '</button>'
    ].join('');
  }).join('');

  list.querySelectorAll('.strategy-ticket-row:not([disabled])').forEach(function (button) {
    button.addEventListener('click', function () {
      openTicketsModal(button.dataset.strategy);
    });
  });

  if (strategies.length > 3) {
    toggle.hidden = false;
    toggle.setAttribute('aria-expanded', 'false');
  }
}

function initTicketToggle() {
  const toggle = document.getElementById('tickets-toggle');
  const list = document.getElementById('next-tickets-grid');
  toggle.addEventListener('click', function () {
    const showAll = list.classList.toggle('show-all');
    toggle.textContent = showAll ? 'Show fewer strategies' : 'View all strategies';
    toggle.setAttribute('aria-expanded', String(showAll));
  });
}

async function openTicketsModal(strategyId) {
  const overlay = document.getElementById('tickets-modal-overlay');
  const close = document.getElementById('tickets-modal-close');
  const title = document.getElementById('tickets-modal-title');
  const sub = document.getElementById('tickets-modal-sub');
  const list = document.getElementById('tickets-modal-list');

  lastFocusedElement = document.activeElement;
  title.textContent = strategyNamesCache[strategyId] || strategyName(strategyId);
  sub.textContent = 'Loading upcoming combinations...';
  list.innerHTML = '';
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  close.focus();

  const data = await api('/api/upcoming-tickets?game=' + GAME + '&strategy=' + strategyId);
  if (!data || !data.found || !data.tickets.length) {
    sub.textContent = 'No tickets have been generated for the next draw.';
    return;
  }

  sub.textContent = '20 tickets for ' + dateLabel(data.draw_date) +
    '. Confidence reflects each model score.';
  list.innerHTML = data.tickets.map(function (ticket, index) {
    return [
      '<div class="modal-ticket-row">',
        '<span class="ticket-rank">' + (index + 1) + '</span>',
        '<span class="draw-balls">' +
          ballsHTML([ticket.n1, ticket.n2, ticket.n3, ticket.n4, ticket.n5], ticket.extra) +
        '</span>',
        '<span class="ticket-confidence">' +
          Math.round(Number(ticket.confidence || 0) * 100) + '%</span>',
      '</div>'
    ].join('');
  }).join('');
}

function closeTicketsModal() {
  const overlay = document.getElementById('tickets-modal-overlay');
  if (!overlay.classList.contains('open')) return;
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
    lastFocusedElement.focus();
  }
}

function initTicketsModal() {
  const overlay = document.getElementById('tickets-modal-overlay');
  const close = document.getElementById('tickets-modal-close');

  close.addEventListener('click', closeTicketsModal);
  overlay.addEventListener('click', function (event) {
    if (event.target === overlay) closeTicketsModal();
  });
  document.addEventListener('keydown', function (event) {
    if (!overlay.classList.contains('open')) return;
    if (event.key === 'Escape') closeTicketsModal();
    if (event.key === 'Tab') {
      event.preventDefault();
      close.focus();
    }
  });
}

function initScrollSpy() {
  const links = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('#overview, #rankings, #next-tickets, #wins');
  const observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      links.forEach(function (link) {
        link.classList.toggle('active', link.getAttribute('href') === '#' + entry.target.id);
      });
    });
  }, { rootMargin: '-20% 0px -65% 0px', threshold: 0 });
  sections.forEach(function (section) { observer.observe(section); });
}

async function init() {
  initTicketsModal();
  initTicketToggle();
  await Promise.all([
    renderGameIdentity(),
    renderCountdown(),
    renderJackpot(),
    renderDraw(),
    renderRankings(),
    renderTechnicalStrategies(),
    renderNextTickets(),
    renderLastCycle(),
    renderWins()
  ]);
  initScrollSpy();
}

init();
