/* Меню, появление блоков, плавная прокрутка, «Скопировать телефон». */
(function () {
  var root = document.documentElement;
  root.classList.add('js');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.addEventListener('DOMContentLoaded', function () {
    /* Меню */
    var btn = document.querySelector('.menu-btn');
    var panel = document.getElementById('menu-panel');
    function setOpen(open) {
      root.classList.toggle('menu-open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open) {
        panel.removeAttribute('inert');
        panel.querySelector('.menu-close').focus();
      } else {
        panel.setAttribute('inert', '');
      }
    }
    if (btn && panel) {
      btn.addEventListener('click', function () { setOpen(true); });
      document.querySelectorAll('[data-menu-close]').forEach(function (el) {
        el.addEventListener('click', function () { setOpen(false); btn.focus(); });
      });
      panel.querySelectorAll('a').forEach(function (a) {
        a.addEventListener('click', function () { setOpen(false); });
      });
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && root.classList.contains('menu-open')) { setOpen(false); btn.focus(); }
      });
      window.matchMedia('(min-width: 1024px)').addEventListener('change', function (m) {
        if (m.matches) setOpen(false);
      });
    }

    /* Появление блоков */
    var blocks = document.querySelectorAll('.reveal');
    if (reduce || !('IntersectionObserver' in window)) {
      blocks.forEach(function (b) { b.classList.add('in'); });
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
        });
      }, { threshold: 0 });
      blocks.forEach(function (b) { io.observe(b); });
    }

    /* Плавная прокрутка к якорям на странице */
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var target = document.getElementById(a.getAttribute('href').slice(1));
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
        target.focus({ preventScroll: true });
      });
    });

    /* Скопировать телефон */
    document.querySelectorAll('.copy-phone').forEach(function (b) {
      var status = b.parentNode.querySelector('.copy-status');
      function say(t) { if (status) status.textContent = t; }
      b.addEventListener('click', function () {
        var phone = b.getAttribute('data-phone');
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(phone).then(function () { say('Скопировано'); },
            function () { say('Не удалось скопировать. Номер: ' + phone); });
        } else {
          say('Не удалось скопировать. Номер: ' + phone);
        }
      });
    });
  });
})();
