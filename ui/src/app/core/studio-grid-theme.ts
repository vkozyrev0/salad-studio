import { themeQuartz } from 'ag-grid-community';

/** A token from the page, with the shipped value as the pre-CSS fallback. */
function token(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** The studio's palette, read from the page's tokens so a grid matches it. */
const PALETTE = {
  bg: token('--bg', '#1B2836'),
  surface: token('--surface', '#243344'),
  surfaceHi: token('--surface-hi', '#2E4458'),
  well: token('--well', '#141E28'),
  fg: token('--fg', '#E8DCC8'),
  fgMuted: token('--fg-muted', '#A6B0C0'),
  accent: token('--accent', '#E39AA9'),
  accentFg: token('--accent-fg', '#1B2836'),
  border: token('--border', '#3A4F63'),
} as const;

/** The one AG Grid theme the studio uses. A grid that needs its own look adds params here. */
export const studioGridTheme = themeQuartz.withParams({
  backgroundColor: PALETTE.bg,
  foregroundColor: PALETTE.fg,
  accentColor: PALETTE.accent,
  headerBackgroundColor: PALETTE.surface,
  /* Headers are a ledger heading, not a menu: muted until you act on them. */
  headerTextColor: PALETTE.fgMuted,
  oddRowBackgroundColor: PALETTE.surface,
  borderColor: PALETTE.border,
  fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif",
  fontSize: '13px',
  headerFontWeight: 500,
  rowHeight: 34,
  headerHeight: 38,
  cellHorizontalPadding: 12,
  wrapperBorderRadius: 8,
});
