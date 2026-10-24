// Filters apply as soon as a dropdown changes. Everything else works without JavaScript.
document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
  el.addEventListener('change', function () { el.form.submit(); });
});

// Job collection panel: while a collection runs, refresh its status every few seconds
// and reload the page once it has finished. Without JavaScript the panel still works.
(function () {
  var panel = document.querySelector('[data-collect-poll="1"]');
  if (panel && window.fetch) {
    var set = function (sel, text) { var el = panel.querySelector(sel); if (el) el.textContent = text; };
    var tick = function () {
      fetch('/collection/status', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (st) {
        if (st.state !== 'running') { window.location.reload(); return; }
        set('[data-collect-text]', st.message || '');
        set('[data-count-collected]', String(st.collected_unique || 0));
        set('[data-count-new]', String(st.new_added || 0));
        set('[data-count-had]', String(st.already_had || 0));
        set('[data-count-rejected]', String((st.skipped_not_relevant || 0) + (st.skipped_out_of_scope || 0)));
        var live = st.live || {};
        ['pages', 'cards', 'skipped', 'opened', 'fetched'].forEach(function (k) { set('[data-live-' + k + ']', String(live[k] || 0)); });
        var logBox = panel.querySelector('[data-collect-log]');
        if (logBox && st.log_tail) { logBox.textContent = st.log_tail.slice(-12).join('\n'); }
        var bar = panel.querySelector('[data-collect-bar]');
        if (bar) { bar.max = Math.max(st.search_total || 1, 1); bar.value = st.search_done || 0; }
        if (st.search_total) {
          set('[data-collect-detail]', 'Place ' + Math.min((st.search_done || 0) + 1, st.search_total) + ' of ' + st.search_total +
            (st.current_search ? ' - ' + st.current_search : '') + (st.current_page ? ', page ' + st.current_page : ''));
        }
      }).catch(function () {});
    };
    window.setInterval(tick, 3000);
  }
  // Restart page: wait until the new process answers, then open the dashboard.
  var restartBox = document.querySelector('[data-restart-poll]');
  if (restartBox && window.fetch) {
    var tries = 0;
    var oldBoot = restartBox.getAttribute('data-boot') || '';
    var wait = window.setInterval(function () {
      tries += 1;
      // open the dashboard only once a DIFFERENT process answers (the old one keeps answering for a moment)
      fetch('/app/boot', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (b) {
        if (b && b.boot && b.boot !== oldBoot) { window.clearInterval(wait); window.location.href = '/'; }
      }).catch(function () {});
      if (tries > 40) {
        window.clearInterval(wait);
        var t = document.querySelector('[data-restart-text]');
        if (t) t.textContent = 'The app did not come back. Close this window and open Ace Talent Consulting Job Radar again from the launcher.';
      }
    }, 1500);
  }
})();
