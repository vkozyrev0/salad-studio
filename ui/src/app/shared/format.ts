/**
 * The small formatters the tables share. Times are local, as the Python pages
 * render them with `time.localtime`; the desktop and the server are one machine.
 */

/** `2026-10-21 18:47` from epoch seconds, or empty for a missing stamp. */
export function dateTime(ts: unknown): string {
  return inZone(ts, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/** `18:47` from epoch seconds, or empty. */
export function clock(ts: unknown): string {
  return inZone(ts, { hour: '2-digit', minute: '2-digit' });
}

function inZone(ts: unknown, options: Intl.DateTimeFormatOptions): string {
  const seconds = Number(ts);
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const date = new Date(seconds * 1000);
  // en-CA is the locale whose short date is already the year-month-day order.
  const parts =
    options.year !== undefined
      ? new Intl.DateTimeFormat('en-CA', options).formatToParts(date)
      : new Intl.DateTimeFormat('en-GB', options).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  const time = options.hour !== undefined ? `${get('hour')}:${get('minute')}` : '';
  if (options.year === undefined) return time;
  return `${get('year')}-${get('month')}-${get('day')}${time ? ' ' + time : ''}`;
}

/** `prompt_history.preview`: one line, cut at `n` characters with an ellipsis. */
export function preview(text: unknown, n = 90): string {
  const one = String(text ?? '').replace(/\s+/g, ' ').trim();
  return one.length <= n ? one : one.slice(0, n - 1) + '…';
}

/** The first `count` parts of a ` · ` stats line, joined the same way. */
export function statsHead(stats: unknown, count = 3): string {
  return String(stats ?? '')
    .split('·')
    .map((part) => part.trim())
    .slice(0, count)
    .filter(Boolean)
    .join(' · ');
}

/** A number read from a text box, or null when the box is blank or not a number. */
export function numberOrNull(raw: string, integer = false): number | null {
  const text = raw.trim();
  if (!text) return null;
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  return integer ? Math.trunc(value) : value;
}
