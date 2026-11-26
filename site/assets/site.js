(function () {
  "use strict";

  // 1. Theme toggle (persisted dark/light override, defaults to obsidian dark)
  var root = document.documentElement;
  try {
    var savedTheme = localStorage.getItem("archon-theme");
    if (savedTheme === "dark" || savedTheme === "light") {
      root.setAttribute("data-theme", savedTheme);
    }
  } catch (_) {}

  var themeBtn = document.querySelector("[data-theme-toggle]");
  if (themeBtn) {
    var syncLabel = function () {
      var cur = root.getAttribute("data-theme");
      if (!cur) {
        cur = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
      }
      themeBtn.textContent = cur === "dark" ? "Light" : "Dark";
      themeBtn.setAttribute("aria-label", cur === "dark" ? "Switch to light theme" : "Switch to dark theme");
    };
    syncLabel();
    themeBtn.addEventListener("click", function () {
      var cur = root.getAttribute("data-theme");
      if (!cur) {
        cur = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
      }
      var next = cur === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("archon-theme", next); } catch (_) {}
      syncLabel();
    });
  }

  // 2. Wrap <pre> blocks in clean terminal shell with non-overlapping header Copy button
  var copyLabel = document.body.getAttribute("data-copy") || "Copy";
  var copiedLabel = document.body.getAttribute("data-copied") || "Copied";
  document.querySelectorAll("pre").forEach(function (pre) {
    if (pre.parentElement && pre.parentElement.classList.contains("code-shell")) return;
    var shell = document.createElement("div");
    shell.className = "code-shell";
    var bar = document.createElement("div");
    bar.className = "code-bar";
    var langSpan = document.createElement("span");
    langSpan.textContent = pre.getAttribute("data-lang") || "shell";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.textContent = copyLabel;
    btn.addEventListener("click", function () {
      var text = pre.textContent || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          btn.textContent = copiedLabel;
          setTimeout(function () { btn.textContent = copyLabel; }, 1600);
        });
      }
    });
    bar.appendChild(langSpan);
    bar.appendChild(btn);
    pre.parentNode.insertBefore(shell, pre);
    shell.appendChild(bar);
    shell.appendChild(pre);
  });

  // 3. Interactive Cockpit Tab Showcase
  var cockpit = document.querySelector("[data-cockpit]");
  if (cockpit) {
    var tabs = Array.prototype.slice.call(cockpit.querySelectorAll("[data-shot-tab]"));
    var figures = Array.prototype.slice.call(cockpit.querySelectorAll("[data-shot-panel]"));
    var thumbs = Array.prototype.slice.call(document.querySelectorAll("[data-shot-thumb]"));
    var titleEl = cockpit.querySelector("[data-cockpit-title]");
    var activate = function (idx) {
      tabs.forEach(function (el, i) {
        var on = i === idx;
        el.classList.toggle("is-active", on);
        el.setAttribute("aria-selected", on ? "true" : "false");
        if (on && titleEl) titleEl.textContent = "ARCHON OS // " + el.textContent.toUpperCase();
      });
      figures.forEach(function (el, i) { el.classList.toggle("is-active", i === idx); });
      thumbs.forEach(function (el, i) { el.classList.toggle("is-active", i === idx); });
    };
    tabs.forEach(function (el, i) { el.addEventListener("click", function () { activate(i); }); });
    thumbs.forEach(function (el, i) { el.addEventListener("click", function () { activate(i); cockpit.scrollIntoView({ behavior: "smooth", block: "nearest" }); }); });
  }

  // 4. Bento Spotlight Cursor Tracking (desktop pointers only)
  if (window.matchMedia && window.matchMedia("(pointer: fine)").matches) {
    document.querySelectorAll(".feat").forEach(function (card) {
      card.addEventListener("pointermove", function (e) {
        var r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left) + "px");
        card.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    });
  }

  // 5. Multi-Layer Depth Parallax for Da-Vinci Silver Copperplate Stage
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced) {
    var stage = document.querySelector(".davinci-layers");
    if (stage) {
      var ticking = false;
      window.addEventListener("scroll", function () {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () {
          var sy = window.scrollY || 0;
          var yMain = Math.min(sy * 0.16, 180);
          var yDeep = Math.min(sy * 0.08, 90);
          stage.style.setProperty("--parallax-y", yMain.toFixed(1) + "px");
          stage.style.setProperty("--parallax-deep", (-yDeep).toFixed(1) + "px");
          ticking = false;
        });
      }, { passive: true });
    }

    // 6. Subtle Scroll Reveals
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -40px 0px", threshold: 0.05 });
      document.querySelectorAll("[data-reveal]").forEach(function (el) { io.observe(el); });
    } else {
      document.querySelectorAll("[data-reveal]").forEach(function (el) { el.classList.add("is-visible"); });
    }
  } else {
    document.querySelectorAll("[data-reveal]").forEach(function (el) { el.classList.add("is-visible"); });
  }

  // 7. Live Search & Category Filter on Phase 3 Directory Subpages
  var searchInput = document.querySelector("[data-dir-search]");
  var filterPills = Array.prototype.slice.call(document.querySelectorAll("[data-dir-cat]"));
  var dirItems = Array.prototype.slice.call(document.querySelectorAll("[data-dir-item]"));
  var countEl = document.querySelector("[data-dir-count]");
  if (dirItems.length && (searchInput || filterPills.length)) {
    var activeCat = "all";
    var applyFilter = function () {
      var q = searchInput ? searchInput.value.trim().toLowerCase() : "";
      var visible = 0;
      dirItems.forEach(function (item) {
        var cat = item.getAttribute("data-cat") || "";
        var txt = (item.textContent || "").toLowerCase();
        var matchCat = activeCat === "all" || cat === activeCat;
        var matchQ = !q || txt.indexOf(q) !== -1;
        var show = matchCat && matchQ;
        item.style.display = show ? "" : "none";
        if (show) visible++;
      });
      if (countEl) countEl.textContent = String(visible);
    };
    if (searchInput) searchInput.addEventListener("input", applyFilter);
    filterPills.forEach(function (pill) {
      pill.addEventListener("click", function () {
        activeCat = pill.getAttribute("data-dir-cat") || "all";
        filterPills.forEach(function (p) { p.classList.toggle("is-active", p === pill); });
        applyFilter();
      });
    });
  }
})();
