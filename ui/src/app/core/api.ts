import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ActionReply, PageReply } from './models';

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

  /** One file from the server, as a URL the page can put in src or href. */
  file(path: string): string {
    return path;
  }

  events(): EventSource {
    return new EventSource('/api/events');
  }
}
