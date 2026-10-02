// ReCircuit shared JS: hamburger menu + dropdowns (plain script, no framework).
// Convention: all live numbers must come from /api/* — never hardcode.
(function () {
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.getElementById('site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }
  document.querySelectorAll('.nav-drop-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const drop = btn.closest('.nav-drop');
      const wasOpen = drop.classList.contains('open');
      document.querySelectorAll('.nav-drop.open').forEach((d) => d.classList.remove('open'));
      if (!wasOpen) {
        drop.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      } else {
        btn.setAttribute('aria-expanded', 'false');
      }
    });
  });
  document.addEventListener('click', () => {
    document.querySelectorAll('.nav-drop.open').forEach((d) => d.classList.remove('open'));
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.nav-drop.open').forEach((d) => d.classList.remove('open'));
      if (nav) nav.classList.remove('nav-open');
    }
  });
})();
