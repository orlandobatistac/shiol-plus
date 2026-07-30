const API = '';

function stateMarkup(type, title, message) {
  return [
    '<div class="ui-state ui-state-' + type + '" role="status">',
      '<span class="ui-state-marker" aria-hidden="true"></span>',
      '<div><strong>' + title + '</strong><p>' + message + '</p></div>',
    '</div>'
  ].join('');
}

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

function strategyName(value) {
  const normalized = String(value || '').replace(/_(mega_millions|cash5)$/, '');
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

function drawDays(value) {
  const str = String(value || '').toLowerCase();
  if (str.includes('sun') && str.includes('mon') && str.includes('sat')) return 'Todos los Días';
  const labels = { mon: 'Lun', tue: 'Mar', wed: 'Mié', thu: 'Jue', fri: 'Vie', sat: 'Sáb', sun: 'Dom' };
  return String(value || '').split(',').map(function (day) {
    return labels[day.trim().toLowerCase()] || day.trim();
  }).join(' / ');
}

async function loadGameStats(gameId) {
  const overview = await api('/api/overview?game=' + gameId) || {};
  const performance = overview.performance || {};
  const jackpot = overview.jackpot || {};
  const top = overview.top_strategy || null;

  return {
    topStrategy: top ? strategyName(top.strategy_id || top.name) : 'No disponible',
    totalWon: Number(performance.total_won || 0),
    evaluatedDraws: Number(performance.evaluated_draws || 0),
    jackpot: jackpot.found ? Number(jackpot.amount || 0) : 0
  };
}

function activeReport(game, stats) {
  const gameClass = game.id === 'powerball' ? 'powerball' :
    (game.id === 'mega_millions' ? 'mega' : 'cash5');
  const jackpotText = stats.jackpot ? money(stats.jackpot) : 'No disponible';
  const wonText = money(stats.totalWon);
  
  return [
    '<a class="game-report ' + gameClass + '" href="game.html?game=' + game.id + '">',
      '<div class="game-report-head">',
        '<div class="game-title-group">',
          '<span class="game-marker" aria-hidden="true"></span>',
          '<h3>' + game.name + '</h3>',
        '</div>',
        '<span class="game-days-badge">' + drawDays(game.draw_days) + '</span>',
      '</div>',
      '<div class="game-jackpot-block">',
        '<span class="card-label">Jackpot Estimado</span>',
        '<strong class="jackpot-value">' + jackpotText + '</strong>',
      '</div>',
      '<div class="game-report-metrics">',
        '<div class="metric-col">',
          '<span class="card-label">Modelo Líder</span>',
          '<strong class="metric-val">' + stats.topStrategy + '</strong>',
        '</div>',
        '<div class="metric-col">',
          '<span class="card-label">Premios Generados</span>',
          '<strong class="metric-val">' + wonText + ' <small>(' + stats.evaluatedDraws + ' sorteos)</small></strong>',
        '</div>',
      '</div>',
      '<div class="game-report-footer">',
        '<span>Explorar Estrategias</span>',
        '<span class="report-arrow" aria-hidden="true">&rarr;</span>',
      '</div>',
    '</a>'
  ].join('');
}

function inactiveReport(game) {
  return [
    '<div class="game-report is-inactive">',
      '<div class="game-report-head">',
        '<div class="game-title-group"><h3>' + game.name + '</h3></div>',
        '<span class="game-days-badge">Próximamente</span>',
      '</div>',
    '</div>'
  ].join('');
}

async function renderGames() {
  const grid = document.getElementById('games-grid');
  const games = await api('/api/games');

  if (!games || !games.length) {
    grid.innerHTML = stateMarkup(
      games ? 'empty' : 'error',
      games ? 'No hay reportes activos aún' : 'Reportes no disponibles temporalmente',
      games ? 'Los reportes aparecerán cuando se active un juego.' : 'Por favor reintenta cuando el servicio esté disponible.'
    );
    return;
  }

  const activeGames = games.filter(function (game) { return game.active; });
  const stats = await Promise.all(activeGames.map(function (game) {
    return loadGameStats(game.id);
  }));
  const statsByGame = {};
  activeGames.forEach(function (game, index) { statsByGame[game.id] = stats[index]; });

  grid.innerHTML = games.map(function (game) {
    return game.active ? activeReport(game, statsByGame[game.id]) : inactiveReport(game);
  }).join('');
}

renderGames();
