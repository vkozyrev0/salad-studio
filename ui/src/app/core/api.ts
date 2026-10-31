import { HttpClient, HttpErrorResponse, HttpEvent, HttpHandlerFn, HttpRequest } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';
import { ActionReply, PageReply } from './models';

/** The header the server reads its run token from. */
export const TOKEN = 'X-Studio-Token';
export const NO_TOKEN =
  'This page was opened without its run token, so the studio cannot answer it. ' +
  'Open the URL the server printed in its terminal, token and all.';

/** The run token the server put in this page's address; empty when the address has none. */
export const runToken: string = new URLSearchParams(location.search).get('token') ?? '';

/**
 * Every request the app makes carries the run token.
 *
 * This is the one place the token is attached. The event stream is not one of
 * these requests: it is an `EventSource`, which cannot set a header, so it
 * carries the token in its URL.
 */
export function tokenInterceptor(request: HttpRequest<unknown>, next: HttpHandlerFn): Observable<HttpEvent<unknown>> {
  return next(request.clone({ setHeaders: { [TOKEN]: runToken } }));
}

/** A refused request with this kind is the server saying the page never carried its token. */
export function unauthorized(err: unknown): boolean {
  if (!(err instanceof HttpErrorResponse) || err.status !== 403) return false;
  const body = err.error as { error?: { kind?: string } } | null;
  return body?.error?.kind === 'unauthorized';
}

/** The three calls the server answers. Nothing else in the app speaks HTTP. */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  page(id: string): Promise<PageReply> {
    return firstValueFrom(this.http.get<PageReply>(`/api/page/${encodeURIComponent(id)}`));
  }

  act(page: string, action: string, args: object = {}): Promise<ActionReply> {
    return firstValueFrom(this.http.post<ActionReply>('/api/action', { page, action, args }));
  }

  confirm(token: string): Promise<ActionReply> {
    return firstValueFrom(this.http.post<ActionReply>('/api/action', { confirm: token }));
  }

  /** `EventSource` cannot set a header, so the stream takes the token in its URL. */
  events(): EventSource {
    return new EventSource(`/api/events?token=${encodeURIComponent(runToken)}`);
  }

  /**
   * The bytes of a plate or a picture.
   *
   * The history strip draws a plate as an `img`, which cannot send the header,
   * and the server will not take a token in the query. So the picture is
   * fetched here like any other request and drawn from a blob URL.
   */
  image(url: string): Promise<string> {
    return firstValueFrom(this.http.get(url, { responseType: 'blob' })).then((blob) => URL.createObjectURL(blob));
  }
}
