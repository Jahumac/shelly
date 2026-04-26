/**
 * ChartHelpers — shared Chart.js scaffolding.
 * Loaded after Chart.js CDN in base.html; exposes window.ChartHelpers.
 */
(function (global) {
  'use strict';

  function readVar(name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function colors() {
    return {
      accent:     readVar('--accent',          '#60a5fa'),
      accent2:    readVar('--accent-2',        '#34d399'),
      primary:    readVar('--primary',         '#60a5fa'),
      muted:      readVar('--muted',           '#94a3b8'),
      grid:       readVar('--chart-grid',      'rgba(148, 163, 184, 0.12)'),
      gridAlt:    readVar('--chart-grid-alt',  'rgba(148, 163, 184, 0.08)'),
      chartBg:    readVar('--chart-bg-deep',   '#0b1220'),
      panel2:     readVar('--panel-2',         '#1e293b'),
      border:     readVar('--border',          '#334155'),
      textWhite:  readVar('--text-white',      '#ffffff'),
    };
  }

  // £ tooltip callback. decimals=0 for whole-pound, 2 for pence.
  function gbpTooltip(decimals) {
    var d = (decimals == null) ? 0 : decimals;
    return {
      callbacks: {
        label: function (ctx) {
          var label = ctx.dataset && ctx.dataset.label ? ctx.dataset.label + ': ' : '';
          return ' ' + label + '£' + ctx.parsed.y.toLocaleString('en-GB', {
            minimumFractionDigits: d,
            maximumFractionDigits: d,
          });
        }
      }
    };
  }

  /**
   * Common line-chart options. Pass { tooltip, extraScales, extra } to override.
   * - tooltip: full plugins.tooltip object (e.g. gbpTooltip(0)).
   * - extraScales: merged into scales.x / scales.y beyond the grid/ticks defaults.
   * - extra: merged into top-level options after defaults.
   */
  function lineOptions(opts) {
    opts = opts || {};
    var c = colors();
    var base = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: { grid: { color: c.grid }, ticks: { color: c.muted, font: { size: 11 } } },
        y: { grid: { color: c.grid }, ticks: { color: c.muted, font: { size: 11 } } },
      },
    };
    if (opts.tooltip) base.plugins.tooltip = opts.tooltip;
    if (opts.extraScales) {
      if (opts.extraScales.x) Object.assign(base.scales.x, opts.extraScales.x);
      if (opts.extraScales.y) Object.assign(base.scales.y, opts.extraScales.y);
    }
    if (opts.extra) Object.assign(base, opts.extra);
    return base;
  }

  /**
   * Common line dataset shape. Caller provides values + color; rest has sensible defaults.
   * - fillAlphaHex: 2-char hex appended to color for fill tint (e.g. '14', '22'). Pass null to disable fill.
   * - pointCutoff: max series length at which points are shown (beyond this, pointRadius=0).
   */
  function lineDataset(cfg) {
    cfg = cfg || {};
    var color = cfg.color;
    var values = cfg.values || [];
    var cutoff = (cfg.pointCutoff == null) ? 24 : cfg.pointCutoff;
    var hasBg = cfg.backgroundColor != null;
    var hasHex = cfg.fillAlphaHex != null;
    var fill = hasBg || hasHex;
    var bg = hasBg ? cfg.backgroundColor : (hasHex ? (color + cfg.fillAlphaHex) : 'transparent');
    return {
      data: values,
      borderColor: color,
      backgroundColor: bg,
      borderWidth: cfg.borderWidth || 2,
      pointRadius: (cfg.pointRadius != null) ? cfg.pointRadius : (values.length <= cutoff ? 3 : 0),
      pointBackgroundColor: color,
      fill: fill,
      tension: (cfg.tension != null) ? cfg.tension : 0.25,
    };
  }

  global.ChartHelpers = {
    colors: colors,
    gbpTooltip: gbpTooltip,
    lineOptions: lineOptions,
    lineDataset: lineDataset,
  };

  /**
   * Automatic initialization of charts based on data- attributes.
   * Scans for canvases with specific IDs or data attributes on load.
   */
  document.addEventListener('DOMContentLoaded', function () {
    var c = colors();

    // ── 1. Holding Detail History Chart ──────────────────────────────────────
    (function initHistoryChart() {
      var canvas = document.getElementById('historyChart');
      if (!canvas) return;
      var rawData = JSON.parse(canvas.dataset.history || '[]');
      if (!rawData.length) return;

      var labels = rawData.map(function(d) { return d.date; });
      var values = rawData.map(function(d) { return d.price; });
      var ctx = canvas.getContext('2d');

      var benchmarkRaw = canvas.dataset.benchmark ? JSON.parse(canvas.dataset.benchmark) : null;
      var benchmarkValues = benchmarkRaw ? benchmarkRaw.map(function(d) { return d.price; }) : null;

      if (typeof window.Chart === 'function') {
        var gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 220);
        gradient.addColorStop(0, c.accent + '33');
        gradient.addColorStop(1, c.accent + '00');

        var datasets = [{
          label: 'Price',
          data: values,
          borderColor: c.accent,
          backgroundColor: gradient,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointBackgroundColor: c.accent,
          fill: true,
          tension: 0.2
        }];

        if (benchmarkValues) {
          datasets.push({
            label: 'Benchmark',
            data: benchmarkValues,
            borderColor: 'rgba(251,191,36,0.7)',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            borderDash: [5, 4],
            pointRadius: 0,
            pointHoverRadius: 3,
            pointBackgroundColor: 'rgba(251,191,36,0.7)',
            fill: false,
            tension: 0.2
          });
        }

        new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: datasets
          },
          options: lineOptions({
            tooltip: { intersect: false, mode: 'index' },
            extraScales: {
              x: { ticks: { color: c.muted, font: { size: 11 }, maxTicksLimit: 6 } }
            }
          })
        });
      } else {
        drawFallback(canvas, values, c.accent);
      }
    })();

    // ── 2. Account Allocation Doughnut ───────────────────────────────────────
    (function initAllocChart() {
      var canvas = document.getElementById('allocChart');
      if (!canvas) return;
      var palette = JSON.parse(canvas.dataset.palette || '[]');
      var labels  = JSON.parse(canvas.dataset.labels  || '[]');
      var values  = JSON.parse(canvas.dataset.values  || '[]');
      var pcts    = JSON.parse(canvas.dataset.pcts    || '[]');
      var total   = canvas.dataset.total || '£0.00';
      var colors  = labels.map(function(_, i) { return palette[i % palette.length]; });

      if (typeof window.Chart !== 'function') return;

      var centerPlugin = {
        id: 'centerText',
        afterDraw: function(chart) {
          var ctx = chart.ctx;
          var ca  = chart.chartArea;
          var cx  = (ca.left + ca.right)  / 2;
          var cy  = (ca.top  + ca.bottom) / 2;
          var active = chart.getActiveElements();
          ctx.save();
          ctx.textAlign    = 'center';
          ctx.textBaseline = 'middle';
          if (active.length > 0) {
            var idx = active[0].index;
            var pct = pcts[idx].toFixed(1) + '%';
            var val = '£' + values[idx].toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
            ctx.font      = 'bold 26px Inter, system-ui, sans-serif';
            ctx.fillStyle = c.textWhite;
            ctx.fillText(pct, cx, cy - 9);
            ctx.font      = '600 12px Inter, system-ui, sans-serif';
            ctx.fillStyle = c.muted;
            ctx.fillText(val, cx, cy + 13);
          } else {
            ctx.font      = 'bold 15px Inter, system-ui, sans-serif';
            ctx.fillStyle = c.textWhite;
            ctx.fillText(total, cx, cy - 8);
            ctx.font      = '10px Inter, system-ui, sans-serif';
            ctx.fillStyle = c.muted;
            ctx.fillText('TOTAL TRACKED', cx, cy + 10);
          }
          ctx.restore();
        }
      };

      var chart = new Chart(canvas.getContext('2d'), {
        type: 'doughnut',
        plugins: [centerPlugin],
        data: {
          labels: labels,
          datasets: [{
            data: values,
            backgroundColor: colors,
            hoverBackgroundColor: colors,
            borderWidth: 3,
            borderColor: c.chartBg,
            hoverBorderColor: c.textWhite,
            hoverBorderWidth: 2,
            hoverOffset: 8,
          }]
        },
        options: {
          cutout: '68%',
          responsive: false,
          layout: { padding: 14 },
          animation: { animateRotate: true, duration: 700, easing: 'easeInOutQuart' },
          plugins: {
            legend:  { display: false },
            tooltip: { enabled: false },
          },
          onHover: function(event, activeElements) {
            canvas.style.cursor = activeElements.length ? 'pointer' : 'default';
            highlightAllocList(activeElements.length ? activeElements[0].index : -1, colors);
          }
        }
      });

      // Bidirectional highlight
      document.querySelectorAll('.allocation-item[data-index]').forEach(function(item) {
        item.addEventListener('mouseenter', function() {
          var idx = parseInt(item.dataset.index);
          highlightAllocList(idx, colors);
          chart.setActiveElements([{ datasetIndex: 0, index: idx }]);
          chart.update('none');
        });
        item.addEventListener('mouseleave', function() {
          highlightAllocList(-1, colors);
          chart.setActiveElements([]);
          chart.update('none');
        });
      });
    })();

    // ── 3. Account Monthly/Daily History Chart ───────────────────────────────
    (function initAcctChart() {
      var canvas = document.getElementById('acctMonthlyChart');
      if (!canvas) return;
      var dailyLabels   = JSON.parse(canvas.dataset.dailyLabels   || '[]');
      var dailyValues   = JSON.parse(canvas.dataset.dailyValues   || '[]');
      var monthlyLabels = JSON.parse(canvas.dataset.monthlyLabels || '[]');
      var monthlyValues = JSON.parse(canvas.dataset.monthlyValues || '[]');
      var ctx = canvas.getContext('2d');
      var chartInstance = null;

      function getSlice(mode, range) {
        var src = mode === 'daily'
          ? { labels: dailyLabels, values: dailyValues }
          : { labels: monthlyLabels, values: monthlyValues };
        if (!range || range <= 0 || range >= src.labels.length) return src;
        return { labels: src.labels.slice(-range), values: src.values.slice(-range) };
      }

      function renderChart(mode, range) {
        var d = getSlice(mode, range);
        if (typeof window.Chart === 'function') {
          if (chartInstance) {
            chartInstance.data.labels = d.labels;
            chartInstance.data.datasets[0].data = d.values;
            chartInstance.update();
          } else {
            chartInstance = new Chart(ctx, {
              type: 'line',
              data: {
                labels: d.labels,
                datasets: [lineDataset({ values: d.values, color: c.primary, fillAlphaHex: '22' })]
              },
              options: lineOptions()
            });
          }
        } else {
          drawFallback(canvas, d.values, c.primary);
        }
      }

      var pills = document.querySelectorAll('.chart-range-pill');
      var activePill = document.querySelector('.chart-range-pill-active');
      if (activePill) {
        renderChart(activePill.dataset.mode || 'daily', parseInt(activePill.dataset.range) || 0);
      } else if (pills.length) {
        renderChart(pills[0].dataset.mode || 'daily', parseInt(pills[0].dataset.range) || 0);
      }

      pills.forEach(function(pill) {
        pill.addEventListener('click', function() {
          pills.forEach(function(p) { p.classList.remove('chart-range-pill-active'); });
          pill.classList.add('chart-range-pill-active');
          renderChart(pill.dataset.mode || 'daily', parseInt(pill.dataset.range) || 0);
        });
      });
    })();

    // ── 4. Performance Chart ────────────────────────────────────────────────
    (function initPerfChart() {
      var canvas = document.getElementById('perfChart');
      if (!canvas || typeof window.Chart !== 'function') return;
      var labels  = JSON.parse(canvas.dataset.labels  || '[]');
      var actual  = JSON.parse(canvas.dataset.actual  || '[]');
      var plan    = JSON.parse(canvas.dataset.plan    || '[]');
      var bench   = JSON.parse(canvas.dataset.bench   || '[]');
      var assumedRate = canvas.dataset.assumedRate || '';
      var benchmarkRate = canvas.dataset.benchmarkRate || '';

      var datasets = [
        {
          label: 'Actual',
          data: actual,
          borderColor: c.accent2,
          backgroundColor: c.accent2 + '14',
          fill: true,
          tension: 0.35,
          pointRadius: actual.length <= 24 ? 4 : 2,
          pointHoverRadius: 6,
          borderWidth: 2,
        },
        {
          label: 'Plan (' + assumedRate + '%)',
          data: plan,
          borderColor: c.muted + '80',
          borderDash: [6, 4],
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 1.5,
        },
      ];

      if (bench.length) {
        datasets.push({
          label: 'Benchmark (' + benchmarkRate + '%)',
          data: bench,
          borderColor: c.accent,
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          borderWidth: 1.5,
        });
      }

      new Chart(canvas, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: lineOptions({
          tooltip: {
            backgroundColor: c.panel2,
            borderColor: c.border,
            borderWidth: 1,
            callbacks: {
              label: function(ctx) {
                return ' ' + ctx.dataset.label + ': £' + Math.round(ctx.parsed.y).toLocaleString('en-GB');
              }
            }
          },
          extraScales: {
            x: { grid: { color: c.gridAlt }, ticks: { color: c.muted, maxRotation: 0, maxTicksLimit: 6, callback: function(val, idx) { var lbl = labels[idx] || ''; var parts = lbl.split(' '); return parts.length >= 2 ? parts[0] + ' ' + parts[1] : lbl; } } },
            y: { grid: { color: c.gridAlt }, ticks: { color: c.muted, callback: function(v) { return '£' + Math.round(v).toLocaleString('en-GB'); } } }
          },
          extra: { interaction: { mode: 'index', intersect: false } }
        })
      });
    })();

    // ── 5. Projections Chart ────────────────────────────────────────────────
    (function initProjectionChart() {
      var canvas = document.getElementById('projectionChart');
      if (!canvas || typeof window.Chart !== 'function') return;
      var labels = JSON.parse(canvas.dataset.labels || '[]');
      var values = JSON.parse(canvas.dataset.values || '[]');

      new Chart(canvas, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [lineDataset({
            values: values,
            color: c.accent2,
            fillAlphaHex: '12',
            pointCutoff: 20,
            tension: 0.3,
          })]
        },
        options: lineOptions({
          tooltip: gbpTooltip(0),
          extraScales: {
            x: { ticks: { color: c.muted, font: { size: 11 }, maxTicksLimit: 10 } },
            y: { ticks: { color: c.muted, font: { size: 11 }, callback: function(v) { return '£' + (v/1000).toFixed(0) + 'k'; } } }
          }
        })
      });
    })();

    // ── 6. Overview Allocation Chart ─────────────────────────────────────────
    (function initOverviewAllocChart() {
      var canvas = document.getElementById('allocationChart');
      if (!canvas || typeof window.Chart !== 'function') return;
      var labels = JSON.parse(canvas.dataset.labels || '[]');
      var values = JSON.parse(canvas.dataset.values || '[]');
      var palette = [
        c.accent, c.accent2,
        '#f59e0b', '#10b981', '#8b5cf6', '#ef4444',
        '#06b6d4', '#f97316', '#84cc16', '#ec4899',
        '#6366f1', '#14b8a6',
      ];

      labels.forEach(function(_, i) {
        document.querySelectorAll('.alloc-dot-' + i).forEach(function(el) {
          el.style.background = palette[i % palette.length];
        });
      });

      function highlightRow(idx) {
        document.querySelectorAll('.allocation-legend-row[data-index]').forEach(function(row) {
          var i = parseInt(row.dataset.index);
          if (idx >= 0 && i === idx) {
            var col = palette[i % palette.length];
            row.style.outline = '1px solid ' + col;
            row.style.boxShadow = '0 0 0 1px ' + col + '55, 0 4px 16px ' + col + '25';
            row.style.transform = 'translateX(4px)';
          } else {
            row.style.outline = '';
            row.style.boxShadow = '';
            row.style.transform = '';
          }
        });
      }

      var chart = new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: values,
            backgroundColor: palette.slice(0, labels.length),
            hoverBackgroundColor: palette.slice(0, labels.length),
            borderWidth: 2,
            borderColor: c.panel2 || '#1e293b',
            hoverBorderColor: '#ffffff',
            hoverBorderWidth: 2,
            hoverOffset: 8,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%',
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: c.panel2,
              borderColor: c.border,
              borderWidth: 1,
              callbacks: {
                label: function(ctx) {
                  var total = ctx.dataset.data.reduce(function(a, b) { return a + b; }, 0);
                  var pct = total > 0 ? (ctx.parsed / total * 100).toFixed(1) : '0.0';
                  return ' £' + Math.round(ctx.parsed).toLocaleString('en-GB') + ' (' + pct + '%)';
                }
              }
            }
          },
          onHover: function(event, activeElements) {
            canvas.style.cursor = activeElements.length ? 'pointer' : 'default';
            highlightRow(activeElements.length ? activeElements[0].index : -1);
          }
        }
      });

      document.querySelectorAll('.allocation-legend-row[data-index]').forEach(function(row) {
        row.addEventListener('mouseenter', function() {
          var idx = parseInt(row.dataset.index);
          highlightRow(idx);
          chart.setActiveElements([{ datasetIndex: 0, index: idx }]);
          chart.update('none');
        });
        row.addEventListener('mouseleave', function() {
          highlightRow(-1);
          chart.setActiveElements([]);
          chart.update('none');
        });
      });
    })();

    // ── 7. Overview Net Worth Chart ──────────────────────────────────────────
    (function initNetWorthChart() {
      var canvas = document.getElementById('netWorthChart');
      if (!canvas || typeof window.Chart !== 'function') return;
      var labels = JSON.parse(canvas.dataset.labels || '[]');
      var values = JSON.parse(canvas.dataset.values || '[]');

      var fmtLabels = labels.map(function(k) {
        var parts = k.split('-');
        var d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, 1);
        return d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' });
      });

      new Chart(canvas, {
        type: 'line',
        data: {
          labels: fmtLabels,
          datasets: [lineDataset({
            values: values,
            color: c.accent,
            fillAlphaHex: '14',
            pointRadius: values.length <= 12 ? 4 : 2,
            tension: 0.35,
          })]
        },
        options: lineOptions({
          tooltip: gbpTooltip(0),
          extraScales: {
            y: { ticks: { color: c.muted, font: { size: 11 }, callback: function(v) { return '£' + (v >= 1000 ? (v/1000).toFixed(0) + 'k' : v); } } }
          }
        })
      });
    })();

    // ── 8. Overview Daily Portfolio Chart ────────────────────────────────────
    (function initDailyPortfolioChart() {
      var canvas = document.getElementById('dailyPortfolioChart');
      if (!canvas) return;
      var allLabels = JSON.parse(canvas.dataset.labels || '[]');
      var allValues = JSON.parse(canvas.dataset.values || '[]');
      var fallbackValue = parseFloat(canvas.dataset.fallback || '0');
      var chart = null;

      var periods = { '1D': 1, '1M': 30, '6M': 180, '1Y': 365, 'ALL': 999999 };

      function parseYMD(dateStr) {
        if (!dateStr || typeof dateStr !== 'string') return null;
        var parts = dateStr.split('-');
        if (parts.length < 3) return null;
        return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      }

      function ensureMinPoints(labels, values) {
        if (!labels.length) {
          var today = new Date();
          var yesterday = new Date(today.getTime() - 86400000);
          return {
            labels: [yesterday.toISOString().split('T')[0], today.toISOString().split('T')[0]],
            values: [fallbackValue, fallbackValue]
          };
        }
        if (labels.length === 1) {
          var dt = parseYMD(labels[0]) || new Date();
          var prev = new Date(dt.getTime() - 86400000);
          return {
            labels: [prev.toISOString().split('T')[0], labels[0]],
            values: [values[0], values[0]]
          };
        }
        return { labels: labels, values: values };
      }

      function buildSeries(period) {
        var src = ensureMinPoints(allLabels, allValues);
        var cutoffDays = periods[period] || 365;
        var today = new Date();
        var endDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        var cutoffDate = new Date(endDate.getTime() - cutoffDays * 24 * 60 * 60 * 1000);

        var points = [];
        for (var i = 0; i < src.labels.length; i++) {
          var dt = parseYMD(src.labels[i]);
          if (dt) points.push({ d: dt, s: src.labels[i], v: Number(src.values[i]) });
        }
        points.sort(function(a, b) { return a.d - b.d; });
        if (!points.length) return ensureMinPoints([], []);

        var startDate = points[0].d > cutoffDate ? points[0].d : cutoffDate;
        var labels = [], values = [];

        if (cutoffDays <= 400) {
          var map = {};
          points.forEach(function(p) { map[p.s] = p.v; });
          var lastV = fallbackValue;
          for (var k = 0; k < points.length; k++) {
            if (points[k].d < startDate) lastV = points[k].v; else break;
          }
          for (var cur = new Date(startDate); cur <= endDate; cur.setDate(cur.getDate() + 1)) {
            var s = cur.toISOString().split('T')[0];
            if (map.hasOwnProperty(s)) lastV = map[s];
            labels.push(s); values.push(lastV);
          }
        } else {
          points.forEach(function(p) {
            if (p.d >= startDate && p.d <= endDate) { labels.push(p.s); values.push(p.v); }
          });
        }
        return ensureMinPoints(labels, values);
      }

      function updateChart(period) {
        var data = buildSeries(period);
        var fmtLabels = data.labels.map(function(s) {
          var d = parseYMD(s);
          return d ? d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : s;
        });

        var dataVals = data.values.filter(isFinite);
        var yMin = dataVals.length ? Math.min.apply(null, dataVals) : 0;
        var yMax = dataVals.length ? Math.max.apply(null, dataVals) : 1;
        var yRange = yMax - yMin;
        var kDec = (yMax > 0 && yRange / yMax < 0.005) ? 2 : (yMax > 0 && yRange / yMax < 0.05 ? 1 : 0);
        var yPad = yRange > 0 ? yRange * 0.25 : yMax * 0.01;

        function fmtTick(v) {
          return v >= 1000 ? '£' + (v / 1000).toFixed(kDec) + 'k' : '£' + Math.round(v);
        }

        if (typeof window.Chart === 'function') {
          if (chart) chart.destroy();
          var ctx = canvas.getContext('2d');
          var grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 220);
          grad.addColorStop(0, c.accent + '33');
          grad.addColorStop(1, c.accent + '00');

          chart = new Chart(ctx, {
            type: 'line',
            data: {
              labels: fmtLabels,
              datasets: [lineDataset({
                values: data.values,
                color: c.accent,
                backgroundColor: grad,
                pointCutoff: 30,
                tension: 0.25
              })]
            },
            options: lineOptions({
              tooltip: gbpTooltip(2),
              extraScales: {
                y: { min: yMin - yPad, max: yMax + yPad, ticks: { color: c.muted, font: { size: 11 }, callback: fmtTick } }
              }
            })
          });
        } else {
          drawFallback(canvas, data.values, c.accent);
        }

        // Stats
        if (data.values.length) {
          var latest = data.values[data.values.length - 1];
          var first = data.values[0];
          var diff = latest - first;
          var pct = first ? (diff / first * 100) : null;
          var lEl = document.getElementById('latestValue');
          var cEl = document.getElementById('changeValue');
          if (lEl) lEl.textContent = '£' + latest.toLocaleString('en-GB', { minimumFractionDigits: 2 });
          if (cEl) {
            cEl.textContent = (diff >= 0 ? '+' : '') + diff.toLocaleString('en-GB', { minimumFractionDigits: 2 }) +
              (pct !== null ? ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)' : '');
            cEl.style.color = diff >= 0 ? 'var(--success)' : 'var(--danger)';
          }
        }
      }

      document.querySelectorAll('.period-btn').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          document.querySelectorAll('.period-btn').forEach(function(b) { b.classList.remove('active'); });
          this.classList.add('active');
          updateChart(this.dataset.period);
        });
      });

      updateChart('ALL');
    })();
  });

  /* Helpers for Doughnut interactions */
  function highlightAllocList(idx, colors) {
    var items = document.querySelectorAll('.allocation-item[data-index]');
    items.forEach(function(item) {
      var i = parseInt(item.dataset.index);
      var dot = item.querySelector('.alloc-dot');
      if (idx >= 0 && i === idx) {
        var col = colors[i % colors.length];
        item.style.borderColor = col;
        item.style.boxShadow   = '0 0 0 1px ' + col + '55, 0 4px 22px ' + col + '30';
        item.style.transform   = 'translateX(4px)';
        if (dot) dot.style.boxShadow = '0 0 7px 2px ' + col + '99';
      } else {
        item.style.borderColor = '';
        item.style.boxShadow   = '';
        item.style.transform   = '';
        if (dot) dot.style.boxShadow = '';
      }
    });
  }

  /* Fallback canvas drawing when Chart.js fails */
  function drawFallback(canvas, values, color) {
    var ctx = canvas.getContext('2d');
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(1, Math.floor(rect.width));
    var h = Math.max(1, Math.floor(rect.height));
    var dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var padL = 44, padR = 12, padT = 10, padB = 22;
    var innerW = Math.max(1, w - padL - padR);
    var innerH = Math.max(1, h - padT - padB);

    var minV = Infinity, maxV = -Infinity;
    for (var i = 0; i < values.length; i++) {
      var v = Number(values[i]);
      if (!isFinite(v)) continue;
      if (v < minV) minV = v; if (v > maxV) maxV = v;
    }
    if (!isFinite(minV) || !isFinite(maxV)) return;
    if (minV === maxV) { minV = minV * 0.999; maxV = maxV * 1.001; }

    function xFor(idx) { return values.length <= 1 ? padL + innerW / 2 : padL + (idx / (values.length - 1)) * innerW; }
    function yFor(val) { return padT + (1 - (val - minV) / (maxV - minV)) * innerH; }

    ctx.strokeStyle = 'rgba(148, 163, 184, 0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var g = 0; g <= 4; g++) {
      var y = padT + (g / 4) * innerH;
      ctx.moveTo(padL, y); ctx.lineTo(padL + innerW, y);
    }
    ctx.stroke();

    ctx.beginPath();
    for (var p = 0; p < values.length; p++) {
      var pv = Number(values[p]); if (!isFinite(pv)) continue;
      var px = xFor(p), py = yFor(pv);
      if (p === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.stroke();
  }

  global.ChartHelpers = {
    colors: colors,
    gbpTooltip: gbpTooltip,
    lineOptions: lineOptions,
    lineDataset: lineDataset,
  };
})(window);
