(function () {
  function $(sel) { return document.querySelector(sel); }

  var canvas = $('#historyChart');
  if (!canvas) return;

  var errorEl = $('#history-chart-error');
  var controls = document.querySelectorAll('[data-history-period]');
  var holdingId = canvas.getAttribute('data-holding-id');

  try {
    var restoreKey = 'holdingHistoryScrollY';
    var y0 = sessionStorage.getItem(restoreKey);
    if (y0 !== null) {
      sessionStorage.removeItem(restoreKey);
      var yNum = Number(y0);
      if (isFinite(yNum) && yNum >= 0) {
        setTimeout(function () { window.scrollTo(0, yNum); }, 0);
      }
    }
  } catch (e) {}

  function setError(msg) {
    if (!errorEl) return;
    if (!msg) {
      errorEl.style.display = 'none';
      errorEl.textContent = '';
      return;
    }
    errorEl.style.display = 'block';
    errorEl.textContent = msg;
  }

  function setActive(period) {
    controls.forEach(function (el) {
      var p = el.getAttribute('data-history-period');
      if (p === period) {
        el.classList.add('badge-primary-action');
        el.classList.remove('badge-meta');
      } else {
        el.classList.remove('badge-primary-action');
        el.classList.add('badge-meta');
      }
    });
  }

  function getColors(ctx) {
    var S = getComputedStyle(document.documentElement);
    return {
      accent: (S.getPropertyValue('--accent').trim() || '#60a5fa'),
      grid: (S.getPropertyValue('--chart-grid').trim() || 'rgba(148, 163, 184, 0.12)'),
      muted: (S.getPropertyValue('--muted').trim() || '#94a3b8'),
      ctx: ctx
    };
  }

  function ensureChart(labels, values) {
    var ctx = canvas.getContext('2d');
    var COLORS = getColors(ctx);

    if (typeof window.Chart !== 'function') {
      setError('Chart library not available.');
      return;
    }

    if (window.__holdingHistoryChart) {
      window.__holdingHistoryChart.data.labels = labels;
      window.__holdingHistoryChart.data.datasets[0].data = values;
      window.__holdingHistoryChart.update();
      return;
    }

    var gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 220);
    gradient.addColorStop(0, COLORS.accent + '33');
    gradient.addColorStop(1, COLORS.accent + '00');

    window.__holdingHistoryChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.accent,
          backgroundColor: gradient,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointBackgroundColor: COLORS.accent,
          fill: true,
          tension: 0.2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { intersect: false, mode: 'index' } },
        scales: {
          x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.muted, font: { size: 11 }, maxTicksLimit: 6 } },
          y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.muted, font: { size: 11 } } }
        }
      }
    });
  }

  function updateUrl(period) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('period', period);
      history.replaceState(null, '', url.toString());
    } catch (e) {}
  }

  function fetchAndRender(period) {
    if (!holdingId) return;

    var y = window.scrollY || window.pageYOffset || 0;
    setError(null);

    var reqUrl = '/holdings/' + holdingId + '/history?period=' + encodeURIComponent(period);

    function fallbackNavigate() {
      try { sessionStorage.setItem('holdingHistoryScrollY', String(y)); } catch (e) {}
      var nextUrl = '/holdings/' + holdingId + '?period=' + encodeURIComponent(period);
      window.location.replace(nextUrl);
    }

    fetch(reqUrl, {
      headers: { 'Accept': 'application/json' },
      credentials: 'include',
      cache: 'no-store'
    })
      .then(function (r) {
        var ct = (r.headers.get('content-type') || '').toLowerCase();
        if (r.redirected || ct.indexOf('application/json') === -1) {
          throw new Error('non_json_response');
        }
        return r.json().then(function (payload) {
          return { ok: r.ok, status: r.status, payload: payload };
        });
      })
      .then(function (payload) {
        if (!payload.ok) {
          setError((payload.payload && payload.payload.message) || 'Could not load data. Please try again.');
          return;
        }
        var labels = payload.payload.labels || [];
        var values = payload.payload.values || [];
        if (!labels.length || !values.length) {
          setError(payload.payload.message || 'No data available for this range.');
          if (window.__holdingHistoryChart) {
            window.__holdingHistoryChart.destroy();
            window.__holdingHistoryChart = null;
          }
          return;
        }
        ensureChart(labels, values);
        setActive(period);
        updateUrl(period);
      })
      .catch(function (err) {
        if (err && err.message === 'non_json_response') {
          fallbackNavigate();
          return;
        }
        if (navigator && navigator.onLine === false) {
          setError('Offline. Reconnect and try again.');
        } else {
          fallbackNavigate();
        }
      })
      .finally(function () {
        window.scrollTo(0, y);
      });
  }

  controls.forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.preventDefault();
      var period = el.getAttribute('data-history-period');
      fetchAndRender(period);
    });
  });
})();
