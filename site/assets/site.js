(function () {
  "use strict";

  // 1. Theme toggle (persisted dark/light override, defaults to obsidian dark)
  var root = document.documentElement;
  root.classList.add("js");
  var announce = function (msg) {
    var s = document.getElementById("a11y-status");
    if (s) s.textContent = msg;
  };
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
      themeBtn.textContent = themeBtn.getAttribute(cur === "dark" ? "data-light" : "data-dark") || (cur === "dark" ? "Light" : "Dark");
      themeBtn.setAttribute("aria-label", cur === "dark"
        ? (themeBtn.getAttribute("data-toggle-light-label") || "Switch to light theme")
        : (themeBtn.getAttribute("data-toggle-dark-label") || "Switch to dark theme"));
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
      applyThemeImages();
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
      var done = function () {
        btn.textContent = copiedLabel;
        btn.setAttribute("aria-label", copiedLabel);
        announce(copiedLabel);
        setTimeout(function () {
          btn.textContent = copyLabel;
          btn.setAttribute("aria-label", copyLabel);
        }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text, done); });
      } else {
        fallbackCopy(text, done);
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
        el.setAttribute("tabindex", on ? "0" : "-1");
        if (on && titleEl) titleEl.textContent = "ARCHON OS // " + el.textContent.toUpperCase();
      });
      figures.forEach(function (el, i) {
        el.classList.toggle("is-active", i === idx);
        el.hidden = i !== idx;
      });
      thumbs.forEach(function (el, i) {
        el.classList.toggle("is-active", i === idx);
        el.setAttribute("aria-pressed", i === idx ? "true" : "false");
      });
    };
    tabs.forEach(function (el, i) { el.addEventListener("click", function () { activate(i); }); });
    cockpit.querySelector(".cockpit-tabs").addEventListener("keydown", function (e) {
      var current = 0;
      tabs.forEach(function (t, i) { if (t.getAttribute("aria-selected") === "true") current = i; });
      var next = current;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (current + 1) % tabs.length;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (current - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = tabs.length - 1;
      else return;
      e.preventDefault();
      activate(next);
      tabs[next].focus();
    });
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

  // 5. Multi-Layer Depth Parallax for Da-Vinci Silver Copperplate Stage & Creation Hands
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced) {
    var stage = document.querySelector(".davinci-layers");
    var creationStage = document.querySelector(".creation-davinci-stage");
    if (stage || creationStage) {
      var ticking = false;
      var updateParallax = function () {
        var sy = window.scrollY || 0;
        if (stage) {
          var yMain = Math.min(sy * 0.16, 180);
          var yDeep = Math.min(sy * 0.08, 90);
          stage.style.setProperty("--parallax-y", yMain.toFixed(1) + "px");
          stage.style.setProperty("--parallax-deep", (-yDeep).toFixed(1) + "px");
        }
        if (creationStage) {
          var r = creationStage.getBoundingClientRect();
          var centerDelta = (r.top + r.height * 0.5) - (window.innerHeight * 0.5);
          var cShift = Math.max(-56, Math.min(56, centerDelta * -0.14));
          creationStage.style.setProperty("--creation-parallax", cShift.toFixed(1) + "px");
        }
        ticking = false;
      };
      updateParallax();
      window.addEventListener("scroll", function () {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(updateParallax);
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


  // 6b. Theme-synchronisierte Bilder: nur die aktive Variante wird geladen
  var themeImages = Array.prototype.slice.call(document.querySelectorAll("[data-theme-dark]"));
  var applyThemeImages = function () {
    var theme = root.getAttribute("data-theme");
    if (!theme) {
      theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    themeImages.forEach(function (img) {
      var target = img.getAttribute(theme === "light" ? "data-theme-light" : "data-theme-dark");
      if (target && img.getAttribute("src") !== target) img.setAttribute("src", target);
    });
  };
  applyThemeImages();
  var themeQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  if (themeQuery && themeQuery.addEventListener) themeQuery.addEventListener("change", applyThemeImages);

  // 8. Hero Quickstart Copy (mit Fallback ohne Clipboard-API)
  var copyCmdBtn = document.querySelector("[data-copy-cmd]");
  var quickstartEl = document.getElementById("quickstart-cmd");
  if (quickstartEl && copyCmdBtn) {
    copyCmdBtn.setAttribute("data-copy-cmd", quickstartEl.textContent.trim());
  }
  if (copyCmdBtn) {
    var copyDone = function () {
      var old = copyCmdBtn.textContent;
      copyCmdBtn.textContent = copiedLabel;
      copyCmdBtn.setAttribute("aria-label", copiedLabel);
      announce(copiedLabel);
      setTimeout(function () {
        copyCmdBtn.textContent = old;
        copyCmdBtn.setAttribute("aria-label", old);
      }, 1600);
    };
    copyCmdBtn.addEventListener("click", function () {
      var cmdEl = document.getElementById("quickstart-cmd");
      var text = (cmdEl && cmdEl.textContent ? cmdEl.textContent : "") || copyCmdBtn.getAttribute("data-copy-cmd") || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(copyDone, function () { fallbackCopy(text, copyDone); });
      } else {
        fallbackCopy(text, copyDone);
      }
    });
  }
  function fallbackCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    document.body.removeChild(ta);
    if (ok) done();
    else announce(document.body.getAttribute("data-copy-failed") || "Copy failed — please select and copy the command manually.");
  }


  // 6c. Mobile Navigation (Hamburger, ARIA, Escape)
  var navToggle = document.querySelector("[data-nav-toggle]");
  var mainNav = document.getElementById("main-nav");
  if (navToggle && mainNav) {
    var setNav = function (open) {
      mainNav.classList.toggle("is-open", open);
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    navToggle.addEventListener("click", function () {
      setNav(navToggle.getAttribute("aria-expanded") !== "true");
    });
    mainNav.addEventListener("click", function (e) {
      if (e.target.closest("a")) setNav(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setNav(false);
    });
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
