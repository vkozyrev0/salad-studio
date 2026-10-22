import { ApplicationRef, Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api } from './api';
import { ActionReply, Effect, Level, PAGES, PageReply, ShellState, StudioEvent, EMPTY_SHELL } from './models';

const LOG_CAP = 2000;

/** The server's or the browser's own words for a failed request. */
function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null) {
    const value = Reflect.get(err, 'message');
    if (typeof value === 'string' && value) return value;
  }
  return String(err);
}

/**
 * Everything the page knows, in signals.
 *
 * The server owns page state; this store mirrors it and holds only what the
 * server has no use for: which page is open, the dialogs on screen, and the
 * action keys currently in flight. One action chain per page keeps two posts
 * from racing, so a keystroke cannot overtake the action it belongs to.
 */
@Injectable({ providedIn: 'root' })
export class StudioStore {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly appRef = inject(ApplicationRef);

  readonly shell = signal<ShellState>(EMPTY_SHELL);
  readonly page = signal<unknown | null>(null);
  readonly pageId = signal<string>('config');
  /** Bumped after every completed navigation, so the page's frame re-reads the URL. */
  readonly routeRev = signal(0);
  readonly busy = signal<Record<string, boolean>>({});
  readonly logLines = signal<{ level: Level; text: string }[]>([]);
  readonly dialog = signal<Extract<Effect, { kind: 'dialog' }> | null>(null);
  readonly confirm = signal<Extract<Effect, { kind: 'confirm' }> | null>(null);
  readonly inFlight = signal<ReadonlySet<string>>(new Set());
  /** A page GET is running; a grid shows its spinner, not its empty copy. */
  readonly loading = signal(false);
  /** The last page GET failed; the frame says so instead of showing an empty page. */
  readonly loadError = signal('');

  readonly pageInfo = computed(() => PAGES.find((p) => p.id === this.pageId()) ?? PAGES[0]);
  readonly isBusy = computed(() => this.inFlight().size > 0);

  private stream: EventSource | null = null;
  private chains = new Map<string, Promise<unknown>>();

  /**
   * Ask for a render. A server-sent event or a router callback can run outside
   * change detection in a zoneless app, and this is how the page catches up.
   */
  /** Tell the page the route changed. Its frame watches this, not `router.url`. */
  touch(): void {
    this.routeRev.update((rev) => rev + 1);
  }

  requestRender(): void {
    this.appRef.tick();
  }

  /** Open the stream once per app. Every reconnection resyncs from `hello`. */
  connect(): void {
    if (this.stream) return;
    const stream = this.api.events();
    stream.addEventListener('hello', (e) => this.onHello(JSON.parse((e as MessageEvent).data)));
    stream.addEventListener('shell', (e) => this.shell.set(JSON.parse((e as MessageEvent).data).shell));
    stream.addEventListener('log', (e) => {
      const line = JSON.parse((e as MessageEvent).data);
      this.logLines.update((lines) => [...lines, { level: line.level, text: line.text }].slice(-LOG_CAP));
    });
    stream.addEventListener('queue_changed', () => {
      if (this.pageId() === 'queue') void this.load(this.pageId());
    });
    stream.addEventListener('salad_logs', () => {
      if (this.pageId() === 'logs') void this.load(this.pageId());
    });
    stream.addEventListener('generated', (e) => this.apply(JSON.parse((e as MessageEvent).data).reply));
    stream.addEventListener('action_done', (e) => {
      const event = JSON.parse((e as MessageEvent).data);
      this.apply(event.reply);
      this.clearFlight(event.reply.page, event.reply.action);
    });
    this.stream = stream;
  }

  private loadSeq = 0;

  async load(id: string): Promise<void> {
    const seq = ++this.loadSeq;
    // A hop starts clean; a refresh of the same page keeps its rows on screen.
    if (this.pageId() !== id) this.page.set(null);
    this.pageId.set(id);
    this.loading.set(true);
    this.loadError.set('');
    try {
      const reply = await this.api.page(id);
      if (seq !== this.loadSeq) return;
      this.page.set(reply.state);
      this.shell.set(reply.shell);
      this.busy.set(reply.busy);
    } catch (err) {
      if (seq !== this.loadSeq) return;
      this.loadError.set(messageOf(err));
    } finally {
      if (seq === this.loadSeq) this.loading.set(false);
    }
  }

  /** Run one action. Returns the reply, or null when the same action is already in flight. */
  act(page: string, action: string, args: object = {}): Promise<ActionReply | null> {
    const key = `${page}.${action}`;
    if (this.inFlight().has(key)) return Promise.resolve(null);
    this.addFlight(key);
    const prior = this.chains.get(page) ?? Promise.resolve();
    const next = prior
      .catch(() => undefined)
      .then(async () => {
        try {
          const reply = await this.api.act(page, action, args);
          this.apply(reply);
          if (!reply.pending) this.clearFlight(page, action);
          return reply;
        } finally {
          if (this.chains.get(page) === next) this.chains.delete(page);
        }
      });
    this.chains.set(page, next);
    return next as Promise<ActionReply | null>;
  }

  async confirmYes(): Promise<void> {
    const pending = this.confirm();
    this.confirm.set(null);
    if (!pending) return;
    const reply = await this.api.confirm(pending.token);
    this.apply(reply);
  }

  dismissDialog(): void {
    this.dialog.set(null);
  }

  dismissConfirm(): void {
    this.confirm.set(null);
  }

  private apply(reply: ActionReply | PageReply): void {
    this.shell.set(reply.shell);
    if ('state' in reply) this.page.set(reply.state);
    if ('busy' in reply) this.busy.set(reply.busy);
    if (!('effects' in reply) || !reply.effects) return;
    for (const effect of reply.effects) {
      if (effect.kind === 'dialog') this.dialog.set(effect);
      else if (effect.kind === 'confirm') this.confirm.set(effect);
      else if (effect.kind === 'navigate') void this.router.navigateByUrl('/' + effect.page);
    }
  }

  private onHello(event: Extract<StudioEvent, { type: 'hello' }>): void {
    this.shell.set(event.shell);
    this.logLines.set(event.logs.slice(-LOG_CAP));
    void this.load(this.pageId());
  }

  private addFlight(key: string): void {
    this.inFlight.update((set) => new Set(set).add(key));
  }

  private clearFlight(page: string, action: string): void {
    this.inFlight.update((set) => {
      const next = new Set(set);
      next.delete(`${page}.${action}`);
      return next;
    });
  }
}
