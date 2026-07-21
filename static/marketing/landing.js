(function () {
  "use strict";

  // ── hero: расставить "зубы"-точки вдоль дуги и запустить анимацию ──
  var archWrap = document.querySelector(".hero-arch");
  if (archWrap) {
    var path = archWrap.querySelector(".arch-path");
    var dotsGroup = archWrap.querySelector(".tooth-dots");
    if (path && dotsGroup && path.getTotalLength) {
      var len = path.getTotalLength();
      var count = 16;
      for (var i = 0; i < count; i++) {
        var t = (i + 0.5) / count;
        var pt = path.getPointAtLength(t * len);
        var c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", pt.x.toFixed(1));
        c.setAttribute("cy", pt.y.toFixed(1));
        c.setAttribute("r", i % 4 === 0 ? "3.2" : "2.2");
        c.setAttribute("class", "tooth-dot");
        c.style.animationDelay = (0.9 + t * 0.6) + "s";
        dotsGroup.appendChild(c);
      }
    }
    requestAnimationFrame(function () {
      archWrap.classList.add("ready");
    });
  }

  // ── карточки модулей: проявление по очереди при попадании во вьюпорт ──
  var cards = document.querySelectorAll(".tooth-card");
  if (cards.length && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var idx = Array.prototype.indexOf.call(cards, entry.target);
          setTimeout(function () { entry.target.classList.add("in"); }, (idx % 4) * 70);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.18 });
    cards.forEach(function (c) { io.observe(c); });
  } else {
    cards.forEach(function (c) { c.classList.add("in"); });
  }

  // ── виджет "войти в клинику": <slug> + .stom.asia → переход в CRM ──
  var loginForm = document.querySelector("[data-clinic-login]");
  if (loginForm) {
    loginForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var input = loginForm.querySelector("input");
      var slug = (input.value || "").trim().toLowerCase()
        .replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
      if (!slug) { input.focus(); return; }
      window.location.href = "https://" + slug + "." + loginForm.dataset.clinicLogin + "/login/";
    });
  }
})();
