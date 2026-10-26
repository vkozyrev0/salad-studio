/** The wire types the server sends. Mirrors `salad_studio/web/` field for field. */

export type Level = 'info' | 'ok' | 'warn' | 'error';

export interface ShellState {
  current: string;
  status: { text: string; level: Level };
  note: { text: string; level: Level };
  gen: { word: string; busy: boolean };
  saladWord: string;
  counts: [number, number, number];
  plates: { name: string; url: string }[];
  busy: Record<string, boolean>;
}

export type Effect =
  | { kind: 'dialog'; title: string; body: string; level: Level }
  | { kind: 'confirm'; token: string; title: string; body: string }
  | { kind: 'navigate'; page: string }
  /** One row's saved key, handed to the page that pressed Show. Never broadcast. */
  | { kind: 'reveal'; id: string; value: string }
  /** One provider's last answer, so a Check turns its own dot. */
  | { kind: 'token_state'; states: Record<string, string> };

export interface ActionReply {
  ok: boolean;
  id: string;
  page: string;
  /** The action name without the page prefix, so a done event can clear its lock. */
  action: string;
  pending: boolean;
  error: string;
  state: unknown;
  shell: ShellState;
  busy: Record<string, boolean>;
  effects: Effect[];
}

export interface PageReply {
  ok: boolean;
  page: string;
  state: unknown;
  shell: ShellState;
  busy: Record<string, boolean>;
}

export type StudioEvent =
  | { seq: number; type: 'hello'; shell: ShellState; logs: { level: Level; text: string }[] }
  | { seq: number; type: 'shell'; shell: ShellState }
  | { seq: number; type: 'log'; level: Level; text: string }
  | { seq: number; type: 'salad_logs'; version: number }
  | { seq: number; type: 'queue_changed' }
  | { seq: number; type: 'generated'; reply: ActionReply }
  | { seq: number; type: 'action_done'; id: string; reply: ActionReply };

export interface PageInfo {
  id: string;
  title: string;
  subtitle: string;
  number: string;
}

/** The rail, in order. The number is the page's position, which the server also uses. */
export const PAGES: readonly PageInfo[] = [
  { id: 'config', title: 'Config', subtitle: 'Profiles, images and the two hostings.', number: '01' },
  { id: 'settings', title: 'Prompt Settings', subtitle: 'The graph, the knobs and the LoRAs the request carries.', number: '02' },
  { id: 'tokens', title: 'Tokens', subtitle: 'Provider keys, and what each one last answered.', number: '03' },
  { id: 'loras', title: 'LoRAs', subtitle: 'The catalog plus the extras you add.', number: '04' },
  { id: 'editor', title: 'Prompt Editor', subtitle: "The JSON body POSTed to the target's /prompt. The graph is drawn from it.", number: '05' },
  { id: 'assist', title: 'Prompt Assist', subtitle: 'Ask for a prompt fix, then commit it.', number: '06' },
  { id: 'catalog', title: 'Prompt Catalog', subtitle: 'Kept prompts, by short name.', number: '07' },
  { id: 'import', title: 'Import', subtitle: 'Paste a Comfy workflow or Civitai data, then convert.', number: '08' },
  { id: 'history', title: 'Prompt History', subtitle: 'Every request, with its prompt and graph.', number: '09' },
  { id: 'queue', title: 'Queue', subtitle: 'One row per request; the container is stopped when it sits idle.', number: '10' },
  { id: 'logs', title: 'Logs', subtitle: 'Studio and HTTP lines, secrets masked.', number: '11' },
] as const;

/** The id the router is showing, read from the URL rather than the store. */
export function pageIdFromUrl(url: string): string {
  const path = url.split('?')[0].split('#').pop() ?? '';
  return path.replace(/^\//, '') || PAGES[0].id;
}

export const REST_TEXT = 'Start on Config: pick a profile and its target.   Ctrl+Tab moves between pages.';

export const EMPTY_SHELL: ShellState = {
  current: 'config',
  status: { text: REST_TEXT, level: 'info' },
  note: { text: '', level: 'info' },
  gen: { word: 'Idle', busy: false },
  saladWord: '',
  counts: [0, 0, 0],
  plates: [],
  busy: {},
};
