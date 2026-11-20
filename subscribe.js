// The launch-signup form (index.html). A file, not an inline <script>, so the
// CSP can keep script-src 'self' (Story 18.10).
(function () {
  var form = document.getElementById('notify');
  var msg = document.getElementById('notify-msg');
  if (!form || !msg) return;
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var button = form.querySelector('button');
    button.disabled = true;
    msg.textContent = 'Sending…';
    msg.className = 'notify-msg';
    fetch('/api/subscribe', { method: 'POST', body: new FormData(form) })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        msg.textContent = data.message || data.error || 'Something went wrong.';
        msg.className = 'notify-msg ' + (data.success ? 'ok' : 'bad');
        if (data.success) form.reset();
      })
      .catch(function () {
        msg.textContent = 'Something went wrong. Please try again.';
        msg.className = 'notify-msg bad';
      })
      .then(function () { button.disabled = false; });
  });
})();
