
  /* Light/dark toggle shared by briefing.html.j2 and index.html.j2.
     render.py inlines this file and allows it by hash in the page's
     Content-Security-Policy, which blocks every other inline script —
     so don't add inline on*= handlers or new script blocks to the templates. */

  /* Apply saved theme as early as possible to avoid a light/dark flash. */
  (function () {
    try {
      var saved = localStorage.getItem('theme');
      if (saved === 'light' || saved === 'dark') {
        document.documentElement.setAttribute('data-theme', saved);
      }
    } catch (e) { /* localStorage unavailable; fall through to OS preference */ }
  })();

  function toggleTheme() {
    var root = document.documentElement;
    var current = root.getAttribute('data-theme');
    if (!current) {
      // No explicit override yet — read what's resolved from OS preference.
      current = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    var next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) {}
  }

  // Delegated so the button needs no inline onclick (the CSP would block it).
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('.theme-toggle')) {
      toggleTheme();
    }
  });
