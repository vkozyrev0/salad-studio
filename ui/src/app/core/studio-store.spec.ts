import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { NO_TOKEN, TOKEN, runToken, tokenInterceptor } from './api';
import { EMPTY_SHELL, ActionReply, PageReply } from './models';
import { StudioStore } from './studio-store';

describe('StudioStore.load', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([tokenInterceptor])), provideHttpClientTesting()],
    });
    store = TestBed.inject(StudioStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('marks the page loading and clears it when the reply arrives', async () => {
    const pending = store.load('tokens');
    expect(store.loading()).toBe(true);
    const reply: PageReply = {
      ok: true,
      page: 'tokens',
      state: { slots: [] },
      shell: EMPTY_SHELL,
      busy: {},
    };
    http.expectOne('/api/page/tokens').flush(reply);
    await pending;
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBe('');
  });
  it('names the printed URL when the page was opened without its token', () => {
    expect(NO_TOKEN).toContain('Open the URL the server printed');
  });

  it('puts a failed load on the page note instead of showing an empty page', async () => {
    // Vitest shares one service module across files; another file's failed load must not lock this store.
    (store as unknown as { locked: { set(value: boolean): void } }).locked.set(false);
    const pending = store.load('history');
    http.expectOne('/api/page/history').flush('nope', {
      status: 500,
      statusText: 'Server Error',
    });
    await pending;
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toContain('500');
    expect(store.locked()).toBe(false);
  });

  it('locks the window and names the token when the server refuses it', async () => {
    const pending = store.load('history');
    http.expectOne('/api/page/history').flush(
      { error: { kind: 'unauthorized', message: 'missing or wrong run token' } },
      { status: 403, statusText: 'Forbidden' },
    );
    await pending;
    expect(store.locked()).toBe(true);
    expect(store.loadError()).toContain('Open the URL the server printed');
  });
});

describe('Api.act', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([tokenInterceptor])), provideHttpClientTesting()],
    });
    store = TestBed.inject(StudioStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('sends the run token from the page URL on every action', async () => {
    const pending = store.act('tokens', 'reveal', { id: 'salad' });
    await new Promise((r) => setTimeout(r, 0));
    const req = http.expectOne('/api/action');
    expect(req.request.headers.get(TOKEN)).toBe(runToken);
    req.flush({ error: { kind: 'busy', message: 'x' } }, { status: 409, statusText: 'Conflict' });
    await pending;
  });
});

describe('StudioStore.act', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(withInterceptors([tokenInterceptor])), provideHttpClientTesting()],
    });
    store = TestBed.inject(StudioStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('clears the in-flight key and reports a refused action', async () => {
    const pending = store.act('tokens', 'check_keys');
    await new Promise((r) => setTimeout(r, 0));
    http.expectOne('/api/action').flush(
      { error: { kind: 'busy', message: 'tokens.check_keys is already running' } },
      { status: 409, statusText: 'Conflict' },
    );
    await pending;
    expect(store.inFlight().has('tokens.check_keys')).toBe(false);
    expect(store.dialog()?.body).toContain('already running');
  });

  it('does not let a reply for another page replace the open page', async () => {
    store.pageId.set('history');
    store.page.set({ current: 'history' });
    const pending = store.act('queue', 'select', { key: '1' });
    await new Promise((r) => setTimeout(r, 0));
    const reply: ActionReply = {
      ok: true,
      id: 'r1',
      page: 'queue',
      action: 'select',
      pending: false,
      error: '',
      state: { current: 'queue' },
      shell: EMPTY_SHELL,
      busy: {},
      effects: [],
    };
    http.expectOne('/api/action').flush(reply);
    await pending;
    expect(store.page()).toEqual({ current: 'history' });
  });

  it('opens the dialog with the server message when a reply fails', async () => {
    const pending = store.act('loras', 'save_edits');
    await new Promise((r) => setTimeout(r, 0));
    http.expectOne('/api/action').flush(replyFor('loras', false, 'strengths must be numbers'));
    await pending;
    expect(store.dialog()?.body).toBe('strengths must be numbers');
  });

  it('gives a repeat of an in-flight action the same reply, not null', async () => {
    const first = store.act('tokens', 'save_key', { values: {} });
    const second = store.act('tokens', 'save_key', { values: {} });
    await new Promise((r) => setTimeout(r, 0));
    const req = http.expectOne('/api/action');
    req.flush(replyFor('tokens', true, '', { slots: [] }));
    expect(await first).toMatchObject({ ok: true });
    expect(await second).toMatchObject({ ok: true });
  });
});

function replyFor(page: string, ok: boolean, error = '', state: unknown = {}): ActionReply {
  return { ok, id: '', page, action: 'x', pending: false, error, state, shell: EMPTY_SHELL, busy: {}, effects: [] };
}
