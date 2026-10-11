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
  if (document.querySelector('[data-restart-poll]') && window.fetch) {
    var tries = 0;
    var wait = window.setInterval(function () {
      tries += 1;
      fetch('/healthz', { cache: 'no-store' }).then(function (r) {
        if (r.ok && tries > 2) { window.clearInterval(wait); window.location.href = '/'; }
      }).catch(function () {});
      if (tries > 40) {
        window.clearInterval(wait);
        var t = document.querySelector('[data-restart-text]');
        if (t) t.textContent = 'The app did not come back. Close this window and open Orbit Job Radar again from the launcher.';
      }
    }, 1500);
  }
})();
