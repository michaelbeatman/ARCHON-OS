export interface ColorSwatch {
  hex: string;
  label: string;
}

export interface ColorPaletteGroup {
  id: string;
  name: string;
  icon: string;
  colors: ColorSwatch[];
}

// User-provided color palettes from screenshots
export const USER_COLOR_PALETTES: ColorPaletteGroup[] = [
  {
    id: 'ocean',
    name: 'Ozean Blau',
    icon: '🌊',
    colors: [
      { hex: '#012A4A', label: '#012A4A' },
      { hex: '#013A63', label: '#013A63' },
      { hex: '#01497C', label: '#01497C' },
      { hex: '#014F86', label: '#014F86' },
      { hex: '#2A6F97', label: '#2A6F97' },
      { hex: '#2C7DA0', label: '#2C7DA0' },
      { hex: '#468FAF', label: '#468FAF' },
      { hex: '#61A5C2', label: '#61A5C2' },
      { hex: '#89C2D9', label: '#89C2D9' },
      { hex: '#A9D6E5', label: '#A9D6E5' },
    ]
  },
  {
    id: 'emerald',
    name: 'Smaragd & Waldgrün',
    icon: '🌿',
    colors: [
      { hex: '#D8F3DC', label: '#D8F3DC' },
      { hex: '#B7E4C7', label: '#B7E4C7' },
      { hex: '#95D5B2', label: '#95D5B2' },
      { hex: '#74C69D', label: '#74C69D' },
      { hex: '#52B788', label: '#52B788' },
      { hex: '#40916C', label: '#40916C' },
      { hex: '#2D6A4F', label: '#2D6A4F' },
      { hex: '#1B4332', label: '#1B4332' },
      { hex: '#081C15', label: '#081C15' },
    ]
  },
  {
    id: 'slate_red',
    name: 'Schiefer & Rubinrot',
    icon: '🔴',
    colors: [
      { hex: '#2B2D42', label: '#2B2D42' },
      { hex: '#8D99AE', label: '#8D99AE' },
      { hex: '#EDF2F4', label: '#EDF2F4' },
      { hex: '#EF233C', label: '#EF233C' },
      { hex: '#D90429', label: '#D90429' },
    ]
  },
  {
    id: 'dark_gold',
    name: 'Dunkel & Gold',
    icon: '👑',
    colors: [
      { hex: '#000000', label: '#000000' },
      { hex: '#14213D', label: '#14213D' },
      { hex: '#FCA311', label: '#FCA311' },
      { hex: '#E5E5E5', label: '#E5E5E5' },
      { hex: '#FFFFFF', label: '#FFFFFF' },
    ]
  }
];

// Hex helper functions
export function hexToRgba(hex: string, alpha: number): string {
  let cleanHex = hex.replace('#', '');
  if (cleanHex.length === 3) {
    cleanHex = cleanHex.split('').map(c => c + c).join('');
  }
  const num = parseInt(cleanHex, 16);
  if (isNaN(num)) return `rgba(16, 185, 129, ${alpha})`;
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function adjustBrightness(hex: string, percent: number): string {
  let cleanHex = hex.replace('#', '');
  if (cleanHex.length === 3) {
    cleanHex = cleanHex.split('').map(c => c + c).join('');
  }
  let num = parseInt(cleanHex, 16);
  if (isNaN(num)) return hex;

  let r = (num >> 16) + Math.round(255 * (percent / 100));
  let g = ((num >> 8) & 0x00FF) + Math.round(255 * (percent / 100));
  let b = (num & 0x0000FF) + Math.round(255 * (percent / 100));

  r = Math.min(255, Math.max(0, r));
  g = Math.min(255, Math.max(0, g));
  b = Math.min(255, Math.max(0, b));

  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

export function applyCustomAccentColors(primaryHex: string, secondaryHex?: string) {
  if (typeof document === 'undefined') return;

  const root = document.documentElement;

  // Primary Accent
  const primary = primaryHex || '#10b981';
  const primaryHover = adjustBrightness(primary, -12);
  root.style.setProperty('--accent-primary', primary);
  root.style.setProperty('--accent-primary-hover', primaryHover);
  root.style.setProperty('--accent-light-text', primary);

  // Secondary Accent (Light Background / Soft Pill Highlight)
  const secondary = secondaryHex || hexToRgba(primary, 0.12);
  const secondaryBorder = adjustBrightness(secondary, -15);

  root.style.setProperty('--accent-light-bg', secondary);
  root.style.setProperty('--accent-light-border', hexToRgba(primary, 0.3));
  root.style.setProperty('--accent-soft-bg', secondary);
  root.style.setProperty('--accent-soft-border', secondaryBorder);
  root.style.setProperty('--accent-dark-soft-bg', hexToRgba(primary, 0.2));
  root.style.setProperty('--accent-dark-soft-border', hexToRgba(primary, 0.4));
}
