import { Injectable, computed, signal } from '@angular/core';

/**
 * The row a grid page acts on, held by key rather than by index.
 *
 * The server re-sends the whole list after every action and on every queue
 * tick, so an index would drift the moment a row lands above the selection.
 * The key is the server's own identifier for the row, and the order is the
 * grid's displayed order, which is what "next" and "previous" mean to the
 * person pressing an arrow key.
 */
@Injectable()
export class Selection {
  /** Called with a visible key after a step; the page maps it. */
  readonly key = signal<string | null>(null);
  private order: string[] = [];
  private readonly moved = signal(0);

  /** The movement is a signal so a page can act on Enter after the arrows moved. */
  readonly step = computed(() => this.moved());

  shown(order: string[]): void {
    this.order = order;
  }

  pick(key: string | null): void {
    this.key.set(key);
  }

  move(where: 'first' | 'last' | 'next' | 'prev'): void {
    if (!this.order.length) return;
    const at = this.key() === null ? -1 : this.order.indexOf(this.key() as string);
    const index =
      where === 'first' ? 0
      : where === 'last' ? this.order.length - 1
      : at === -1 ? 0
      : Math.min(this.order.length - 1, Math.max(0, at + (where === 'next' ? 1 : -1)));
    this.key.set(this.order[index]);
    this.moved.update((n) => n + 1);
  }
}
