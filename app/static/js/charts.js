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
    var hasFill = cfg.fillAlphaHex !== null && cfg.fillAlphaHex !== undefined;
    var cutoff = (cfg.pointCutoff == null) ? 24 : cfg.pointCutoff;
    var values = cfg.values || [];
    return {
      data: values,
      borderColor: color,
      backgroundColor: hasFill ? (cfg.backgroundColor || (color + cfg.fillAlphaHex)) : 'transparent',
      borderWidth: cfg.borderWidth || 2,
      pointRadius: (cfg.pointRadius != null) ? cfg.pointRadius : (values.length <= cutoff ? 3 : 0),
      pointBackgroundColor: color,
      fill: hasFill,
      tension: (cfg.tension != null) ? cfg.tension : 0.25,
    };
  }

  global.ChartHelpers = {
    colors: colors,
    gbpTooltip: gbpTooltip,
    lineOptions: lineOptions,
    lineDataset: lineDataset,
  };
})(window);
