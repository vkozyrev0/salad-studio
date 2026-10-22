import { DestroyRef, Injectable, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { StudioStore } from './studio-store';

/**
 * The URL is the page selection, and this keeps the store's idea of the open
 * page in step with it.
 *
 * Only a completed navigation counts. The earlier router events carry a URL
 * that has not committed, and acting on one renders in the middle of the
 * router's own update. The single tick below is ordinary change detection: it
 * never re-entered the outlet mid-update, and what looked like that failure
 * was the shared placeholder page keeping the route it was first built for.
 */
@Injectable({ providedIn: 'root' })
export class RouteSync {
  private readonly router = inject(Router);
  private readonly store = inject(StudioStore);
  private readonly destroyRef = inject(DestroyRef);

  start(): void {
    this.router.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
      if (!(event instanceof NavigationEnd)) return;
      this.open(pageId(event.urlAfterRedirects));
    });
    this.open(pageId(this.router.url));
  }

  /** Fetch the page the URL names. The server also records it as the open page. */
  private open(id: string): void {
    this.store.pageId.set(id);
    this.store.touch();
    void this.store.load(id);
  }
}

function pageId(url: string): string {
  const path = url.split('?')[0].split('#').pop() ?? '';
  return path.replace(/^\//, '') || 'config';
}
