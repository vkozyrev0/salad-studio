import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ActionReply, PageReply } from './models';

/** The header and query name the server reads its run token from. */
export const TOKEN = 'X-Studio-Token';
export const NO_TOKEN =
  'This page was opened without its run token, so the studio cannot answer it. ' +
  'Open the URL the server printed in its terminal, token and all.';

/** The run token the server put in this page's address; empty when the address has none. */
export const runToken: string = new URLSearchParams(location.search).get('token') ?? '';

/** A URL for an `img` or a link, which cannot send the token header. */
export function withToken(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(runToken)}`;
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
  private readonly headers = new HttpHeaders({ [TOKEN]: runToken });

  page(id: string): Promise<PageReply> {
    return firstValueFrom(this.http.get<PageReply>(`/api/page/${encodeURIComponent(id)}`, { headers: this.headers }));
  }

  act(page: string, action: string, args: object = {}): Promise<ActionReply> {
    return firstValueFrom(this.http.post<ActionReply>('/api/action', { page, action, args }, { headers: this.headers }));
  }

  confirm(token: string): Promise<ActionReply> {
    return firstValueFrom(this.http.post<ActionReply>('/api/action', { confirm: token }, { headers: this.headers }));
  }

  /** `EventSource` cannot set a header, so the stream takes the token in its URL. */
  events(): EventSource {
    return new EventSource(`/api/events?token=${encodeURIComponent(runToken)}`);
  }
}
