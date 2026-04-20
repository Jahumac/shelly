/* app.js — Core client-side logic for Shelly Finance */

(function() {
  /* ── CSRF Protection ─────────────────────────────────────────────── */
  var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

  /* Inject CSRF into a single form element if it's missing */
  function ensureCsrf(form) {
    if (form.method && form.method.toUpperCase() === 'POST') {
      if (!form.querySelector('input[name="csrf_token"]')) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'csrf_token';
        input.value = csrfToken;
        form.insertBefore(input, form.firstChild);
      }
    }
  }

  /* Scan and inject into all current POST forms on the page */
  function injectAll() {
    document.querySelectorAll('form').forEach(ensureCsrf);
  }

  /* Run immediately (covers all static forms in the HTML) */
  document.addEventListener('DOMContentLoaded', injectAll);

  /* Also catch any forms injected dynamically by JavaScript */
  if (window.MutationObserver) {
    new MutationObserver(function(mutations) {
      mutations.forEach(function(m) {
        m.addedNodes.forEach(function(node) {
          if (node.nodeType !== 1) return;
          if (node.tagName === 'FORM') { ensureCsrf(node); return; }
          if (node.querySelectorAll) {
            node.querySelectorAll('form').forEach(ensureCsrf);
          }
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  /* Belt-and-suspenders: also catch on submit in case a form was missed */
  document.addEventListener('submit', function(e) { ensureCsrf(e.target); });

  /* Add CSRF token to all AJAX fetch POST requests */
  var originalFetch = window.fetch;
  window.fetch = function() {
    var args = Array.prototype.slice.call(arguments);
    if (args.length > 1 && args[1] && args[1].method && args[1].method.toUpperCase() === 'POST') {
      args[1].headers = args[1].headers || {};
      if (args[1].headers instanceof Headers) {
        args[1].headers.set('X-CSRFToken', csrfToken);
      } else {
        args[1].headers['X-CSRFToken'] = csrfToken;
      }
    }
    return originalFetch.apply(this, args);
  };

  /* ── Shelly confirm — replaces browser confirm() ─────────────────── */
  var overlay = document.getElementById('shelly-confirm');
  var titleEl = document.getElementById('shelly-confirm-title');
  var msgEl   = document.getElementById('shelly-confirm-msg');
  var okBtn   = document.getElementById('shelly-confirm-ok');
  var cancelBtn = document.getElementById('shelly-confirm-cancel');
  var pendingResolve = null;

  window.shellyConfirm = function (opts) {
    opts = opts || {};
    titleEl.textContent = opts.title || 'Are you sure?';
    msgEl.textContent   = opts.message || '';
    okBtn.textContent   = opts.confirmText || 'Yes, do it';
    cancelBtn.textContent = opts.cancelText || 'Nope, go back';
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    okBtn.focus();

    return new Promise(function (resolve) {
      pendingResolve = resolve;
    });
  };

  function closeConfirm(result) {
    overlay.classList.add('hidden');
    overlay.setAttribute('aria-hidden', 'true');
    if (pendingResolve) {
      pendingResolve(result);
      pendingResolve = null;
    }
  }

  if (okBtn) okBtn.addEventListener('click', function () { closeConfirm(true); });
  if (cancelBtn) cancelBtn.addEventListener('click', function () { closeConfirm(false); });
  if (overlay) overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeConfirm(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && overlay && !overlay.classList.contains('hidden')) closeConfirm(false);
  });

  /* ── Wire up all [data-confirm] elements ─────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        shellyConfirm({
          title: el.getAttribute('data-confirm-title') || 'Hang on a sec…',
          message: el.getAttribute('data-confirm'),
          confirmText: el.getAttribute('data-confirm-ok') || 'Yes, do it',
          cancelText: el.getAttribute('data-confirm-cancel') || 'Nope, go back',
        }).then(function (confirmed) {
          if (!confirmed) return;
          var form = el.closest('form');
          if (form && (el.tagName === 'BUTTON' || el.type === 'submit')) {
            form.submit();
          } else if (el.href) {
            window.location.href = el.href;
          }
        });
      });
    });
  });

  /* ── Tag sync helper ─────────────────────────────────────────────── */
  window.syncTagsInForm = function(form) {
    var tagHiddenInput = form.querySelector('[data-tags-hidden-input]');
    if (!tagHiddenInput) return;
    var checked = Array.from(form.querySelectorAll('[data-tag-checkbox]:checked')).map(function(el) {
      return el.value;
    });
    tagHiddenInput.value = checked.join(', ');
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form').forEach(function (form) {
      var tagHiddenInput = form.querySelector('[data-tags-hidden-input]');
      if (tagHiddenInput) {
        form.querySelectorAll('[data-tag-checkbox]').forEach(function (checkbox) {
          checkbox.addEventListener('change', function() { syncTagsInForm(form); });
          checkbox.addEventListener('click', function() {
            setTimeout(function() { syncTagsInForm(form); }, 0);
          });
        });
        form.querySelectorAll('.tag-chip').forEach(function(chip) {
          chip.addEventListener('click', function() {
            setTimeout(function() { syncTagsInForm(form); }, 0);
          });
        });
        syncTagsInForm(form);
      }
    });

    document.querySelectorAll('[data-valuation-mode]').forEach(function (select) {
      var form = select.closest('form');
      if (!form) return;
      var manualFields = form.querySelector('[data-manual-fields]');
      var positionsPanel = form.querySelector('[data-positions-panel]');
      var positionFormPanel = form.querySelector('[data-position-form-panel]');
      var hintManual = select.closest('label') && select.closest('label').querySelector('[data-hint-manual]');
      var hintHoldings = select.closest('label') && select.closest('label').querySelector('[data-hint-holdings]');

      function syncValuationMode() {
        var isHoldings = select.value === 'holdings';
        if (manualFields) {
          manualFields.hidden = isHoldings;
          manualFields.style.display = isHoldings ? 'none' : 'contents';
        }
        if (positionsPanel) {
          positionsPanel.hidden = !isHoldings;
          positionsPanel.style.display = isHoldings ? 'block' : 'none';
        }
        if (positionFormPanel) {
          positionFormPanel.hidden = !isHoldings;
          positionFormPanel.style.display = isHoldings ? 'block' : 'none';
        }
        if (hintManual)   hintManual.style.display   = isHoldings ? 'none' : '';
        if (hintHoldings) hintHoldings.style.display = isHoldings ? '' : 'none';
      }

      select.addEventListener('change', syncValuationMode);
      syncValuationMode();
    });

    var PROVIDER_DEFAULTS = {
      'nest':                    { wrapper: 'Workplace Pension', category: 'Pension' },
      "the people's pension":    { wrapper: 'Workplace Pension', category: 'Pension' },
      'now: pensions':           { wrapper: 'Workplace Pension', category: 'Pension' },
      'smart pension':           { wrapper: 'Workplace Pension', category: 'Pension' },
      'cushon':                  { wrapper: 'Workplace Pension', category: 'Pension' },
      'salary finance':          { wrapper: 'Workplace Pension', category: 'Pension' },
      'standard life':           { wrapper: 'Workplace Pension', category: 'Pension' },
      'aviva':                   { wrapper: 'Workplace Pension', category: 'Pension' },
      'legal & general':         { wrapper: 'Workplace Pension', category: 'Pension' },
      'scottish widows':         { wrapper: 'Workplace Pension', category: 'Pension' },
      'royal london':            { wrapper: 'Workplace Pension', category: 'Pension' },
      'aegon':                   { wrapper: 'Workplace Pension', category: 'Pension' },
      'zurich':                  { wrapper: 'Workplace Pension', category: 'Pension' },
      'aon':                     { wrapper: 'Workplace Pension', category: 'Pension' },
      'mercer':                  { wrapper: 'Workplace Pension', category: 'Pension' },
      'willis towers watson':    { wrapper: 'Workplace Pension', category: 'Pension' },
      'pensionbee':              { wrapper: 'SIPP', category: 'Pension' },
      'investengine':            { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'freetrade':               { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'trading 212':             { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'nutmeg':                  { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'wealthify':               { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'moneyfarm':               { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'wealthsimple':            { wrapper: 'Stocks & Shares ISA', category: 'ISA' },
      'moneybox':                { wrapper: 'Lifetime ISA', category: 'ISA' },
      "ns&i":                    { wrapper: 'Other', category: 'Other' },
      'marcus by goldman sachs': { wrapper: 'Other', category: 'Other' },
      'chip':                    { wrapper: 'Other', category: 'Other' },
      'plum':                    { wrapper: 'Other', category: 'Other' },
    };

    document.querySelectorAll('input[list="provider-list"]').forEach(function (input) {
      var form = input.closest('form');
      if (!form) return;
      input.addEventListener('change', function () {
        var key = input.value.trim().toLowerCase();
        var defaults = PROVIDER_DEFAULTS[key];
        if (!defaults) return;
        var wrapperSel = form.querySelector('select[name="wrapper_type"]');
        var categorySel = form.querySelector('select[name="category"]');
        if (wrapperSel) {
          var opt = Array.from(wrapperSel.options).find(function(o) { return o.value === defaults.wrapper; });
          if (opt) wrapperSel.value = defaults.wrapper;
        }
        if (categorySel) {
          var opt2 = Array.from(categorySel.options).find(function(o) { return o.value === defaults.category; });
          if (opt2) categorySel.value = defaults.category;
        }
      });
    });

    document.querySelectorAll('[data-growth-mode]').forEach(function (select) {
      var form = select.closest('form');
      if (!form) return;
      var customRateField = form.querySelector('[data-custom-rate-field]');
      var hintDefault = select.closest('label') && select.closest('label').querySelector('[data-hint-growth-default]');
      var hintCustom  = select.closest('label') && select.closest('label').querySelector('[data-hint-growth-custom]');

      function syncGrowthMode() {
        var isCustom = select.value === 'custom';
        if (customRateField) customRateField.style.display = isCustom ? '' : 'none';
        if (hintDefault) hintDefault.style.display = isCustom ? 'none' : '';
        if (hintCustom)  hintCustom.style.display  = isCustom ? '' : 'none';
      }

      select.addEventListener('change', syncGrowthMode);
      syncGrowthMode();
    });

    document.querySelectorAll('tr[data-href]').forEach(function (row) {
      row.addEventListener('click', function () {
        window.location.href = row.dataset.href;
      });
    });

    var focusPanel = document.querySelector('[data-focus-panel]');
    if (focusPanel) {
      requestAnimationFrame(function () {
        focusPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  });

  /* ── Online/Offline status ───────────────────────────────────────── */
  (function () {
    var banner = document.getElementById('offline-banner');
    var toast  = document.getElementById('online-toast');
    if (!banner) return;
    var wasOffline = false;
    var lastPingOk = true;
    var toastTimer = null;

    function showOffline() {
      document.body.classList.remove('is-back-online');
      document.body.classList.add('is-offline');
      banner.classList.remove('hidden');
      if (toast) toast.classList.add('hidden');
    }

    function showOnline() {
      document.body.classList.remove('is-offline');
      banner.classList.add('hidden');
      if (wasOffline && toast) {
        document.body.classList.add('is-back-online');
        toast.classList.remove('hidden');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
          toast.classList.add('hidden');
          document.body.classList.remove('is-back-online');
        }, 3000);
      }
      wasOffline = false;
    }

    function checkServer() {
      if (!navigator.onLine) {
        wasOffline = true;
        lastPingOk = false;
        showOffline();
        return;
      }
      fetch('/api/ping', { cache: 'no-store' })
        .then(function (r) {
          lastPingOk = !!(r && r.ok);
          if (lastPingOk) showOnline();
          else { wasOffline = true; showOffline(); }
        })
        .catch(function () {
          wasOffline = true;
          lastPingOk = false;
          showOffline();
        });
    }

    checkServer();
    window.addEventListener('online',  checkServer);
    window.addEventListener('offline', checkServer);
    window.__shellyIsOffline = function () { return !navigator.onLine || !lastPingOk; };
  })();

  /* ── Form submit: disable button & show spinner ─────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form').forEach(function(form) {
      if (form.classList.contains('budget-amount-form')) return;
      form.addEventListener('submit', function(e) {
        syncTagsInForm(form);
        var isPost = form.method && form.method.toUpperCase() === 'POST';
        if (isPost && window.__shellyIsOffline && window.__shellyIsOffline()) {
          e.preventDefault();
          var banner = document.getElementById('offline-banner');
          if (banner) banner.classList.remove('hidden');
          return;
        }
        var btn = form.querySelector('button[type="submit"]');
        if (btn && !btn.classList.contains('btn-loading')) {
          btn.classList.add('btn-loading');
          btn.disabled = true;
          setTimeout(function() {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
          }, 8000);
        }
      });
    });
  });

  /* ── Service Worker registration ──────────────────────────────────── */
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js')
      .then(function(reg) {
        setInterval(function() { reg.update(); }, 60 * 60 * 1000);
      })
      .catch(function() { });
  }
})();
