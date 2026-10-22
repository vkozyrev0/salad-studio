import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { beforeEach, describe, expect, it } from 'vitest';
import { ActionReply, EMPTY_SHELL } from './models';
import { StudioStore } from './studio-store';

/** The one EventSource the store opens, with its listeners kept for the test. */
class FakeEventSource {
  static last: FakeEventSource | null = null;
  private readonly listeners = new Map<string, (event: MessageEvent) => void>();

  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }

  addEventListener(name: string, handler: (event: MessageEvent) => void): void {
    this.listeners.set(name, handler);
  }

  close(): void {}

  emit(name: string, data: unknown): void {
    const handler = this.listeners.get(name);
    handler?.(new MessageEvent(name, { data: JSON.stringify(data) }));
  }
}

describe('StudioStore events', () => {
  let store: StudioStore;
  let http: HttpTestingController;

  beforeEach(() => {
    Object.defineProperty(globalThis, 'EventSource', {
      value: FakeEventSource,
      configurable: true,
    });
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(StudioStore);
    http = TestBed.inject(HttpTestingController);
    store.connect();
  });

  it('clears the in-flight key the action_done reply names', async () => {
    const pending: ActionReply = {
      ok: true,
      id: 'r1',
      page: 'settings',
      action: 'set_knobs',
      pending: true,
      error: '',
      state: {},
      shell: EMPTY_SHELL,
      busy: {},
      effects: [],
    };
    const running = store.act('settings', 'set_knobs', { steps: '8' });
    // act() chains on a microtask before it posts.
    await Promise.resolve();
    await Promise.resolve();
    http.expectOne('/api/action').flush(pending);
    await running;
    expect(store.inFlight().has('settings.set_knobs')).toBe(true);

    const done: ActionReply = { ...pending, pending: false, id: 'r1' };
    FakeEventSource.last?.emit('action_done', { reply: done });
    expect(store.inFlight().has('settings.set_knobs')).toBe(false);
  });
});
