import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Type, provideAppInitializer } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { EMPTY_SHELL, PageReply } from '../core/models';
import { StudioStore } from '../core/studio-store';
import { AssistPage } from './assist/assist-page';
import { ImportPage } from './import/import-page';
import { TokensPage } from './tokens/tokens-page';

type Any = any;

/** Open one page against the real store, with its first reply in place. */
async function open<T>(component: Type<T>, id: string, state: unknown): Promise<{ page: Any; store: StudioStore; http: HttpTestingController }> {
  TestBed.configureTestingModule({
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(), provideAppInitializer(() => undefined)],
  });
  const store = TestBed.inject(StudioStore);
  const http = TestBed.inject(HttpTestingController);
  const fixture = TestBed.createComponent(component);
  globalThis.EventSource = { addEventListener() {}, close() {} } as unknown as typeof EventSource;
  store.pageId.set(id === 'tokens' ? 'config' : 'tokens');
  const pending = store.load(id);
  const reply: PageReply = { ok: true, page: id, state, shell: EMPTY_SHELL, busy: {} };
  http.expectOne(`/api/page/${id}`).flush(reply);
  await pending;
  fixture.detectChanges();
  // Change detection and its effects finish on a microtask, and a zoneless fixture does not wait on that.
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { page: fixture.componentInstance as Any, store, http };
}

function reply(page: string, ok: boolean, error = ''): Any {
  return { ok, id: '', page, action: 'save_key', pending: false, error, state: {}, shell: EMPTY_SHELL, busy: {}, effects: [] };
}

/**
 * A page hop as the store makes it: the page goes null, then the reply arrives.
 * The test replies in the same turn, so the hop's null and its reply are set together.
 */
async function hop(page: Any, http: HttpTestingController, id: string, state: unknown): Promise<void> {
  http.match('/api/action').forEach((request) => request.flush(reply(id, true)));
  page.store.page.set(null);
  const pending = page.store.load(id);
  http.expectOne(`/api/page/${id}`).flush({ ok: true, page: id, state, shell: EMPTY_SHELL, busy: {} });
  await pending;
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe('Tokens page', () => {
  it('hides a typed key again on Hide', async () => {
    const { page, store, http } = await open(TokensPage, 'tokens', {
      slots: [{ id: 'salad', label: 'Salad', present: true, hint: 'sk-…', state: 'unknown', tooltip: 'unconfirmed' }],
    });
    const show = store.act('tokens', 'reveal', { id: 'salad' });
    await Promise.resolve();
    await Promise.resolve();
    http.expectOne('/api/action').flush({
      ok: true, id: 'r1', page: 'tokens', action: 'reveal', pending: false, error: '', state: { slots: [] },
      shell: EMPTY_SHELL, busy: {}, effects: [{ kind: 'reveal', id: 'salad', value: 'sk-live-1' }],
    });
    await show;
    expect(page.revealOf('salad')).toBe('sk-live-1');
    page.edit('salad', { target: { value: 'sk-typed-2' } });
    page.toggle('salad');
    expect(store.revealed()).toBe(null);
    // The template reads the type from revealOf alone, so a draft stays masked.
    expect(page.revealOf('salad')).toBe('');
  });

  it('keeps every typed key in the box when the save fails', async () => {
    const { page, store, http } = await open(TokensPage, 'tokens', {
      slots: [
        { id: 'salad', label: 'Salad', present: true, hint: 'sk-…', state: 'unknown', tooltip: 'unconfirmed' },
        { id: 'civitai', label: 'Civitai', present: false, hint: '', state: 'unknown', tooltip: 'unconfirmed' },
      ],
    });
    page.edit('salad', { target: { value: 'sk-a' } });
    page.edit('civitai', { target: { value: 'sk-b' } });
    page.save();
    await new Promise((resolve) => setTimeout(resolve, 0));
    http.expectOne('/api/action').flush({
      ok: false, id: '', page: 'tokens', action: 'save_key', pending: false, error: 'Could not save the Salad key: denied',
      state: { slots: [] }, shell: EMPTY_SHELL, busy: {}, effects: [],
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(page.draft()).toEqual({ salad: 'sk-a', civitai: 'sk-b' });
    expect(store.dialog()?.body).toContain('Could not save the Salad key');
  });

  it('clears the key the server saved', async () => {
    const { page, http } = await open(TokensPage, 'tokens', {
      slots: [
        { id: 'salad', label: 'Salad', present: true, hint: 'sk-…', state: 'unknown', tooltip: 'unconfirmed' },
        { id: 'civitai', label: 'Civitai', present: false, hint: '', state: 'unknown', tooltip: 'unconfirmed' },
      ],
    });
    page.edit('salad', { target: { value: 'sk-a' } });
    page.edit('civitai', { target: { value: 'sk-b' } });
    page.save();
    await new Promise((resolve) => setTimeout(resolve, 0));
    http.expectOne('/api/action').flush({ ...reply('tokens', true), effects: [] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(page.draft()).toEqual({});
  });
});

describe('Import page', () => {
  it('seeds the boxes from the first reply after a hop, and keeps a newer keystroke', async () => {
    const { page, http } = await open(ImportPage, 'import', { url: 'https://civitai.com/images/1', meta: 'a prompt', workflow: '' });
    expect(page.boxes().url).toBe('https://civitai.com/images/1');
    page.type('url', 'https://civitai.com/images/2');
    await hop(page, http, 'import', { url: 'https://civitai.com/images/2', meta: 'a prompt', workflow: '', knobs: [] });
    expect(page.boxes().url).toBe('https://civitai.com/images/2');
    expect(page.boxes().meta).toBe('a prompt');
  });
});

describe('Assist page', () => {
  it('ticks a typed box through a reply that still carries the old text, as a keystroke does', async () => {
    const { page, http } = await open(AssistPage, 'assist', { issue: 'blurry', positive: 'a cat' });
    // Typing puts the new text in the native box and then reads it, so the signal holds it before the reply merges.
    page.edit({ positive: 'a dog' });
    await hop(page, http, 'assist', { issue: 'blurry', positive: 'a cat' });
    expect(page.edited().positive).toBe('a dog');
  });
  it('seeds an untouched box after a hop and keeps a typed one', async () => {
    const { page, http } = await open(AssistPage, 'assist', { issue: 'blurry', positive: 'a cat' });
    page.edit({ positive: 'a dog' });
    await hop(page, http, 'assist', { issue: 'still blurry', positive: 'a fox' });
    // The typed prompt survives the opening's first reply; the untouched issue shows the server's.
    expect(page.edited().positive).toBe('a dog');
    expect(page.edited().issue).toBe('still blurry');
  });
});
