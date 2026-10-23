import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { EMPTY_SHELL, ActionReply, PageReply } from './models';
import { StudioStore } from './studio-store';

describe('StudioStore.load', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
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

  it('puts a failed load on the page note instead of showing an empty page', async () => {
    const pending = store.load('history');
    http.expectOne('/api/page/history').flush('nope', {
      status: 500,
      statusText: 'Server Error',
    });
    await pending;
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toContain('500');
  });
});

describe('StudioStore.act', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
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
});
