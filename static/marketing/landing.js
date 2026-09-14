(function () {
  "use strict";

  // ── карточки возможностей: проявление по очереди при попадании во вьюпорт ──
  var cards = document.querySelectorAll(".feature-card");
  if (cards.length && "IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var idx = Array.prototype.indexOf.call(cards, entry.target);
          setTimeout(function () { entry.target.classList.add("in"); }, (idx % 3) * 70);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.18 });
    cards.forEach(function (c) { io.observe(c); });
  } else {
    cards.forEach(function (c) { c.classList.add("in"); });
  }

  // ── FAQ (<details>/<summary>) — оставляем только один пункт открытым за раз ──
  var faqItems = document.querySelectorAll(".faq-item");
  faqItems.forEach(function (item) {
    item.addEventListener("toggle", function () {
      if (!item.open) return;
      faqItems.forEach(function (other) {
        if (other !== item) other.open = false;
      });
    });
  });

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
