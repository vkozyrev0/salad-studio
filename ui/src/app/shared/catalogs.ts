/**
 * The choices that are constants in the Python modules, mirrored here.
 *
 * They are the labels a select shows and the id or key it sends, paired so the
 * page never matches on display text. A select whose list the server grows
 * (profiles, images) is built from state instead and is not here.
 */

export const SCHEDULERS = [
  { value: 'flux2', label: 'Flux2 (Klein)' },
  { value: 'simple', label: 'Simple (Civitai)' },
] as const;

/** `request_json.UNET_LABELS`, with the blank choice Import's menu starts on. */
export const UNETS = [
  { value: '', label: '-' },
  { value: 'Base 9B', label: 'Base 9B' },
  { value: 'Distilled 9B', label: 'Distilled 9B' },
  { value: 'SNOFS 9B', label: 'SNOFS 9B' },
] as const;

/** `pages/config.PROBE_KEYS`, in the order the probe rows show them. */
export const PROBE_KEYS = [
  'path',
  'port',
  'initial_delay_seconds',
  'period_seconds',
  'timeout_seconds',
  'success_threshold',
  'failure_threshold',
] as const;

export type ProbeKey = (typeof PROBE_KEYS)[number];

/** The wire field's name, as a person reads it on the label above the box. */
export const PROBE_LABELS: Record<ProbeKey, string> = {
  path: 'Path',
  port: 'Port',
  initial_delay_seconds: 'Delay (s)',
  period_seconds: 'Period (s)',
  timeout_seconds: 'Timeout (s)',
  success_threshold: 'Successes',
  failure_threshold: 'Failures',
};

/** A probe field's width: a port is three digits, a delay is five, a path needs the most. */
export const PROBE_WIDTHS: Record<ProbeKey, number> = {
  path: 180,
  port: 76,
  initial_delay_seconds: 96,
  period_seconds: 96,
  timeout_seconds: 96,
  success_threshold: 96,
  failure_threshold: 96,
};

export const DEFAULT_LOCAL_URL = 'http://localhost:1234/v1';
