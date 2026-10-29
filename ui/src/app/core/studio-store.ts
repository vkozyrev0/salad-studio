import { ApplicationRef, Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Api, NO_TOKEN, runToken, unauthorized } from './api';
import { ActionReply, Effect, Level, PAGES, PageReply, ShellState, StudioEvent, EMPTY_SHELL } from './models';

const LOG_CAP = 2000;

/** The server's or the browser's own words for a failed request. */
function messageOf(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const body = Reflect.get(err, 'error');
    if (typeof body === 'object' && body !== null) {
      const detail = Reflect.get(body, 'error');
      const message =
        detail && typeof detail === 'object' ? Reflect.get(detail, 'message') : Reflect.get(body, 'message');
      if (typeof message === 'string' && message) return message;
    }
  }
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
  readonly logLines = signal<{ level: Level; text: string }[]>([]);
  readonly dialog = signal<Extract<Effect, { kind: 'dialog' }> | null>(null);
  readonly confirm = signal<Extract<Effect, { kind: 'confirm' }> | null>(null);
  /** The one key a row's Show asked for. It lives here, not in the page state. */
  readonly revealed = signal<Extract<Effect, { kind: 'reveal' }> | null>(null);
  /** What each provider last answered, laid over the slots a page was loaded with. */
  readonly tokenStates = signal<Record<string, string>>({});
  readonly inFlight = signal<ReadonlySet<string>>(new Set());
  /** A page GET is running; a grid shows its spinner, not its empty copy. */
  readonly loading = signal(false);
  /** The last page GET failed; the frame says so instead of showing an empty page. */
  readonly loadError = signal('');
  /** The server refused the run token; the window shows how to open the page instead. */
  readonly locked = signal(runToken === '');

  readonly pageInfo = computed(() => PAGES.find((p) => p.id === this.pageId()) ?? PAGES[0]);
  readonly isBusy = computed(() => this.inFlight().size > 0);

  private stream: EventSource | null = null;
  private chains = new Map<string, Promise<unknown>>();
  /** A connection has been open before; the first one is the opening, not a reconnect. */
  private opened = false;
  /** The call each in-flight key is running, so a repeat of it joins that call. */
  private readonly joined = new Map<string, Promise<ActionReply | undefined>>();
  private readonly keys = new Map<Promise<unknown>, string>();
  /** The action key each confirm box stands for, held from the box until the person answers it. */
  private readonly confirmKey = new Map<string, string>();

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
    // A reply that was pending when the stream dropped never arrives, so a
    // reconnect takes every key as free rather than leave a button wedged.
    stream.addEventListener('open', () => {
      if (this.opened) this.dropFlights();
      this.opened = true;
    });
    // A refused stream never delivers the first page's state, so its failure carries the token's answer.
    if (!runToken) stream.addEventListener('error', () => this.locked.set(true));
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
    } catch (err) {
      if (seq !== this.loadSeq) return;
      // Every page fails the same way without the token, so the whole window says how to open it.
      const refused = unauthorized(err) || this.locked();
      if (refused) this.locked.set(true);
      this.loadError.set(refused ? NO_TOKEN : messageOf(err));
    } finally {
      if (seq === this.loadSeq) this.loading.set(false);
    }
  }

  /**
   * Run one action. A repeat of one already in flight joins it rather than
   * posting twice, so every caller gets that action's own reply or undefined.
   */
  act(page: string, action: string, args: object = {}): Promise<ActionReply | undefined> {
    const key = `${page}.${action}`;
    const joined = this.joined.get(key);
    if (joined) return joined;
    this.addFlight(key);
    const prior = this.chains.get(page) ?? Promise.resolve();
    const next: Promise<ActionReply | undefined> = prior
      .catch(() => undefined)
      .then(() => {
        // The action it waited on may have left the key free or been taken again.
        if (!this.inFlight().has(key)) return undefined;
        return this.post(page, action, key, args);
      })
      .finally(() => {
        if (this.joined.get(key) === next) this.joined.delete(key);
        this.keys.delete(next);
        if (this.chains.get(page) === next) this.chains.delete(page);
      });
    this.chains.set(page, next);
    this.keys.set(next, key);
    // A repeat joins this call's own outcome, so two callers never disagree on what happened.
    this.joined.set(key, next);
    return next as Promise<ActionReply | undefined>;
  }

  private async post(page: string, action: string, key: string, args: object): Promise<ActionReply | undefined> {
    try {
      const reply = await this.api.act(page, action, args);
      // A reply for a page left behind keeps its shell, busy map and effects, and drops its state.
      if (reply.page === this.pageId()) this.apply(reply);
      else this.shell.set(reply.shell);
      if (!reply.ok && reply.error) {
        this.dialog.set({ kind: 'dialog', title: 'The action failed', body: reply.error, level: 'error' });
      }
      if (!reply.pending) this.clearFlight(page, action);
      return reply;
    } catch (err) {
      // A refused or dropped request must not leave the button spinning
      // forever; say what happened and let the same action be tried again.
      this.clearFlight(page, action);
      this.fail(err);
      return undefined;
    }
  }

  async confirmYes(): Promise<void> {
    const pending = this.confirm();
    this.confirm.set(null);
    if (!pending) return;
    const key = this.confirmKey.get(pending.token);
    this.confirmKey.delete(pending.token);
    // The first press already sent it; a second while that is out would make the box see a busy 409.
    if (key && this.inFlight().has(key)) return;
    if (key) this.addFlight(key);
    try {
      const reply = await this.api.confirm(pending.token);
      this.apply(reply);
      if (key) this.clearFlight(reply.page, reply.action);
    } catch (err) {
      if (key) this.clearFlight(key.slice(0, key.indexOf('.')), key.slice(key.indexOf('.') + 1));
      this.fail(err);
    }
  }

  /** A failed post: the dialog says why, and a refused token locks the whole window. */
  private fail(err: unknown): void {
    const refused = unauthorized(err);
    if (refused) this.locked.set(true);
    this.dialog.set({
      kind: 'dialog',
      title: 'The action failed',
      body: refused ? NO_TOKEN : messageOf(err),
      level: 'error',
    });
  }

  dismissDialog(): void {
    this.dialog.set(null);
  }

  dismissConfirm(): void {
    const box = this.confirm();
    this.confirm.set(null);
    // A declined confirm means the action will not run, so its button comes back.
    const key = box ? this.confirmKey.get(box.token) : undefined;
    if (!key) return;
    this.confirmKey.delete(box!.token);
    this.clearFlight(key.slice(0, key.indexOf('.')), key.slice(key.indexOf('.') + 1));
  }

  private apply(reply: ActionReply | PageReply): void {
    this.shell.set(reply.shell);
    // A slow reply from a page the user has left must not replace the page
    // they are reading now. Its shell, busy map and effects still apply.
    if ('state' in reply && reply.page === this.pageId()) this.page.set(reply.state);
    if (!('effects' in reply) || !reply.effects) return;
    for (const effect of reply.effects) {
      if (effect.kind === 'dialog') this.dialog.set(effect);
      else if (effect.kind === 'confirm') {
        this.confirm.set(effect);
        // A confirmed action is not in flight by name, so its key is held until the answer.
        if ('page' in reply) this.confirmKey.set(effect.token, `${reply.page}.${reply.action}`);
      }
      else if (effect.kind === 'navigate') void this.router.navigateByUrl('/' + effect.page);
      else if (effect.kind === 'reveal') this.revealed.set(effect);
      else if (effect.kind === 'token_state') this.tokenStates.update((states) => ({ ...states, ...effect.states }));
    }
  }

  private onHello(event: Extract<StudioEvent, { type: 'hello' }>): void {
    this.shell.set(event.shell);
    this.logLines.set(event.logs.slice(-LOG_CAP));
    void this.load(this.pageId());
  }

  /**
   * A reply that was pending when the stream dropped may never arrive, so a
   * reconnect starts each button free, and a call still waiting posts its own
   * action again rather than be skipped by the key that went away.
   */
  private dropFlights(): void {
    for (const [call, key] of this.keys) {
      const page = key.slice(0, key.lastIndexOf('.'));
      if (this.chains.get(page) === call) this.chains.set(page, Promise.resolve());
    }
    this.inFlight.set(new Set());
    this.joined.clear();
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
