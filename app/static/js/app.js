/* app.js — Core client-side logic for Shelly Finance */

(function() {
  /* ── CSRF Protection ─────────────────────────────────────────────── */
  var csrfTokenEl = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfTokenEl ? csrfTokenEl.getAttribute('content') : '';

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
    if (!overlay) return Promise.resolve(confirm(opts.message || 'Are you sure?'));

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
    if (!overlay) return;
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

  /* ── Tag sync helper ─────────────────────────────────────────────── */
  window.syncTagsInForm = function(form) {
    var tagHiddenInput = form.querySelector('[data-tags-hidden-input]');
    if (!tagHiddenInput) return;
    var checked = Array.from(form.querySelectorAll('[data-tag-checkbox]:checked')).map(function(el) {
      return el.value;
    });
    tagHiddenInput.value = checked.join(', ');
  };

  /* ── Initialization Registry ──────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    // 0. Flash dismiss buttons (CSP-safe — replaces onclick attribute)
    document.querySelectorAll('.flash-dismiss').forEach(function(btn) {
      btn.addEventListener('click', function() { btn.parentElement.remove(); });
    });

    // 1. All [data-confirm] elements
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.preventDefault();
        window.shellyConfirm({
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

    // 2. Tag sync in forms
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

    // 3. Valuation mode sync
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

    // 4. Provider defaults
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

    // 5. Growth mode sync
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

    // 6. Clickable table rows
    document.querySelectorAll('tr[data-href]').forEach(function (row) {
      row.addEventListener('click', function () {
        window.location.href = row.dataset.href;
      });
    });

    // 7. Focus panel
    var focusPanel = document.querySelector('[data-focus-panel]');
    if (focusPanel) {
      requestAnimationFrame(function () {
        focusPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }

    // 8. Progress bars (Allowance)
    document.querySelectorAll('.progress-bar[data-pct]').forEach(function (el) {
      var pct = parseFloat(el.dataset.pct || '0');
      if (!isFinite(pct) || pct < 0) pct = 0;
      if (pct > 100) pct = 100;
      el.style.width = pct + '%';
    });

    // 9. CSV Import Preview
    (function initCsvPreview() {
      var selectBtn   = document.getElementById('select-all-btn');
      var deselectBtn = document.getElementById('deselect-all-btn');
      if (!selectBtn && !deselectBtn) return;

      function setAll(checked) {
        document.querySelectorAll('.import-checkbox').forEach(function (cb) {
          cb.checked = checked;
          cb.closest('tr').classList.toggle('import-row-dim', !checked);
        });
      }

      if (selectBtn)   selectBtn.addEventListener('click',   function () { setAll(true); });
      if (deselectBtn) deselectBtn.addEventListener('click', function () { setAll(false); });

      document.querySelectorAll('.import-checkbox').forEach(function (cb) {
        cb.addEventListener('change', function() {
          cb.closest('tr').classList.toggle('import-row-dim', !cb.checked);
        });
      });
    })();

    // 10. History Period Tabs (Holding Detail)
    (function initHistoryTabs() {
      var tabs = document.querySelectorAll('#history-period-tabs a');
      tabs.forEach(function (a) {
        a.addEventListener('click', function (e) {
          e.preventDefault();
          window.location.replace(a.getAttribute('href'));
        });
      });
    })();

    // 11. Budget Logic
    (function initBudget() {
      var container = document.querySelector('.budget-container');
      if (!container) return;

      var MONTH      = container.dataset.monthKey;
      var INCOME_KEY = container.dataset.incomeKey;
      var SAVE_KEYS  = ['invest', 'saving'];

      function fmtGBP(v, showSign) {
        var s = Math.abs(v).toLocaleString('en-GB', {minimumFractionDigits:0, maximumFractionDigits:0});
        if (showSign) return (v >= 0 ? '+' : '-') + '£' + s;
        return '£' + s;
      }

      function recalcSummary() {
        var sectionTotals = {};
        document.querySelectorAll('.budget-amount-input').forEach(function(inp) {
          var k = inp.dataset.section;
          sectionTotals[k] = (sectionTotals[k] || 0) + (parseFloat(inp.value) || 0);
        });

        var income   = sectionTotals[INCOME_KEY] || 0;
        var expenses = 0;
        var savings  = 0;
        Object.keys(sectionTotals).forEach(function(k) {
          if (k === INCOME_KEY) return;
          expenses += sectionTotals[k];
          SAVE_KEYS.forEach(function(s) { if (k.indexOf(s) !== -1) savings += sectionTotals[k]; });
        });
        var surplus      = income - expenses;
        var savingsRate  = income > 0 ? (savings / income * 100) : 0;

        var si = document.getElementById('stat-income');
        var se = document.getElementById('stat-expenses');
        var ss = document.getElementById('stat-surplus');
        var sr = document.getElementById('stat-savings');
        if (si) si.textContent = fmtGBP(income);
        if (se) se.textContent = fmtGBP(expenses);
        if (ss) {
          ss.textContent = (surplus >= 0 ? '+' : '-') + fmtGBP(Math.abs(surplus));
          ss.className   = surplus >= 0 ? 'stat-positive-text' : 'stat-negative-text';
        }
        if (sr) sr.textContent = savingsRate.toFixed(1) + '%';

        // Update section totals
        Object.keys(sectionTotals).forEach(function(k) {
          var el = document.getElementById('total-' + k);
          if (el) el.textContent = '£' + sectionTotals[k].toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
        });
      }

      function saveEntry(itemId, amount, ind) {
        var fd = new FormData();
        fd.append('month', MONTH);
        fd.append('item_id', itemId);
        fd.append('amount', amount);

        fetch('/budget/api/entry', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(d) {
          if (d.ok && ind) {
            ind.textContent = '✓';
            ind.style.opacity = '1';
            setTimeout(function() {
              ind.style.opacity = '0';
              setTimeout(function() { ind.textContent = ''; ind.style.opacity = '1'; }, 300);
            }, 1200);
          }
        })
        .catch(function() {
          if (ind) {
            ind.textContent = '✗';
            ind.style.color = 'var(--error)';
            ind.style.opacity = '1';
            setTimeout(function() {
              ind.style.opacity = '0';
              setTimeout(function() { ind.textContent = ''; ind.style.color = ''; ind.style.opacity = '1'; }, 300);
            }, 2500);
          }
        });
      }

      // File import auto-submit (CSP-safe — replaces onchange attribute on file input)
      var importFileInput = document.getElementById('budget-import-file');
      if (importFileInput) {
        importFileInput.addEventListener('change', function() {
          this.closest('form').submit();
        });
      }

      document.querySelectorAll('.budget-amount-input').forEach(function(input) {
        var debounceTimer = null;
        var ind = document.getElementById('ind-' + input.dataset.itemId);
        var row = input.closest('.budget-row');
        var isLinked = !!row.querySelector('.budget-pill');
        var linkedNotified = false;
        var sourceBadge = row.querySelector('.budget-row-source');

        input.addEventListener('input', function() {
          if (sourceBadge) { sourceBadge.style.display = 'none'; sourceBadge = null; }
          if (isLinked && !linkedNotified) {
            linkedNotified = true;
            if (ind) {
              ind.textContent = 'this month only';
              ind.style.opacity = '1';
              setTimeout(function() { ind.style.opacity = '0'; }, 3000);
            }
          }
          clearTimeout(debounceTimer);
          debounceTimer = setTimeout(function() {
            saveEntry(input.dataset.itemId, input.value, ind);
            recalcSummary();
          }, 600);
        });
      });

      // Sync hero stats immediately on load (server-rendered values may differ
      // from JS calculation in edge cases like inherited/overridden months)
      recalcSummary();

      // Prev/next month navigation arrows
      var prevMonthBtn = document.getElementById('prev-month');
      var nextMonthBtn = document.getElementById('next-month');
      function shiftMonth(key, delta) {
        var parts = key.split('-');
        var y = parseInt(parts[0]);
        var m = parseInt(parts[1]) + delta;
        if (m < 1)  { m = 12; y--; }
        if (m > 12) { m = 1;  y++; }
        window.location.href = '/budget/?month=' + y + '-' + (m < 10 ? '0' + m : m);
      }
      if (prevMonthBtn) prevMonthBtn.addEventListener('click', function() { shiftMonth(MONTH, -1); });
      if (nextMonthBtn) nextMonthBtn.addEventListener('click', function() { shiftMonth(MONTH, 1); });
    })();

    // 12. Monthly Review Logic
    (function initMonthlyReview() {
      var reviewSection = document.querySelector('.monthly-review-container');
      if (!reviewSection) return;

      var MONTH_KEY = reviewSection.dataset.monthKey;

      function apiPost(url, body) {
        return fetch(url, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
          body: JSON.stringify(body),
        });
      }

      /* Confirm checkboxes */
      document.querySelectorAll('.contribution-cb').forEach(function(cb) {
        cb.addEventListener('change', function() {
          var row = cb.closest('.contribution-check-row');
          var itemId = parseInt(row.dataset.itemId);
          var confirmed = cb.checked;
          row.classList.toggle('contribution-confirmed', confirmed);
          apiPost('/monthly-review/api/confirm-contribution',
            {item_id: itemId, confirmed: confirmed, month_key: MONTH_KEY})
            .catch(function() {
              cb.checked = !confirmed;
              row.classList.toggle('contribution-confirmed', !confirmed);
            });
        });
      });

      /* Skip/Restore buttons */
      document.querySelectorAll('.contribution-skip-btn, .contribution-restore-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var row = btn.closest('.contribution-check-row');
          var accountId = parseInt(row.dataset.accountId);
          var isSkip = btn.classList.contains('contribution-skip-btn');
          var url = isSkip ? '/monthly-review/api/skip-contribution' : '/monthly-review/api/restore-contribution';
          var body = {account_id: accountId, month_key: MONTH_KEY};
          if (isSkip) body.reason = 'Skipped';

          btn.disabled = true; btn.textContent = '…';
          apiPost(url, body)
            .then(function(r) { if (r.ok) location.reload(); })
            .catch(function() { btn.disabled = false; btn.textContent = isSkip ? 'Skip' : 'Restore'; });
        });
      });

      /* Holding Update Rows */
      function fmtGBP(n) {
        return '£' + n.toLocaleString('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
      }

      document.querySelectorAll('.holding-update-row').forEach(function(form) {
        var ticker   = form.dataset.ticker;
        var unitsEl  = form.querySelector('.hu-units');
        var priceEl  = form.querySelector('.hu-price');
        var valueEl  = form.querySelector('.hu-value');
        var refreshBtn = form.querySelector('.hu-refresh');
        var submitBtn  = form.querySelector('.hu-submit');

        function recalc() {
          var units = parseFloat(unitsEl.value) || 0;
          var price = parseFloat(priceEl.value) || 0;
          if (valueEl) valueEl.textContent = fmtGBP(units * price);
        }

        function buildPayload(price, meta) {
          meta = meta || {};
          return {
            month_key: MONTH_KEY,
            holding_id: (form.querySelector('[name="holding_id"]') || {}).value,
            account_id: (form.querySelector('[name="account_id"]') || {}).value,
            holding_catalogue_id: (form.querySelector('[name="holding_catalogue_id"]') || {}).value || null,
            holding_name: (form.querySelector('[name="holding_name"]') || {}).value || '',
            ticker: (form.querySelector('[name="ticker"]') || {}).value || '',
            asset_type: (form.querySelector('[name="asset_type"]') || {}).value || '',
            bucket: (form.querySelector('[name="bucket"]') || {}).value || '',
            notes: (form.querySelector('[name="notes"]') || {}).value || '',
            units: parseFloat(unitsEl.value) || 0,
            price: price,
            price_source: meta.price_source,
            price_raw: meta.price_raw,
            currency_raw: meta.currency_raw,
            change_pct: meta.change_pct,
            updated_at: meta.updated_at,
          };
        }

        async function autoSave(price, meta) {
          try {
            await fetch('/holdings/api/save-price', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(buildPayload(price, meta)),
            });
            if (submitBtn) {
              submitBtn.textContent = 'Saved ✓';
              setTimeout(function() { submitBtn.textContent = 'Save'; }, 1500);
            }
          } catch(e) {}
        }

        if (refreshBtn && ticker) {
          refreshBtn.addEventListener('click', async function() {
            refreshBtn.textContent = '…';
            try {
              var resp = await fetch('/holdings/api/price?ticker=' + encodeURIComponent(ticker));
              if (resp.ok) {
                var data = await resp.json();
                priceEl.value = data.price;
                recalc();
                await autoSave(data.price, {
                  price_source: 'live',
                  price_raw: data.price_raw,
                  currency_raw: data.currency_raw,
                  change_pct: data.change_pct,
                  updated_at: data.updated_at,
                });
              }
            } catch(e) {}
            refreshBtn.textContent = '↻';
          });
        }

        if (submitBtn) {
          submitBtn.addEventListener('click', async function() {
            var price = parseFloat(priceEl ? priceEl.value : '0') || 0;
            await autoSave(price);
          });
        }

        if (unitsEl) unitsEl.addEventListener('input', recalc);
        if (priceEl) priceEl.addEventListener('input', recalc);
      });

      var updateAllBtn = document.getElementById('update-all-prices');
      if (updateAllBtn) {
        updateAllBtn.addEventListener('click', async function() {
          updateAllBtn.disabled = true;
          updateAllBtn.textContent = '↻ Updating…';
          var rows = document.querySelectorAll('.holding-update-row[data-ticker]');
          var total = rows.length;
          var done = 0;
          for (var i = 0; i < rows.length; i++) {
            var btn = rows[i].querySelector('.hu-refresh');
            if (btn) btn.click();
            done++;
            updateAllBtn.textContent = '↻ ' + done + '/' + total;
            await new Promise(function(r) { setTimeout(r, 500); });
          }
          updateAllBtn.textContent = '✓ All updated';
          setTimeout(function() { updateAllBtn.disabled = false; updateAllBtn.textContent = '↻ Update All Prices'; }, 2500);
        });
      }

      /* Guide (The Routine) toggle */
      var guideToggle = document.getElementById('guide-toggle');
      var guidePanel  = document.getElementById('guide-panel');
      if (guideToggle && guidePanel) {
        guideToggle.addEventListener('click', function() {
          var hidden = guidePanel.classList.contains('hidden');
          guidePanel.classList.toggle('hidden', !hidden);
          guideToggle.textContent = hidden ? 'Hide' : 'Show';
        });
      }

      /* CSV import toggle */
      var csvToggle = document.getElementById('csv-import-toggle');
      var csvPanel  = document.getElementById('csv-import-panel');
      var csvCancel = document.getElementById('csv-import-cancel');
      if (csvToggle && csvPanel) {
        csvToggle.addEventListener('click', function() {
          var hidden = csvPanel.classList.contains('hidden');
          csvPanel.classList.toggle('hidden', !hidden);
          csvToggle.textContent = hidden ? 'Hide' : 'Show';
        });
      }
      if (csvCancel && csvPanel) {
        csvCancel.addEventListener('click', function() {
          csvPanel.classList.add('hidden');
          if (csvToggle) csvToggle.textContent = 'Show';
        });
      }

      /* Mark as Complete — open native dialog */
      var markCompleteBtn  = document.getElementById('mark-complete-btn');
      var markCompleteForm = document.getElementById('mark-complete-form');
      var completeDialog   = document.getElementById('confirm-complete-dialog');
      var confirmYes       = document.getElementById('confirm-complete-yes');
      var confirmNo        = document.getElementById('confirm-complete-no');
      if (markCompleteBtn && completeDialog) {
        markCompleteBtn.addEventListener('click', function() {
          if (completeDialog.showModal) {
            completeDialog.showModal();
          } else {
            completeDialog.setAttribute('open', '');
          }
        });
      }
      if (confirmYes && markCompleteForm) {
        confirmYes.addEventListener('click', function() { markCompleteForm.submit(); });
      }
      if (confirmNo && completeDialog) {
        confirmNo.addEventListener('click', function() {
          if (completeDialog.close) {
            completeDialog.close();
          } else {
            completeDialog.removeAttribute('open');
          }
        });
      }

      /* Month navigation (prev/next) */
      function shiftMonth(key, delta) {
        var parts = key.split('-');
        var y = parseInt(parts[0]);
        var m = parseInt(parts[1]) + delta;
        if (m < 1)  { m = 12; y--; }
        if (m > 12) { m = 1;  y++; }
        window.location.href = '/monthly-review/?month=' + y + '-' + (m < 10 ? '0' + m : m);
      }
      var prevMonthBtn = document.querySelector('.review-prev-month');
      var nextMonthBtn = document.querySelector('.review-next-month');
      if (prevMonthBtn) prevMonthBtn.addEventListener('click', function() { shiftMonth(MONTH_KEY, -1); });
      if (nextMonthBtn) nextMonthBtn.addEventListener('click', function() { shiftMonth(MONTH_KEY, 1); });

    })();

    // 13. Budget Debts Logic
    (function initBudgetDebts() {
      // No page guard — each section checks for its own elements.

      // ── Amortization helpers ──────────────────────────────────────────
      function buildSchedule(balance, payment, apr) {
        var r = apr / 100 / 12;
        var rows = [];
        var bal = balance;
        for (var i = 1; i <= 600 && bal > 0.005; i++) {
          var interest  = r > 0 ? bal * r : 0;
          var principal = Math.min(payment - interest, bal);
          if (principal < 0.001) break;
          bal = Math.max(bal - principal, 0);
          rows.push({ month: i, payment: interest + principal,
                      interest: interest, principal: principal, balance: bal });
        }
        return rows;
      }

      function fmt2(v) {
        return '£' + v.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
      }

      function renderScheduleHtml(rows) {
        var html = '<div style="overflow-x:auto;"><table class="data-table">' +
          '<thead><tr><th class="num">Month</th><th class="num">Payment</th>' +
          '<th class="num">Interest</th><th class="num">Principal</th>' +
          '<th class="num">Balance</th></tr></thead><tbody>';
        rows.forEach(function(r, i) {
          var hidden = i >= 24 ? ' class="sched-extra" style="display:none;"' : '';
          html += '<tr' + hidden + '>' +
            '<td class="num text-muted">' + r.month + '</td>' +
            '<td class="num">' + fmt2(r.payment) + '</td>' +
            '<td class="num stat-negative-text">' + fmt2(r.interest) + '</td>' +
            '<td class="num" style="color:var(--accent-3);">' + fmt2(r.principal) + '</td>' +
            '<td class="num"><strong>' + fmt2(r.balance) + '</strong></td></tr>';
        });
        html += '</tbody></table></div>';
        if (rows.length > 24) {
          html += '<div class="badge-row mt-075">' +
            '<button type="button" class="badge" id="sched-show-all">Show all ' +
            rows.length + ' months</button></div>';
        }
        return html;
      }

      function wireShowAll() {
        var btn = document.getElementById('sched-show-all');
        if (btn) {
          btn.addEventListener('click', function() {
            document.querySelectorAll('#debt-sched-container .sched-extra').forEach(function(r) {
              r.style.display = '';
            });
            btn.style.display = 'none';
          });
        }
      }

      function scheduleToCSV(rows, name, extra) {
        var lines = ['"Payment Schedule — ' + (name || 'Debt').replace(/"/g, '') + '"'];
        if (extra > 0) lines.push('"Extra monthly payment: £' + extra.toFixed(2) + ' — new total: £' + (extra + (rows[0] ? rows[0].payment : 0)).toFixed(2) + '/mo"');
        lines.push('');
        lines.push('Month,Payment (£),Interest (£),Principal (£),Balance (£)');
        rows.forEach(function(r) {
          lines.push([r.month, r.payment.toFixed(2), r.interest.toFixed(2),
                      r.principal.toFixed(2), r.balance.toFixed(2)].join(','));
        });
        return lines.join('\n');
      }

      function downloadCSV(content, filename) {
        var blob = new Blob([content], {type: 'text/csv;charset=utf-8;'});
        var url  = URL.createObjectURL(blob);
        var a    = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }

      // ── What-if quick buttons ────────────────────────────────────────
      document.querySelectorAll('.debt-quick-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var input = document.getElementById(btn.dataset.target);
          if (input) {
            input.value = parseFloat(btn.dataset.amount) || '';
            input.dispatchEvent(new Event('input'));
          }
        });
      });

      // ── What-if summary stats (updates as you type) ──────────────────
      function monthsToPayoff(balance, payment, apr) {
        if (balance <= 0) return 0;
        if (payment <= 0) return null;
        var r = apr / 100 / 12;
        if (r === 0) return Math.ceil(balance / payment);
        if (payment <= balance * r) return null;
        return Math.ceil(-Math.log(1 - balance * r / payment) / Math.log(1 + r));
      }

      function totalInterest(balance, payment, apr, months) {
        if (apr === 0) return 0;
        if (months === null) return null;
        return Math.max(payment * months - balance, 0);
      }

      function addMonths(months) {
        var d = new Date();
        d.setMonth(d.getMonth() + months);
        return d.toLocaleString('en-GB', {month: 'long', year: 'numeric'});
      }

      function fmtRound(v) { return '£' + Math.round(v).toLocaleString('en-GB'); }

      document.querySelectorAll('.debt-whatif-input').forEach(function(input) {
        input.addEventListener('input', function() {
          var id           = input.id.replace('extra-', '');
          var balance      = parseFloat(input.dataset.balance)   || 0;
          var payment      = parseFloat(input.dataset.payment)   || 0;
          var apr          = parseFloat(input.dataset.apr)       || 0;
          var origMonths   = parseInt(input.dataset.months)      || 0;
          var origInterest = parseFloat(input.dataset.interest)  || 0;
          var extra        = parseFloat(input.value)             || 0;
          var result       = document.getElementById('result-' + id);

          if (extra <= 0) { if (result) result.style.display = 'none'; return; }

          var newPayment  = payment + extra;
          var newMonths   = monthsToPayoff(balance, newPayment, apr);
          var newInterest = newMonths !== null ? totalInterest(balance, newPayment, apr, newMonths) : null;
          var monthsSaved = newMonths !== null ? Math.max(origMonths - newMonths, 0) : null;
          var intSaved    = newInterest !== null ? Math.max(origInterest - newInterest, 0) : null;

          if (result) result.style.display = '';
          var dateEl   = document.getElementById('wi-date-' + id);
          var mSavedEl = document.getElementById('wi-months-saved-' + id);
          var iSavedEl = document.getElementById('wi-int-saved-' + id);
          var iNewEl   = document.getElementById('wi-int-new-' + id);
          if (dateEl)   dateEl.textContent   = newMonths !== null ? addMonths(newMonths) : 'Cannot pay off';
          if (mSavedEl) mSavedEl.textContent = monthsSaved !== null ? monthsSaved + ' month' + (monthsSaved === 1 ? '' : 's') : '—';
          if (iSavedEl) iSavedEl.textContent = intSaved    !== null ? fmtRound(intSaved) : '—';
          if (iNewEl)   iNewEl.textContent   = newInterest !== null ? fmtRound(newInterest) : '—';
        });
      });

      // ── Schedule: Calculate / Reset / Export ─────────────────────────
      var calcBtn     = document.getElementById('debt-calc-btn');
      var resetBtn    = document.getElementById('debt-sched-reset');
      var exportBtn   = document.getElementById('debt-sched-export');
      var schedEl     = document.getElementById('debt-sched-container');
      var schedTitle  = document.getElementById('debt-sched-title');
      var schedHint   = document.getElementById('debt-sched-hint');
      var whatifInput = document.querySelector('.debt-whatif-input');

      var _origHtml    = schedEl   ? schedEl.innerHTML        : null;
      var _origTitle   = schedTitle ? schedTitle.textContent  : null;
      var _origHint    = schedHint  ? schedHint.style.display : null;
      var _curSchedule = null;
      var _curExtra    = 0;

      if (schedEl) wireShowAll();

      if (calcBtn && whatifInput && schedEl) {
        calcBtn.addEventListener('click', function() {
          var balance  = parseFloat(whatifInput.dataset.balance)  || 0;
          var payment  = parseFloat(whatifInput.dataset.payment)  || 0;
          var apr      = parseFloat(whatifInput.dataset.apr)      || 0;
          var extra    = parseFloat(whatifInput.value)            || 0;
          if (balance <= 0 || payment <= 0) return;

          var sched = buildSchedule(balance, payment + extra, apr);
          _curSchedule = sched;
          _curExtra    = extra;

          if (schedTitle) {
            schedTitle.textContent = extra > 0
              ? 'Recalculated · +£' + extra.toLocaleString('en-GB') + '/mo extra'
              : 'Month by month (current payment)';
          }
          if (schedHint) schedHint.style.display = 'none';
          schedEl.innerHTML = renderScheduleHtml(sched);
          wireShowAll();
          if (resetBtn) resetBtn.style.display = '';
        });
      }

      if (resetBtn && schedEl) {
        resetBtn.addEventListener('click', function() {
          if (_origHtml !== null) {
            schedEl.innerHTML = _origHtml;
            if (schedTitle) schedTitle.textContent = _origTitle;
            if (schedHint && _origHint !== null) schedHint.style.display = _origHint;
            _curSchedule = null;
            _curExtra    = 0;
            resetBtn.style.display = 'none';
            wireShowAll();
          }
        });
      }

      if (exportBtn) {
        exportBtn.addEventListener('click', function() {
          var name = whatifInput ? (whatifInput.dataset.name || 'Debt') : 'Debt';
          var slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
          if (_curSchedule && _curSchedule.length) {
            downloadCSV(scheduleToCSV(_curSchedule, name, _curExtra),
              'schedule-' + slug + (_curExtra > 0 ? '-extra' : '') + '.csv');
          } else {
            // Build CSV from the DOM table (original server-rendered schedule)
            var rows = document.querySelectorAll('#debt-sched-container tbody tr');
            var lines = ['"Payment Schedule — ' + name.replace(/"/g, '') + '"', '',
                         'Month,Payment (£),Interest (£),Principal (£),Balance (£)'];
            rows.forEach(function(row) {
              var cells = row.querySelectorAll('td');
              if (cells.length >= 5) {
                lines.push([
                  cells[0].textContent.replace(/[✓\s]/g, '').trim(),
                  cells[1].textContent.replace(/[£,]/g, '').trim(),
                  cells[2].textContent.replace(/[£,]/g, '').trim(),
                  cells[3].textContent.replace(/[£,]/g, '').trim(),
                  cells[4].textContent.replace(/[£,]/g, '').trim()
                ].join(','));
              }
            });
            downloadCSV(lines.join('\n'), 'schedule-' + slug + '.csv');
          }
        });
      }

      // ── 0% deal calculator ───────────────────────────────────────────
      var zeroBalance = document.getElementById('zero-balance');
      var zeroMonths  = document.getElementById('zero-months');
      var zeroResult  = document.getElementById('zero-result');
      var zeroMonthly = document.getElementById('zero-monthly');
      var zeroNote    = document.getElementById('zero-note');
      var zeroFill    = document.getElementById('zero-fill-payment');

      function calcZero() {
        if (!zeroBalance || !zeroMonths) return;
        var bal = parseFloat(zeroBalance.value) || 0;
        var mos = parseInt(zeroMonths.value)    || 0;
        if (bal <= 0 || mos <= 0) { if (zeroResult) zeroResult.style.display = 'none'; return; }
        var monthly = bal / mos;
        if (zeroMonthly) zeroMonthly.textContent = '£' + monthly.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
        if (zeroNote)    zeroNote.textContent    = '(£' + bal.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2}) + ' ÷ ' + mos + ' months)';
        if (zeroFill)    zeroFill.value          = monthly.toFixed(2);
        if (zeroResult)  zeroResult.style.display = '';
      }

      if (zeroBalance) zeroBalance.addEventListener('input', calcZero);
      if (zeroMonths)  zeroMonths.addEventListener('input', calcZero);
    })();

    // 15. Settings Logic
    (function initSettings() {
      var mpaaToggle = document.getElementById('mpaa-toggle');
      var mpaaRow = document.getElementById('mpaa-row');
      if (mpaaToggle && mpaaRow) {
        function sync() { mpaaRow.style.display = mpaaToggle.checked ? '' : 'none'; }
        mpaaToggle.addEventListener('change', sync);
        sync();
      }

      var autoUpdateToggle = document.getElementById('auto-update-toggle');
      var timesRow = document.getElementById('update-times-row');
      if (autoUpdateToggle && timesRow) {
        function sync() { timesRow.style.display = autoUpdateToggle.checked ? '' : 'none'; }
        autoUpdateToggle.addEventListener('change', sync);
        sync();
      }

      var revealBtn  = document.getElementById('reset-reveal-btn');
      var formWrap   = document.getElementById('reset-form');
      var confirmWrap= document.getElementById('reset-confirm');
      var input      = document.getElementById('reset-input');
      var submitBtn  = document.getElementById('reset-submit');
      var cancelBtn  = document.getElementById('reset-cancel');

      if (revealBtn) {
        revealBtn.addEventListener('click', function() {
          confirmWrap.style.display = 'none';
          formWrap.style.display = '';
          input.focus();
        });
      }

      if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
          formWrap.style.display = 'none';
          confirmWrap.style.display = '';
          input.value = '';
          submitBtn.disabled = true;
        });
      }

      if (input) {
        input.addEventListener('input', function() {
          submitBtn.disabled = input.value.trim().toUpperCase() !== 'RESET';
        });
      }
    })();

    // 17. Account Create Wizard
    (function initWizard() {
      var form = document.getElementById('create-account-form');
      if (!form) return;

      var current = 1;
      var isHoldingsAccount = false;
      var pendingHoldings = [];        /* [{type,ticker,name,units,price,asset_type}] */
      var createdAccountId = null;

      /* Tax band from data attribute — defaults to basic if not provided */
      var TAX_BAND = form.dataset.taxBand || 'basic';
      var TAX_RATES = { basic: 0.20, higher: 0.40, additional: 0.45 };
      var BAND_RATE = TAX_RATES[TAX_BAND] || 0.20;

      function stepSequence() {
        return isHoldingsAccount ? [1,2,3,4,5] : [1,2,4,5];
      }
      function nextStep() {
        var seq = stepSequence();
        var idx = seq.indexOf(current);
        return idx >= 0 && idx < seq.length - 1 ? seq[idx + 1] : null;
      }
      function prevStep() {
        var seq = stepSequence();
        var idx = seq.indexOf(current);
        return idx > 0 ? seq[idx - 1] : null;
      }

      var progressBar = document.getElementById('cw-progress');

      function buildDots() {
        var seq = stepSequence();
        progressBar.innerHTML = '';
        for (var i = 0; i < seq.length; i++) {
          if (i > 0) {
            var line = document.createElement('div');
            line.className = 'cw-line';
            progressBar.appendChild(line);
          }
          var dot = document.createElement('div');
          dot.className = 'cw-dot';
          dot.setAttribute('data-cw-dot', seq[i]);
          dot.innerHTML = '<span>' + (i + 1) + '</span>';
          progressBar.appendChild(dot);
        }
        updateDots();
      }

      function updateDots() {
        var seq = stepSequence();
        var currentIdx = seq.indexOf(current);
        progressBar.querySelectorAll('[data-cw-dot]').forEach(function(dot) {
          var s = parseInt(dot.getAttribute('data-cw-dot'));
          var dotIdx = seq.indexOf(s);
          dot.classList.toggle('cw-dot-active', s === current);
          dot.classList.toggle('cw-dot-done', dotIdx < currentIdx && dotIdx >= 0);
        });
      }

      function refreshStepCount() {
        var valMode = document.getElementById('cw-valuation');
        isHoldingsAccount = valMode && valMode.value === 'holdings';
        buildDots();
      }
      refreshStepCount();

      function goTo(n, direction) {
        if (n < 1 || n > 6) return;
        var outPanel = form.querySelector('[data-cw="' + current + '"]');
        var inPanel  = form.querySelector('[data-cw="' + n + '"]');
        if (!outPanel || !inPanel) return;

        var slideOut = direction === 'back' ? 'cw-slide-right' : 'cw-slide-left';
        var slideIn  = direction === 'back' ? 'cw-enter-left'  : 'cw-enter-right';

        outPanel.classList.add(slideOut);
        outPanel.classList.remove('cw-visible');

        setTimeout(function() {
          outPanel.classList.remove(slideOut);
          inPanel.classList.add('cw-visible', slideIn);
          setTimeout(function() { inPanel.classList.remove(slideIn); }, 300);
        }, 250);

        current = n;
        progressBar.style.display = (n === 6) ? 'none' : '';
        var cancelBtn = document.getElementById('cw-cancel');
        if (cancelBtn) cancelBtn.style.display = (n === 6) ? 'none' : '';
        updateDots();
      }

      form.querySelectorAll('[data-cw-next]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          if (current === 3) autoHarvestHolding();
          var n = nextStep();
          if (n) goTo(n, 'forward');
        });
      });
      form.querySelectorAll('[data-cw-prev]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var p = prevStep();
          if (p) goTo(p, 'back');
        });
      });

      var manualFields = form.querySelector('[data-manual-fields]');
      function toggleManualFields() {
        var valMode = document.getElementById('cw-valuation');
        if (manualFields && valMode) {
          manualFields.style.display = valMode.value === 'manual' ? '' : 'none';
        }
      }
      toggleManualFields();

      var growthModeEl    = document.getElementById('cw-growth-mode');
      var customRateField = form.querySelector('[data-custom-rate-field]');
      function toggleCustomRate() {
        if (customRateField) {
          customRateField.style.display = growthModeEl && growthModeEl.value === 'custom' ? '' : 'none';
        }
      }
      if (growthModeEl) {
        growthModeEl.addEventListener('change', toggleCustomRate);
        toggleCustomRate();
      }

      var holdingsList  = document.getElementById('cw-holdings-list');
      var holdingsCount = document.getElementById('cw-holdings-count');
      function renderHoldings() {
        if (!holdingsList || !holdingsCount) return;
        holdingsList.innerHTML = '';
        pendingHoldings.forEach(function(h, i) {
          var chip = document.createElement('div');
          chip.className = 'setup-holding-chip';
          var valStr = h.value ? '£' + parseFloat(h.value).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',') : '';
          chip.innerHTML = '<strong>' + (h.name || h.ticker) + '</strong>' +
            '<span class="text-muted">' + parseFloat(h.units).toFixed(2) + ' units</span>' +
            (valStr ? '<span>' + valStr + '</span>' : '') +
            '<button type="button" class="badge badge-danger badge-meta cw-remove-holding" data-idx="' + i + '">×</button>';
          holdingsList.appendChild(chip);
        });
        holdingsCount.style.display = pendingHoldings.length ? '' : 'none';
        holdingsCount.textContent = pendingHoldings.length === 1
          ? '1 holding added — add more or continue when you\'re ready.'
          : pendingHoldings.length + ' holdings added — add more or continue when you\'re ready.';

        holdingsList.querySelectorAll('.cw-remove-holding').forEach(function(btn) {
          btn.addEventListener('click', function() {
            pendingHoldings.splice(parseInt(this.getAttribute('data-idx')), 1);
            renderHoldings();
          });
        });
      }

      var hTickerIn = document.getElementById('cw-h-ticker');
      var hUnitsIn  = document.getElementById('cw-h-units');
      var hPreview  = document.getElementById('cw-h-preview');
      var hStatus   = document.getElementById('cw-h-status');
      var hAddBtn   = document.getElementById('cw-h-add');
      var hCachedPrice = null;
      var hLookupTimer = null;

      function fmtGBP(v) { return '£' + v.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2}); }

      function updateTickerPreview() {
        if (!hUnitsIn || !hPreview) return;
        var u = parseFloat(hUnitsIn.value);
        if (hCachedPrice && u > 0) {
          hPreview.textContent = fmtGBP(u * hCachedPrice);
          hPreview.style.color = 'var(--accent)';
        } else {
          hPreview.textContent = '—';
          hPreview.style.color = 'var(--muted)';
        }
      }

      function doTickerLookup() {
        if (!hTickerIn || !hStatus) return;
        var t = hTickerIn.value.trim();
        if (!t || t.length < 2) { hCachedPrice = null; hStatus.textContent = ''; updateTickerPreview(); return; }
        hStatus.textContent = 'Looking up ' + t.toUpperCase() + '…';
        hStatus.style.color = 'var(--muted)';

        fetch('/holdings/api/price?ticker=' + encodeURIComponent(t))
          .then(function(r) { return r.json(); })
          .then(function(d) {
            if (d.price) {
              hCachedPrice = d.price;
              var sym = d.yf_symbol || t.toUpperCase();
              var symNote = sym !== t.toUpperCase() ? ' (matched as ' + sym + ')' : '';
              hStatus.textContent = fmtGBP(d.price) + '/unit' +
                (d.change_pct != null ? '  ' + (d.change_pct >= 0 ? '+' : '') + d.change_pct.toFixed(2) + '%' : '') +
                symNote;
              hStatus.style.color = '#86efac';
            } else {
              hCachedPrice = null;
              hStatus.innerHTML = 'Not found via live market data providers. <button type="button" id="cw-h-status-switch-manual" style="color:#93c5fd;background:none;border:none;padding:0;cursor:pointer;font-size:inherit;text-decoration:underline;">Add manually instead →</button>';
              hStatus.style.color = '#fca5a5';
              var sBtn = document.getElementById('cw-h-status-switch-manual');
              if (sBtn) sBtn.addEventListener('click', function() {
                var switchManual = document.getElementById('cw-h-switch-manual');
                if (switchManual) switchManual.click();
              });
            }
            updateTickerPreview();
          });
      }

      function doFullLookup(ticker, callback) {
        var fd = new FormData();
        fd.append('ticker', ticker);
        fetch('/accounts/api/ticker-lookup', { method: 'POST', body: fd })
          .then(function(r) { return r.json(); })
          .then(function(data) { callback(data.ok ? data : null); })
          .catch(function() { callback(null); });
      }

      if (hTickerIn) {
        hTickerIn.addEventListener('input', function() {
          clearTimeout(hLookupTimer);
          hCachedPrice = null; updateTickerPreview();
          hLookupTimer = setTimeout(doTickerLookup, 700);
        });
        hTickerIn.addEventListener('blur', function() { clearTimeout(hLookupTimer); doTickerLookup(); });
      }
      if (hUnitsIn) hUnitsIn.addEventListener('input', updateTickerPreview);

      if (hAddBtn) {
        hAddBtn.addEventListener('click', function() {
          var ticker = hTickerIn.value.trim().toUpperCase();
          var units  = hUnitsIn.value.trim();
          if (!ticker || !units || parseFloat(units) <= 0) {
            hStatus.textContent = 'Pop in a ticker and the number of units.';
            hStatus.style.color = '#fca5a5';
            return;
          }
          if (!hCachedPrice) {
            hStatus.textContent = 'Wait for the price lookup to finish first.';
            hStatus.style.color = '#fca5a5';
            return;
          }

          hAddBtn.disabled = true;
          hStatus.textContent = 'Adding ' + ticker + '…';
          hStatus.style.color = 'var(--muted)';

          doFullLookup(ticker, function(info) {
            hAddBtn.disabled = false;
            var name = (info && info.name) || ticker;
            var assetType = (info && info.asset_type) || 'ETF';
            var value = (parseFloat(units) * hCachedPrice).toFixed(2);

            pendingHoldings.push({
              type: 'ticker', ticker: ticker, yf_symbol: (info && info.yf_symbol) || ticker,
              name: name, asset_type: assetType,
              units: units, price: hCachedPrice, value: value
            });

            hTickerIn.value = '';
            hUnitsIn.value = '';
            hCachedPrice = null;
            hPreview.textContent = '—';
            hStatus.textContent = name + ' added — ' + fmtGBP(parseFloat(value));
            hStatus.style.color = '#86efac';
            setTimeout(function() { hStatus.textContent = ''; }, 4000);
            renderHoldings();
          });
        });
      }

      var mAddBtn = document.getElementById('cw-m-add');
      if (mAddBtn) {
        mAddBtn.addEventListener('click', function() {
          var name  = document.getElementById('cw-m-name').value.trim();
          var ticker= document.getElementById('cw-m-ticker').value.trim().toUpperCase() || null;
          var atype = document.getElementById('cw-m-type').value;
          var units = document.getElementById('cw-m-units').value.trim();
          var price = document.getElementById('cw-m-price').value.trim();
          var status= document.getElementById('cw-m-status');
          if (!name || !units || !price || parseFloat(units) <= 0 || parseFloat(price) <= 0) {
            status.textContent = 'Shelly needs a name, units and price per unit.';
            return;
          }
          var value = (parseFloat(units) * parseFloat(price)).toFixed(2);
          pendingHoldings.push({ type: 'manual', name: name, ticker: ticker, asset_type: atype, units: units, price: price, value: value });
          document.getElementById('cw-m-name').value = '';
          document.getElementById('cw-m-ticker').value = '';
          document.getElementById('cw-m-units').value = '';
          document.getElementById('cw-m-price').value = '';
          status.textContent = name + ' added!';
          setTimeout(function() { status.textContent = ''; }, 3000);
          renderHoldings();
        });
      }

      function autoHarvestHolding() {
        var tickerForm = document.getElementById('cw-ticker-form');
        var tickerFormVisible = tickerForm && !tickerForm.classList.contains('hidden');

        if (tickerFormVisible) {
          var ticker = hTickerIn.value.trim().toUpperCase();
          var units  = hUnitsIn.value.trim();
          if (ticker && units && parseFloat(units) > 0) {
            if (hCachedPrice) {
              var value = (parseFloat(units) * hCachedPrice).toFixed(2);
              pendingHoldings.push({
                type: 'ticker', ticker: ticker, yf_symbol: ticker,
                name: ticker, asset_type: 'ETF',
                units: units, price: hCachedPrice, value: value
              });
            } else {
              pendingHoldings.push({
                type: 'ticker', ticker: ticker, yf_symbol: ticker,
                name: ticker, asset_type: 'ETF',
                units: units, price: null, value: null
              });
            }
            hTickerIn.value = ''; hUnitsIn.value = ''; hCachedPrice = null;
            if (hPreview) hPreview.textContent = '—';
            renderHoldings();
          }
        } else {
          var mName  = document.getElementById('cw-m-name').value.trim();
          var mUnits = document.getElementById('cw-m-units').value.trim();
          var mPrice = document.getElementById('cw-m-price').value.trim();
          if (mName && mUnits && mPrice && parseFloat(mUnits) > 0 && parseFloat(mPrice) > 0) {
            var mTicker = document.getElementById('cw-m-ticker').value.trim().toUpperCase() || null;
            var mType   = document.getElementById('cw-m-type').value;
            var mVal    = (parseFloat(mUnits) * parseFloat(mPrice)).toFixed(2);
            pendingHoldings.push({
              type: 'manual', name: mName, ticker: mTicker, asset_type: mType,
              units: mUnits, price: mPrice, value: mVal
            });
            document.getElementById('cw-m-name').value = '';
            document.getElementById('cw-m-ticker').value = '';
            document.getElementById('cw-m-units').value = '';
            document.getElementById('cw-m-price').value = '';
            renderHoldings();
          }
        }
      }

      var hSwitchManual = document.getElementById('cw-h-switch-manual');
      if (hSwitchManual) {
        hSwitchManual.addEventListener('click', function() {
          document.getElementById('cw-ticker-form').classList.add('hidden');
          document.getElementById('cw-manual-form').classList.remove('hidden');
        });
      }
      var hSwitchTicker = document.getElementById('cw-h-switch-ticker');
      if (hSwitchTicker) {
        hSwitchTicker.addEventListener('click', function() {
          document.getElementById('cw-manual-form').classList.add('hidden');
          document.getElementById('cw-ticker-form').classList.remove('hidden');
        });
      }

      var createBtn = document.getElementById('cw-create-btn');
      if (createBtn) {
        createBtn.addEventListener('click', function() {
          createBtn.textContent = 'Shelly\'s setting things up…';
          createBtn.disabled = true;

          var fd = new FormData();
          form.querySelectorAll('input[name], select[name]').forEach(function(el) { fd.append(el.name, el.value); });
          form.querySelectorAll('[data-tag-checkbox]:checked').forEach(function(cb) { fd.append('tags', cb.value); });

          var errorBox = document.getElementById('cw-create-error');
          if (errorBox) errorBox.style.display = 'none';

          fetch('/accounts/api/create', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(data) {
              if (!data.ok) throw new Error(data.error || 'Account creation failed');
              createdAccountId = data.account_id;

              var chain = Promise.resolve();
              pendingHoldings.forEach(function(h) {
                chain = chain.then(function() {
                  var hfd = new FormData();
                  if (h.type === 'ticker') {
                    hfd.append('ticker', h.ticker);
                    hfd.append('units', h.units);
                    return fetch('/accounts/api/' + createdAccountId + '/holdings/add', { method: 'POST', body: hfd });
                  } else {
                    hfd.append('name', h.name);
                    hfd.append('ticker', h.ticker || '');
                    hfd.append('asset_type', h.asset_type || 'Fund');
                    hfd.append('units', h.units);
                    hfd.append('price', h.price);
                    return fetch('/accounts/api/' + createdAccountId + '/holdings/add-manual', { method: 'POST', body: hfd });
                  }
                });
              });

              return chain.then(function() {
                var accName = document.getElementById('cw-name').value || 'your new account';
                var title = document.getElementById('cw-success-title');
                var msg   = document.getElementById('cw-success-msg');

                if (pendingHoldings.length > 0) {
                  title.textContent = accName + ' is live!';
                  msg.textContent = 'Shelly\'s got ' + accName + ' all set up with ' +
                    pendingHoldings.length + (pendingHoldings.length === 1 ? ' holding' : ' holdings') +
                    '. He\'s already crunching the numbers — check your dashboard to see how things are shaping up.';
                } else {
                  title.textContent = 'You\'re all set!';
                  msg.textContent = 'Shelly\'s got ' + accName + ' tucked away safe and sound. He\'s already keeping an eye on it — you\'ll see it on your dashboard and in your projections straight away. Go on, have a look.';
                }
                goTo(6, 'forward');
              });
            })
            .catch(function(err) {
              createBtn.textContent = 'Create account';
              createBtn.disabled = false;
              if (errorBox) { errorBox.textContent = err.message || 'Something went wrong.'; errorBox.style.display = ''; }
            });
        });
      }

      var wrapperEl    = document.getElementById('cw-wrapper');
      var categoryEl   = document.getElementById('cw-category');
      var valModeEl    = document.getElementById('cw-valuation');
      var employerEl   = document.getElementById('cw-employer-field');
      var postingEl    = document.getElementById('cw-posting-field');
      var methodField  = document.getElementById('cw-method-field');
      var methodSelect = document.getElementById('cw-method-select');
      var methodHint   = document.getElementById('cw-method-hint');
      var personalIn   = document.getElementById('cw-personal');
      var personalLabel= document.getElementById('cw-personal-label');
      var employerIn   = document.getElementById('cw-employer');
      var previewBox   = document.getElementById('cw-contrib-preview');
      var contribHint  = document.getElementById('cw-hint-contrib');

      var prevPersonal    = document.getElementById('cw-prev-personal');
      var prevPersonalVal = document.getElementById('cw-prev-personal-val');
      var prevRelief      = document.getElementById('cw-prev-relief');
      var prevReliefLabel = document.getElementById('cw-prev-relief-label');
      var prevReliefVal   = document.getElementById('cw-prev-relief-val');
      var prevEmployer    = document.getElementById('cw-prev-employer');
      var prevEmployerVal = document.getElementById('cw-prev-employer-val');
      var prevTotal       = document.getElementById('cw-prev-total');

      var CFG = {
        'Stocks & Shares ISA':       { cat: 'ISA',     bal: 'holdings', showEmployer: false, method: null, personalLabel: 'Monthly contribution', hint: 'How much do you put into this ISA each month? Even a rough figure helps Shelly map out your future.' },
        'Cash ISA':                   { cat: 'ISA',     bal: 'manual',   showEmployer: false, method: null, personalLabel: 'Monthly deposit', hint: 'How much do you stash away in this Cash ISA each month?' },
        'Lifetime ISA':               { cat: 'ISA',     bal: 'holdings', showEmployer: false, method: null, personalLabel: 'Your monthly contribution', hint: 'How much do you pay in each month? The government tops it up with a lovely 25% bonus (up to £1,000/year).' },
        'SIPP':                       { cat: 'Pension', bal: 'holdings', showEmployer: false, method: null, personalLabel: 'Your monthly contribution', hint: 'How much do you pay in? Your provider claims 25% tax relief from HMRC automatically — free money, basically.' },
        'Workplace Pension':          { cat: 'Pension', bal: 'manual',   showEmployer: true,  method: ['salary_sacrifice','relief_at_source'], methodDefault: 'salary_sacrifice', personalLabel: 'Your employee contribution', hint: 'How is your workplace pension set up? Pick the method first — Shelly will work out the rest.', methodHints: { salary_sacrifice: 'Contributions come out of your pay before tax — no further relief needed.', relief_at_source: 'You pay from net pay; your provider claims 20% tax relief from HMRC (e.g. NEST).' } },
        'General Investment Account': { cat: 'Taxable', bal: 'holdings', showEmployer: false, method: null, personalLabel: 'Monthly investment', hint: 'How much do you invest into this account each month?' },
        'Other':                      { cat: null,      bal: 'manual',   showEmployer: false, method: null, personalLabel: 'Monthly contribution', hint: 'How much goes in each month, if anything? No pressure — you can always update this later.' }
      };
      var currentWrapper = '';

      function applyConfig() {
        if (!wrapperEl) return;
        var w   = wrapperEl.value;
        var cfg = CFG[w] || CFG['Other'];
        currentWrapper = w;
        if (cfg.cat && categoryEl) categoryEl.value = cfg.cat;
        if (valModeEl) { valModeEl.value = cfg.bal; valModeEl.dispatchEvent(new Event('change')); }
        if (contribHint) contribHint.textContent = cfg.hint;
        if (personalLabel) personalLabel.textContent = cfg.personalLabel;

        if (methodField && methodSelect) {
          if (cfg.method) {
            methodField.style.display = '';
            methodSelect.innerHTML = '';
            cfg.method.forEach(function(val) {
              var opt = document.createElement('option');
              opt.value = val;
              opt.textContent = val === 'salary_sacrifice' ? 'Salary sacrifice' : val === 'relief_at_source' ? 'Relief at source (e.g. NEST)' : 'My own contributions';
              methodSelect.appendChild(opt);
            });
            if (cfg.methodDefault) methodSelect.value = cfg.methodDefault;
            updateMethodHint();
          } else {
            methodField.style.display = 'none';
            methodSelect.innerHTML = '<option value="standard" selected>My own contributions</option>';
          }
        }
        if (employerEl) employerEl.style.display = cfg.showEmployer ? '' : 'none';
        if (postingEl) postingEl.style.display = (w === 'Workplace Pension') ? '' : 'none';
        refreshStepCount();
        updatePreview();
      }

      function updateMethodHint() {
        var cfg = CFG[wrapperEl.value] || CFG['Other'];
        if (methodHint && cfg.methodHints && cfg.methodHints[methodSelect.value]) methodHint.textContent = cfg.methodHints[methodSelect.value];
        else if (methodHint) methodHint.textContent = '';
        updatePreview();
      }

      function fmt(v) { return '£' + v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

      var prevSelfAssess     = document.getElementById('cw-prev-selfassess');
      var prevSelfAssessLabel= document.getElementById('cw-prev-selfassess-label');
      var prevSelfAssessVal  = document.getElementById('cw-prev-selfassess-val');
      var prevSelfAssessNote = document.getElementById('cw-prev-selfassess-note');

      function updatePreview() {
        if (!personalIn || !previewBox) return;
        var personal = parseFloat(personalIn.value) || 0;
        var employer = parseFloat(employerIn ? employerIn.value : 0) || 0;
        var w = currentWrapper;
        var method = methodSelect ? methodSelect.value : 'standard';

        if (personal <= 0 && employer <= 0) { previewBox.style.display = 'none'; return; }

        var relief = 0, reliefLabel = '', showRelief = false, showEmp = false;
        var selfAssess = 0, showSelfAssess = false, selfAssessNote = '';

        if (w === 'SIPP') {
          relief = personal * 0.25;
          reliefLabel = '+ basic-rate tax relief (25%)';
          showRelief = true;
          if (BAND_RATE > 0.20) {
            var gross = personal + relief;
            selfAssess = gross * (BAND_RATE - 0.20);
            showSelfAssess = true;
            selfAssessNote = 'You\'re a ' + TAX_BAND + '-rate taxpayer (' + Math.round(BAND_RATE * 100) + '%). Your provider claims 20% automatically. You claim the extra ' + Math.round((BAND_RATE - 0.20) * 100) + '% back through your self-assessment tax return — it goes to you, not the pension.';
          }
        } else if (w === 'Workplace Pension') {
          if (method === 'salary_sacrifice') {
            if (employer > 0) showEmp = true;
          } else {
            relief = personal * 0.25;
            reliefLabel = '+ basic-rate tax relief (25%)';
            showRelief = true;
            if (BAND_RATE > 0.20) {
              var gross = personal + relief;
              selfAssess = gross * (BAND_RATE - 0.20);
              showSelfAssess = true;
              selfAssessNote = 'As a ' + TAX_BAND + '-rate taxpayer, you can claim an extra ' + Math.round((BAND_RATE - 0.20) * 100) + '% back via self-assessment. This goes to you as a tax refund, not into the pension.';
            }
          }
          if (employer > 0) showEmp = true;
        } else if (w === 'Lifetime ISA') {
          var eligible = Math.min(personal * 12, 4000);
          relief = (eligible * 0.25) / 12;
          reliefLabel = '+ government bonus (25%)';
          showRelief = relief > 0;
        }

        var total = personal + relief + employer;
        var hasExtra = showRelief || showEmp;

        previewBox.style.display = (hasExtra || showSelfAssess) ? '' : 'none';
        if (!hasExtra && !showSelfAssess) return;

        if (prevPersonal) { prevPersonal.style.display = ''; prevPersonalVal.textContent = fmt(personal) + '/mo'; }
        if (prevRelief) {
          prevRelief.style.display = showRelief ? '' : 'none';
          if (showRelief) { prevReliefLabel.textContent = reliefLabel; prevReliefVal.textContent = '+ ' + fmt(relief) + '/mo'; }
        }
        if (prevEmployer) {
          prevEmployer.style.display = showEmp ? '' : 'none';
          if (showEmp) prevEmployerVal.textContent = fmt(employer) + '/mo';
        }
        if (prevTotal) prevTotal.textContent = fmt(total) + '/mo';

        if (prevSelfAssess) {
          prevSelfAssess.style.display = showSelfAssess ? '' : 'none';
          prevSelfAssessNote.style.display = showSelfAssess ? '' : 'none';
          if (showSelfAssess) {
            prevSelfAssessLabel.textContent = '+ you claim back via self-assessment';
            prevSelfAssessVal.textContent = '+ ' + fmt(selfAssess) + '/mo';
            prevSelfAssessNote.textContent = selfAssessNote;
          }
        }
      }

      if (valModeEl) { valModeEl.addEventListener('change', function() { refreshStepCount(); toggleManualFields(); toggleCustomRate(); }); }
      if (wrapperEl) { wrapperEl.addEventListener('change', applyConfig); applyConfig(); }
      if (growthModeEl) growthModeEl.addEventListener('change', toggleCustomRate);
      if (methodSelect) methodSelect.addEventListener('change', updateMethodHint);
      if (personalIn) { personalIn.addEventListener('input', updatePreview); personalIn.addEventListener('change', updatePreview); }
      if (employerIn) { employerIn.addEventListener('input', updatePreview); employerIn.addEventListener('change', updatePreview); }
    })();

    // 18. Tag Management
    (function initTagManagement() {
      function handleDeleteTag(e) {
        e.preventDefault();
        e.stopPropagation();
        var btn = e.currentTarget;
        var tagName = btn.getAttribute('data-delete-tag');
        if (!tagName) return;

        window.shellyConfirm({
          title: 'Remove "' + tagName + '"?',
          message: 'This removes the tag from the list.',
          confirmText: 'Yes, remove tag',
          cancelText: 'Keep it',
        }).then(function (confirmed) {
          if (!confirmed) return;
          var fd = new FormData();
          fd.append('tag', tagName);
          fetch('/accounts/api/tags/delete', { method: 'POST', body: fd })
            .then(r => r.json())
            .then(data => { if (data.ok) btn.closest('.tag-chip').remove(); });
        });
      }

      document.querySelectorAll('.tag-delete').forEach(btn => btn.addEventListener('click', handleDeleteTag));

      var addBtn = document.querySelector('[data-add-tag-btn]');
      if (addBtn) {
        addBtn.addEventListener('click', function () {
          var input = document.querySelector('[data-new-tag-input]');
          var tagName = (input.value || '').trim();
          if (!tagName) return;
          var fd = new FormData();
          fd.append('tag', tagName);
          fetch('/accounts/api/tags', { method: 'POST', body: fd })
            .then(r => r.json())
            .then(data => { if (data.ok) window.location.reload(); });
        });
      }
    })();

    // 19. Projections What-If Logic
    (function initWhatIf() {
      var ageInput = document.getElementById('wi_age');
      if (!ageInput) return;

      var BASE_CURRENT_AGE = parseFloat(ageInput.dataset.currentAgeFrac);
      var BASE_RETIREMENT_AGE = parseInt(ageInput.dataset.baseRetirementAge);
      var BASE_YEARS_REMAINING = parseFloat(ageInput.dataset.baseYearsRemaining);
      var BASE_MONTHS_REMAINING = parseInt(ageInput.dataset.baseMonthsRemaining);
      var DEFAULT_RATE_PCT = parseFloat(ageInput.dataset.defaultRatePct);

      function fv(current, monthly, annualRate, years, months) {
        var r = annualRate / 12;
        var n = (typeof months === 'number') ? months : Math.floor(years * 12);
        var fc = current * Math.pow(1 + r, n);
        var fm = r === 0 ? monthly * n : monthly * ((Math.pow(1 + r, n) - 1) / r);
        return fc + fm;
      }

      function projectAccount(current, monthly, annualRate, retAge, isLISA) {
        var onPlan = (retAge === BASE_RETIREMENT_AGE);
        var years  = onPlan ? BASE_YEARS_REMAINING : Math.max(retAge - BASE_CURRENT_AGE, 0);
        var months = onPlan ? BASE_MONTHS_REMAINING : undefined;
        if (isLISA) {
          var contribEndAge = Math.min(50, retAge);
          var contribYears  = Math.max(contribEndAge - BASE_CURRENT_AGE, 0);
          var frozenYears   = Math.max(years - contribYears, 0);
          var valAtEnd = fv(current, monthly, annualRate, contribYears);
          return fv(valAtEnd, 0, annualRate, frozenYears);
        }
        return fv(current, monthly, annualRate, years, months);
      }

      function fmt(v) { return '£' + Math.round(v).toLocaleString('en-GB'); }

      var inputs  = Array.from(document.querySelectorAll('.wi-contrib-input'));
      var labels  = Array.from(document.querySelectorAll('[data-projected-label]'));
      var rateInput = document.getElementById('wi_rate');

      function recalc() {
        var retAge      = parseFloat(ageInput.value)  || BASE_RETIREMENT_AGE;
        var globalPct   = parseFloat(rateInput.value) || 0;
        var rateChanged = Math.abs(globalPct - DEFAULT_RATE_PCT) > 0.0001;
        var scenarioTotal = 0;
        var planTotal     = 0;
        var totalMonthly  = 0;

        inputs.forEach(function(inp, i) {
          var current = parseFloat(inp.dataset.current) || 0;
          var personal = parseFloat(inp.value) || 0;
          var planPersonal = parseFloat(inp.dataset.plan) || 0;
          var planEffective = parseFloat(inp.dataset.effective) || planPersonal;
          var acctRate = parseFloat(inp.dataset.rate) || 0;
          var isLISA = inp.dataset.wrapper === 'Lifetime ISA';
          var ratio = planPersonal > 0 ? (planEffective / planPersonal) : 1;
          var monthly = personal * ratio;
          var useRate = rateChanged ? (globalPct / 100) : acctRate;
          var proj = projectAccount(current, monthly, useRate, retAge, isLISA);
          var planVal = projectAccount(current, planEffective, acctRate, BASE_RETIREMENT_AGE, isLISA);
          scenarioTotal += proj; planTotal += planVal; totalMonthly += personal;
          if (labels[i]) labels[i].textContent = fmt(proj);
        });

        var diff = scenarioTotal - planTotal;
        var diffEl = document.getElementById('wi_diff');
        if (diffEl) {
          diffEl.textContent = (diff >= 0 ? '+' : '') + fmt(diff);
          diffEl.className = diff >= 0 ? 'whatif-positive' : 'whatif-negative';
        }
        var totalEl = document.getElementById('wi_total');
        if (totalEl) totalEl.textContent = fmt(scenarioTotal);
        var yearsEl = document.getElementById('wi_years');
        if (yearsEl) yearsEl.textContent = Math.round((retAge === BASE_RETIREMENT_AGE) ? BASE_YEARS_REMAINING : Math.max(retAge - BASE_CURRENT_AGE, 0)) + ' years';
        var monthlyEl = document.getElementById('wi_monthly');
        if (monthlyEl) monthlyEl.textContent = fmt(totalMonthly) + '/mo';
      }

      ageInput.addEventListener('input', recalc);
      if (rateInput) rateInput.addEventListener('input', recalc);
      inputs.forEach(function(inp) { inp.addEventListener('input', recalc); });

      var resetBtn = document.getElementById('wi_reset');
      if (resetBtn) {
        resetBtn.addEventListener('click', function() {
          ageInput.value  = BASE_RETIREMENT_AGE;
          if (rateInput) rateInput.value = DEFAULT_RATE_PCT;
          inputs.forEach(function(inp) { inp.value = inp.dataset.plan; });
          recalc();
        });
      }
      recalc();
    })();

    // 20. Instrument Lookup Logic
    (function initHoldingsLookup() {
      var input = document.getElementById('instrument-search-input');
      var btn   = document.getElementById('instrument-search-btn');
      var resultBox = document.getElementById('instrument-search-result');
      if (!input || !btn || !resultBox) return;

      function fmtPrice(price, currency, change_pct) {
        var priceStr = currency === 'GBp' ? price.toFixed(2) + 'p' : '£' + price.toFixed(4);
        var changeStr = '';
        if (change_pct !== null && change_pct !== undefined) {
          var cls = change_pct >= 0 ? 'perf-positive' : 'perf-negative';
          changeStr = ' <span class="' + cls + '" style="font-size:0.8rem;">' + (change_pct >= 0 ? '+' : '') + change_pct.toFixed(2) + '%</span>';
        }
        return priceStr + changeStr;
      }

      async function doSearch() {
        var q = input.value.trim();
        if (!q) return;
        btn.textContent = '…'; btn.disabled = true;
        resultBox.style.display = 'none'; resultBox.innerHTML = '';

        try {
          var resp = await fetch('/holdings/api/lookup?q=' + encodeURIComponent(q));
          var data = await resp.json();
          if (!resp.ok) {
            resultBox.innerHTML = '<p style="color:#fca5a5;font-size:0.875rem;">⚠ ' + (data.error || 'Not found') + '</p>';
            resultBox.style.display = 'block'; return;
          }

          var inCat = data.in_catalogue;
          var addToCatBtn = inCat ? '' :
            '<form method="post" style="margin:0;">' +
              '<input type="hidden" name="csrf_token" value="' + csrfToken + '">' +
              '<input type="hidden" name="form_name" value="catalogue">' +
              '<input type="hidden" name="catalogue_holding_name" value="' + data.name.replace(/"/g,'&quot;') + '">' +
              '<input type="hidden" name="catalogue_ticker" value="' + data.ticker + '">' +
              '<input type="hidden" name="catalogue_asset_type" value="' + data.asset_type + '">' +
              '<input type="hidden" name="catalogue_bucket" value="Global Equity">' +
              '<button type="submit" class="badge badge-meta">+ Save to instruments</button>' +
            '</form>';

          var addAction = data.catalogue_id ? '/holdings/' + data.catalogue_id + '/add-to-account' : '/holdings/search/add-to-account';
          var acctOptions = resultBox.dataset.accounts || '';

          var addToAcctForm =
            '<form method="post" action="' + addAction + '" style="display:flex;align-items:flex-end;gap:0.6rem;flex-wrap:wrap;margin-top:0.75rem;">' +
              '<input type="hidden" name="csrf_token" value="' + csrfToken + '">' +
              '<input type="hidden" name="ticker" value="' + data.ticker + '">' +
              '<input type="hidden" name="name" value="' + data.name.replace(/"/g,'&quot;') + '">' +
              '<input type="hidden" name="asset_type" value="' + data.asset_type + '">' +
              '<input type="hidden" name="price" value="' + data.price_gbp + '">' +
              '<label style="display:flex;flex-direction:column;gap:0.2rem;"><span style="font-size:0.72rem;color:var(--muted);text-transform:uppercase;">Account</span>' +
              '<select name="account_id" required style="background:var(--panel-2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:0.35rem 0.6rem;font-size:0.875rem;">' + acctOptions + '</select></label>' +
              '<label style="display:flex;flex-direction:column;gap:0.2rem;"><span style="font-size:0.72rem;color:var(--muted);text-transform:uppercase;">Units</span>' +
              '<input type="number" name="units" step="any" placeholder="e.g. 42.5" required style="width:8rem;background:var(--panel-2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:0.35rem 0.6rem;font-size:0.875rem;"></label>' +
              '<button type="submit" class="badge badge-primary-action">Add to account</button></form>';

          resultBox.innerHTML = '<div class="instrument-result-card"><strong>' + data.name + '</strong> <span class="holding-ticker">' + data.ticker + '</span>' +
            '<p>' + fmtPrice(data.price, data.currency, data.change_pct) + '</p>' +
            (inCat ? '<p style="color:#86efac;font-size:0.875rem;">✓ Already in instruments</p>' : '') +
            (addToCatBtn ? '<div class="badge-row">' + addToCatBtn + '</div>' : '') + addToAcctForm + '</div>';
          resultBox.style.display = 'block';
        } catch(e) {
          resultBox.innerHTML = '<p style="color:#fca5a5;font-size:0.875rem;">⚠ Request failed.</p>';
          resultBox.style.display = 'block';
        } finally { btn.textContent = 'Look up'; btn.disabled = false; }
      }
      btn.addEventListener('click', doSearch);
      input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
    })();

    // 21. Goals Dirty Checking
    (function initGoals() {
      var goalFlag = document.querySelector('form [name="form_name"][value="update_goal"]');
      if (!goalFlag) return;
      var form = goalFlag.closest('form');
      var cancelBtn = document.getElementById('goal-cancel-btn');
      if (!form || !cancelBtn) return;

      var originalData = new FormData(form);
      function isDirty() {
        var currentData = new FormData(form);
        for (var pair of currentData.entries()) {
          if (originalData.get(pair[0]) !== pair[1]) return true;
        }
        return false;
      }

      cancelBtn.addEventListener('click', async function (e) {
        if (isDirty()) {
          e.preventDefault();
          var ok = await window.shellyConfirm({
            title: 'Discard changes?',
            message: 'You have unsaved changes. Discard them?',
            confirmText: 'Yes, discard',
            cancelText: 'Keep editing'
          });
          if (ok) {
            window.location.href = cancelBtn.getAttribute('href');
          }
        }
      });
    })();

    // 22. Add Holding Logic
    (function initAddHolding() {
      var bar         = document.getElementById('add-holding-bar');
      var toggle      = document.getElementById('top-add-holding');
      var cancelBtn   = document.getElementById('ah-cancel');
      var modeTicker  = document.getElementById('ah-mode-ticker');
      var modeManual  = document.getElementById('ah-mode-manual');
      var toManual    = document.getElementById('ah-switch-manual');
      var toTicker    = document.getElementById('ah-switch-ticker');

      if (!toggle || !bar) return;

      function closeForm() {
        bar.style.display = 'none';
        toggle.textContent = '+ Add holding';
      }

      toggle.addEventListener('click', function() {
        var open = bar.style.display !== 'none';
        if (open) {
          closeForm();
        } else {
          bar.style.display = 'block';
          toggle.textContent = '✕ Cancel';
          bar.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          var tickerInp = document.getElementById('ah-ticker');
          if (tickerInp) tickerInp.focus();
        }
      });

      if (cancelBtn) cancelBtn.addEventListener('click', closeForm);

      if (toManual) {
        toManual.addEventListener('click', function() {
          if (modeTicker) modeTicker.style.display = 'none';
          if (modeManual) modeManual.style.display = 'block';
          var nameInp = document.getElementById('am-name');
          if (nameInp) nameInp.focus();
        });
      }
      if (toTicker) {
        toTicker.addEventListener('click', function() {
          if (modeManual) modeManual.style.display = 'none';
          if (modeTicker) modeTicker.style.display = 'block';
          var tickerInp = document.getElementById('ah-ticker');
          if (tickerInp) tickerInp.focus();
        });
      }

      var ticker  = document.getElementById('ah-ticker');
      var units   = document.getElementById('ah-units');
      var preview = document.getElementById('ah-preview');
      var status  = document.getElementById('ah-status');
      var cachedPrice = null;
      var lookupTimer = null;

      function fmtGBP(v) {
        return '£' + v.toLocaleString('en-GB', {minimumFractionDigits:2, maximumFractionDigits:2});
      }

      function updateTickerPreview() {
        var u = parseFloat(units.value);
        if (cachedPrice && u > 0) {
          preview.textContent = fmtGBP(u * cachedPrice);
          preview.style.color = 'var(--accent)';
        } else {
          preview.textContent = '—';
          preview.style.color = 'var(--muted)';
        }
      }

      function doLookup() {
        var t = ticker.value.trim();
        if (!t || t.length < 2) { cachedPrice = null; if (status) status.textContent = ''; updateTickerPreview(); return; }
        if (status) {
          status.textContent = 'Looking up…';
          status.style.color = 'var(--muted)';
        }
        fetch('/holdings/api/price?ticker=' + encodeURIComponent(t))
          .then(function(r) { return r.json(); })
          .then(function(d) {
            if (d.price) {
              cachedPrice = d.price;
              if (status) {
                status.textContent = '£' + d.price.toFixed(4) + '/unit' +
                  (d.change_pct != null ? '  ' + (d.change_pct >= 0 ? '+' : '') + d.change_pct.toFixed(2) + '%' : '');
                status.style.color = '#86efac';
              }
            } else {
              cachedPrice = null;
              if (status) {
                status.innerHTML = 'Not found via live market data providers. <button type="button" id="ah-status-switch-manual" ' +
                  'style="color:#93c5fd;background:none;border:none;padding:0;cursor:pointer;font-size:inherit;text-decoration:underline;">' +
                  'Add manually instead →</button>';
                status.style.color = '#fca5a5';
                var sBtn = document.getElementById('ah-status-switch-manual');
                if (sBtn) sBtn.addEventListener('click', function() { if (toManual) toManual.click(); });
              }
            }
            updateTickerPreview();
          });
      }

      if (ticker) {
        ticker.addEventListener('input', function() {
          clearTimeout(lookupTimer);
          lookupTimer = setTimeout(doLookup, 600);
        });
      }
      if (units) units.addEventListener('input', updateTickerPreview);
    })();

    /* ── Holding detail: back button uses browser history if available ── */
    (function () {
      var backBtn = document.getElementById('holding-back-btn');
      if (!backBtn) return;
      backBtn.addEventListener('click', function (e) {
        if (window.history.length > 1) {
          e.preventDefault();
          window.history.back();
        }
        // else follow the href="/holdings/" fallback naturally
      });
    })();

    /* ── Month/Year picker: sync selects → hidden input ──────────────── */
    (function () {
      document.querySelectorAll('.month-year-picker').forEach(function(picker) {
        var label = picker.closest('label');
        if (!label) return;
        var hidden = label.querySelector('.mp-hidden');
        var monthSel = picker.querySelector('.mp-month');
        var yearSel  = picker.querySelector('.mp-year');
        if (!hidden || !monthSel || !yearSel) return;

        function sync() {
          if (monthSel.value && yearSel.value) {
            hidden.value = yearSel.value + '-' + monthSel.value;
          } else {
            hidden.value = '';
          }
        }

        monthSel.addEventListener('change', sync);
        yearSel.addEventListener('change', sync);

        // Pre-fill current month/year in the year select
        var now = new Date();
        var currentYear = now.getFullYear();
        var currentMonth = String(now.getMonth() + 1).padStart(2, '0');
        Array.from(yearSel.options).forEach(function(opt) {
          if (parseInt(opt.value) === currentYear) opt.selected = true;
        });
        Array.from(monthSel.options).forEach(function(opt) {
          if (opt.value === currentMonth) opt.selected = true;
        });
        sync();
      });

      // Validate on submit that hidden values are set
      document.querySelectorAll('.override-add-form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
          var hiddens = form.querySelectorAll('.mp-hidden');
          for (var i = 0; i < hiddens.length; i++) {
            if (!hiddens[i].value) {
              e.preventDefault();
              alert('Please select both a month and year for the override period.');
              return;
            }
          }
        });
      });
    })();

  }); // End DOMContentLoaded

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
      if (!navigator.onLine) { wasOffline = true; lastPingOk = false; showOffline(); return; }
      fetch('/api/ping', { cache: 'no-store' })
        .then(r => { lastPingOk = !!(r && r.ok); if (lastPingOk) showOnline(); else { wasOffline = true; showOffline(); } })
        .catch(() => { wasOffline = true; lastPingOk = false; showOffline(); });
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
        if (typeof window.syncTagsInForm === 'function') window.syncTagsInForm(form);
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
      .then(reg => { setInterval(() => reg.update(), 60 * 60 * 1000); })
      .catch(() => { });
  }

})();
