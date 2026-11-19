// The release countdown (Story 18.8). Decoration only: the date is real text on
// the page, and the worker already marks the page "out" from the moment on, so
// nothing here is needed for the page to be right.
//
// What it does: reads the moment from the countdown's data-release attribute
// (written by scripts/build_launch.py from src/launch.js; no date is typed
// here), shows the timer, ticks it, and at zero flips the open page to "out".
// It counts from the SERVER's clock (<html data-now>, stamped by the worker)
// when it has it, so a visitor whose clock is wrong is not told "Out now" early.
(function () {
  var root = document.documentElement;
  var cd = document.querySelector('[data-release]');
  if (!cd) return;
  var release = Number(cd.getAttribute('data-release'));
  if (!isFinite(release)) return;
  var serverNow = Number(root.getAttribute('data-now'));
  var offset = isFinite(serverNow) && serverNow > 0 ? serverNow - Date.now() : 0;
  var cells = cd.querySelectorAll('[data-u]');
  var timer = null;

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function tick() {
    var ms = release - (Date.now() + offset);
    if (ms <= 0) {
      root.setAttribute('data-launch', 'out');
      if (timer) clearInterval(timer);
      return;
    }
    var s = Math.floor(ms / 1000);
    var v = { d: Math.floor(s / 86400), h: Math.floor(s % 86400 / 3600), m: Math.floor(s % 3600 / 60), s: s % 60 };
    for (var i = 0; i < cells.length; i++) {
      var u = cells[i].getAttribute('data-u');
      cells[i].textContent = u === 'd' ? String(v.d) : pad(v[u]);
    }
    cd.hidden = false;
  }

  tick();
  if (root.getAttribute('data-launch') !== 'out') timer = setInterval(tick, 1000);
})();
