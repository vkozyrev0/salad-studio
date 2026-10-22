import { themeQuartz } from 'ag-grid-community';

/** The studio's palette, role for role, so a grid matches the page around it. */
const PALETTE = {
  bg: '#1B2836',
  surface: '#243344',
  surfaceHi: '#2E4458',
  well: '#141E28',
  fg: '#E8DCC8',
  fgMuted: '#A6B0C0',
  accent: '#E39AA9',
  accentFg: '#1B2836',
  border: '#3A4F63',
} as const;

/** The one AG Grid theme the studio uses. A grid that needs its own look adds params here. */
export const studioGridTheme = themeQuartz.withParams({
  backgroundColor: PALETTE.bg,
  foregroundColor: PALETTE.fg,
  accentColor: PALETTE.accent,
  headerBackgroundColor: PALETTE.surface,
  headerTextColor: PALETTE.accent,
  oddRowBackgroundColor: PALETTE.surface,
  borderColor: PALETTE.border,
  fontFamily: "'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif",
  fontSize: '13px',
  headerFontWeight: 600,
  rowHeight: 34,
  headerHeight: 36,
  cellHorizontalPadding: 10,
  wrapperBorderRadius: 8,
});
