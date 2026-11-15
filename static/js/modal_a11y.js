/**
 * static/js/modal_a11y.js
 * Zentraler WCAG-2.2-AA Dialog-Controller für alle [role="dialog"]-Modals & Drawer:
 * - Setzt automatisch aria-labelledby auf die erste Modal-Überschrift (falls nicht vorhanden)
 * - Merkt das vorher fokussierte Element und stellt den Fokus beim Schließen wieder her
 * - Fängt Tab / Shift+Tab im jeweils obersten geöffneten Dialog (Focus-Trap)
 * - Schließt den obersten Dialog sauber per Escape-Taste
 */
(function () {
  if (typeof document === "undefined") return;

  const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
  ].join(", ");

  const openStack = [];
  const openerMap = new WeakMap();

  function isDialogVisible(el) {
    if (!el || !el.isConnected) return false;
    if (el.classList.contains("hidden")) return false;
    if (el.style && el.style.display === "none") return false;
    if (typeof window.getComputedStyle === "function") {
      const st = window.getComputedStyle(el);
      if (st.display === "none" || st.visibility === "hidden") return false;
    }
    return true;
  }

  function ensureHeadingLabel(dialog) {
    if (dialog.hasAttribute("aria-label") || dialog.hasAttribute("aria-labelledby")) return;
    const heading = dialog.querySelector("h1, h2, h3, h4");
    if (!heading) return;
    if (!heading.id) {
      heading.id = `${dialog.id || "archon-dialog"}-heading-${Math.random().toString(36).slice(2, 7)}`;
    }
    dialog.setAttribute("aria-labelledby", heading.id);
  }

  function getFocusable(dialog) {
    return Array.from(dialog.querySelectorAll(FOCUSABLE_SELECTOR)).filter((el) => {
      if (el.offsetParent === null && (!el.style || el.style.position !== "fixed")) {
        return false;
      }
      return !el.hasAttribute("disabled");
    });
  }

  function onDialogOpened(dialog) {
    if (!dialog || openStack.includes(dialog)) return;
    const active = document.activeElement;
    if (active && active !== document.body && !dialog.contains(active)) {
      openerMap.set(dialog, active);
    }
    if (!dialog.hasAttribute("tabindex")) {
      dialog.setAttribute("tabindex", "-1");
    }
    ensureHeadingLabel(dialog);
    openStack.push(dialog);

    requestAnimationFrame(() => {
      if (!isDialogVisible(dialog)) return;
      if (dialog.contains(document.activeElement)) return;
      const focusable = getFocusable(dialog);
      const target = focusable[0] || dialog;
      try {
        target.focus({ preventScroll: true });
      } catch (_e) {}
    });
  }

  function onDialogClosed(dialog) {
    const idx = openStack.indexOf(dialog);
    if (idx !== -1) openStack.splice(idx, 1);
    const opener = openerMap.get(dialog);
    openerMap.delete(dialog);
    if (opener && opener.isConnected && typeof opener.focus === "function") {
      requestAnimationFrame(() => {
        if (!openStack.length) {
          try {
            opener.focus({ preventScroll: true });
          } catch (_e) {}
        }
      });
    }
  }

  function syncDialogs() {
    const dialogs = document.querySelectorAll('[role="dialog"]');
    dialogs.forEach((dlg) => {
      const visible = isDialogVisible(dlg);
      const tracked = openStack.includes(dlg);
      if (visible && !tracked) {
        onDialogOpened(dlg);
      } else if (!visible && tracked) {
        onDialogClosed(dlg);
      }
    });
    for (let i = openStack.length - 1; i >= 0; i--) {
      if (!isDialogVisible(openStack[i])) {
        onDialogClosed(openStack[i]);
      }
    }
  }

  function closeTopDialog() {
    const visibleDialogs = openStack.filter(isDialogVisible);
    const top = visibleDialogs[visibleDialogs.length - 1];
    if (!top) return false;

    const closeBtn = top.querySelector(
      'button[onclick*="close" i], button[onclick*="Close"], button[aria-label*="Schließen" i], button[aria-label*="Close" i], button[title*="Schließen" i], button[title*="Close" i]'
    );
    if (closeBtn && typeof closeBtn.click === "function") {
      closeBtn.click();
    } else if (typeof top.onclick === "function") {
      top.click();
    }
    if (isDialogVisible(top)) {
      top.classList.add("hidden");
    }
    syncDialogs();
    return true;
  }

  document.addEventListener("keydown", (event) => {
    const visibleDialogs = openStack.filter(isDialogVisible);
    if (!visibleDialogs.length) return;
    const top = visibleDialogs[visibleDialogs.length - 1];

    if (event.key === "Escape") {
      if (closeTopDialog()) {
        event.preventDefault();
        event.stopPropagation();
      }
      return;
    }

    if (event.key === "Tab") {
      const focusable = getFocusable(top);
      if (!focusable.length) {
        event.preventDefault();
        try {
          top.focus({ preventScroll: true });
        } catch (_e) {}
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !top.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last || !top.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  function initObserver() {
    syncDialogs();
    const obs = new MutationObserver(() => syncDialogs());
    obs.observe(document.body || document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class", "style", "hidden", "role"],
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initObserver);
  } else {
    initObserver();
  }

  window.ArchonModalA11y = { syncDialogs, closeTopDialog };
})();
