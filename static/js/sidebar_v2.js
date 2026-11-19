// M63: Linkes Menue (Sidebar) einklappbare Sektionen & kompakte untere linke Ecke
(function () {
  const STORAGE_KEY = 'archon_sidebar_collapsed_sections';

  function loadState() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (_) {
      return {};
    }
  }

  function toggleSection(sectionId) {
    const el = document.getElementById(sectionId);
    if (!el) return;
    const isHidden = el.classList.toggle('hidden');
    const st = loadState();
    st[sectionId] = isHidden;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(st)); } catch (_) {}
  }

  function applySavedSections() {
    const st = loadState();
    Object.keys(st).forEach(id => {
      const el = document.getElementById(id);
      if (el && st[id]) el.classList.add('hidden');
    });
  }

  document.addEventListener('DOMContentLoaded', applySavedSections);
  window.archonSidebarV2 = { toggleSection, applySavedSections };
})();
