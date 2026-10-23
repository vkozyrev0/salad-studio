import { Injectable, signal } from '@angular/core';

/**
 * The row a grid page acts on, held by key rather than by index.
 *
 * The server re-sends the whole list after every action and on every queue
 * tick, so an index would drift the moment a row lands above the selection.
 * The key is the server's own identifier for the row.
 */
@Injectable()
export class Selection {
  readonly key = signal<string | null>(null);

  pick(key: string | null): void {
    this.key.set(key);
  }
}
