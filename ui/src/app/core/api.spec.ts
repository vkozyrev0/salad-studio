import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Api, TOKEN, runToken, tokenInterceptor } from './api';

describe('the run token', () => {
  let backend: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([tokenInterceptor])), provideHttpClientTesting()],
    });
    backend = TestBed.inject(HttpTestingController);
  });

  afterEach(() => backend.verify());

  it('rides in the URL the server prints', () => {
    expect(runToken).toBe(new URLSearchParams(location.search).get('token') ?? '');
  });

  it('is set by the interceptor on every request, page read or picture alike', async () => {
    const api = TestBed.inject(Api);
    const picture = api.image('/api/thumbs/a.jpg');
    const plate = backend.expectOne('/api/thumbs/a.jpg');
    expect(plate.request.headers.get(TOKEN)).toBe(runToken);
    expect(plate.request.responseType).toBe('blob');
    plate.flush(new Blob(['x'], { type: 'image/jpeg' }));
    expect(await picture).toMatch(/^blob:/);

    void api.page('config');
    const read = backend.expectOne('/api/page/config');
    expect(read.request.headers.get(TOKEN)).toBe(runToken);
    read.flush({});
  });
});
