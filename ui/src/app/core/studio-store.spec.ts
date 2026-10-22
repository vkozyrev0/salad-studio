import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { EMPTY_SHELL, PageReply } from './models';
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
