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
  if (str.includes('sun') && str.includes('mon') && str.includes('sat')) return 'Every Day';
  const labels = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' };
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
    topStrategy: top ? strategyName(top.strategy_id || top.name) : 'Not available',
    totalWon: Number(performance.total_won || 0),
    evaluatedDraws: Number(performance.evaluated_draws || 0),
    jackpot: jackpot.found ? Number(jackpot.amount || 0) : 0
  };
}

function activeReport(game, stats) {
  stats = stats || {};
  const gameClass = game.id === 'powerball' ? 'powerball' :
    (game.id === 'mega_millions' ? 'mega' : (game.id === 'cash5' ? 'cash5' : (game.id === 'pick3' ? 'pick3' : 'pick4')));
  const jackpotText = stats.jackpot ? money(stats.jackpot) :
    (game.game_type === 'digit' ? (game.id === 'pick3' ? '$500' : '$5,000') : 'Not available');
  const wonText = money(stats.totalWon || 0);
  const topStrategyText = stats.topStrategy || 'Not available';
  const evaluatedDrawsText = stats.evaluatedDraws || 0;
  
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
        '<span class="card-label">Estimated Jackpot</span>',
        '<strong class="jackpot-value">' + jackpotText + '</strong>',
      '</div>',
      '<div class="game-report-metrics">',
        '<div class="metric-col">',
          '<span class="card-label">Top Strategy</span>',
          '<strong class="metric-val">' + topStrategyText + '</strong>',
        '</div>',
        '<div class="metric-col">',
          '<span class="card-label">Total Won</span>',
          '<strong class="metric-val">' + wonText + ' <small>(' + evaluatedDrawsText + ' draws)</small></strong>',
        '</div>',
      '</div>',
      '<div class="game-report-footer">',
        '<span>Explore Strategies</span>',
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
        '<span class="game-days-badge">Coming Soon</span>',
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
      games ? 'No active reports yet' : 'Reports temporarily unavailable',
      games ? 'Reports will appear once a game is activated.' : 'Please retry when the service is available.'
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

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/sw.js').catch(function (err) {
      console.log('Service Worker reg error:', err);
    });
  });
}

// PWA Install Handler
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

initDisclaimerModal();

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
