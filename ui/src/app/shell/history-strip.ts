import { ChangeDetectionStrategy, Component, ElementRef, inject, input, signal } from '@angular/core';
import { StudioStore } from '../core/studio-store';

/**
 * The newest plates, as a contact sheet. Each plate is printed: a paper
 * margin, a mono index caption under it, and a rose loupe ring on the one the
 * arrow keys sit on. Opening a plate is the server's job, since the file is
 * on its disk.
 *
 * With no plates the strip collapses to one line. It is the last thing on the
 * page and the least useful when empty, so it does not take a band of the
 * window from the page above it.
 */
@Component({
  selector: 'app-history-strip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(keydown)': 'onKey($event)',
    tabindex: '0',
    role: 'region',
    'aria-label': 'Recent plates',
  },
  template: `
    @if (plates().length === 0) {
      <div class="empty-bar">
        <span class="eyebrow">Recent plates</span>
        <span class="blank-print" aria-hidden="true"></span>
        <p>No plates yet. The next finished render lands here.</p>
      </div>
    } @else {
      <div class="head">
        <span class="eyebrow">Recent plates</span>
        <span class="head-right">
          <span class="count">{{ plates().length }} {{ plates().length === 1 ? 'plate' : 'plates' }}</span>
          <button class="btn quiet sm" type="button" (click)="openCurrent()" title="Open the ringed plate (Enter)">Open</button>
        </span>
      </div>
      <div class="body">
        <button class="arrow" type="button" (click)="step(-1)" aria-label="Newer plates" [disabled]="ring() <= 0">‹</button>
        <div class="reel">
          @for (plate of plates(); track plate.name; let i = $index) {
            <button
              class="plate"
              type="button"
              [class.current]="i === ring()"
              (click)="ring.set(i)"
              (dblclick)="open(plate.name)"
              [attr.aria-label]="caption(plate.name) + ', ' + plate.name"
              [attr.title]="'Double-click to open ' + plate.name"
            >
              <span class="print small">
                <img [src]="plate.url" [alt]="" loading="lazy" />
              </span>
              <span class="cap"><b>{{ i + 1 }}</b> · {{ caption(plate.name) }}</span>
            </button>
          }
        </div>
        <button class="arrow" type="button" (click)="step(1)" aria-label="Older plates" [disabled]="ring() >= plates().length - 1">›</button>
      </div>
    }
  `,
  styles: `
    :host {
      display: block;
      grid-area: strip;
      padding: 6px 14px 10px;
      background: var(--bg);
      border-top: 1px solid var(--hairline);
      outline: none;
    }
    .empty-bar { display: flex; align-items: center; gap: 12px; min-height: 34px; }
    .empty-bar p { margin: 0; font-size: 12.5px; color: var(--fg-muted); }
    .blank-print { flex: none; width: 34px; height: 26px; border: 1px dashed var(--rule); border-radius: 1px; }
    .head { display: flex; align-items: baseline; justify-content: space-between; padding-bottom: 4px; }
    .head-right { display: inline-flex; align-items: center; gap: 10px; }
    .count { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--fg-muted); }
    .body { display: flex; align-items: stretch; height: 84px; }
    .arrow {
      flex: 0 0 30px;
      border: 0;
      background: none;
      color: var(--rule);
      font-size: 20px;
      cursor: pointer;
    }
    .arrow:hover:not(:disabled) { color: var(--fg); background: var(--wash); }
    .arrow:disabled { opacity: 0.35; cursor: default; }
    .reel { display: flex; align-items: center; gap: 10px; overflow-x: auto; flex: 1; scrollbar-width: thin; }
    .plate {
      flex: 0 0 auto;
      display: flex; flex-direction: column; align-items: center; gap: 4px;
      padding: 3px 4px 4px;
      border: 0; background: none; color: inherit; cursor: pointer;
    }
    .plate:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .plate .print { width: 56px; height: 48px; }
    .plate .print img { object-fit: cover; }
    .plate:hover .print { outline: 1px solid var(--rule); outline-offset: 2px; }
    .plate.current .print { outline: 2px solid var(--accent); outline-offset: 2px; }
    .cap {
      max-width: 64px;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: var(--font-mono);
      font-size: 10px;
      line-height: 1;
      letter-spacing: 0.02em;
      color: var(--fg-muted);
      white-space: nowrap;
    }
    .cap b { font-weight: 500; color: var(--fg); }
    .plate.current .cap, .plate.current .cap b { color: var(--accent); }
  `,
})
export class HistoryStrip {
  private readonly store = inject(StudioStore);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  readonly plates = input<readonly { name: string; url: string }[]>([]);
  protected readonly ring = signal(0);

  /** A short caption: a render's clock time, or the day a dated file names. */
  protected caption(name: string): string {
    const stem = name.replace(/\.[^.]+$/, '');
    const millis = stem.match(/(?:^|_)(\d{13})$/)?.[1];
    if (millis) {
      return new Date(Number(millis)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    const dated = stem.match(/(\d{4})-(\d{2})-(\d{2})-(.+)$/);
    if (dated) return `${dated[2]}-${dated[3]}`;
    return stem.replace(/^studio_/, '');
  }

  protected step(delta: number): void {
    const next = Math.min(Math.max(this.ring() + delta, 0), Math.max(0, this.plates().length - 1));
    this.ring.set(next);
    this.reveal();
  }

  /** Open the plate the ring is on, from the head's button or from Enter. */
  protected openCurrent(): void {
    const plate = this.plates()[this.ring()];
    if (plate) this.open(plate.name);
  }

  protected open(name: string): void {
    void this.store.act('shell', 'open_plate', { name });
  }

  protected onKey(event: KeyboardEvent): void {
    const root = event.currentTarget as HTMLElement;
    if (event.key === 'ArrowLeft') { event.preventDefault(); this.step(-1); this.focusRing(root); }
    else if (event.key === 'ArrowRight') { event.preventDefault(); this.step(1); this.focusRing(root); }
    else if (event.key === 'Home') { event.preventDefault(); this.ring.set(0); this.reveal(); this.focusRing(root); }
    else if (event.key === 'End') {
      event.preventDefault();
      this.ring.set(Math.max(0, this.plates().length - 1));
      this.reveal();
      this.focusRing(root);
    } else if (event.key === 'Enter') {
      const plate = this.plates()[this.ring()];
      if (plate) { event.preventDefault(); this.open(plate.name); }
    }
  }

  /** Arrow clicks move the ring and the reel together, so the ring is never off screen. */
  private reveal(): void {
    const plate = this.host.nativeElement.querySelectorAll<HTMLElement>('.plate')[this.ring()];
    plate?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  /** The ring and the keyboard focus move together, so Enter opens one plate. */
  private focusRing(root: HTMLElement): void {
    const plate = root.querySelectorAll<HTMLElement>('.plate')[this.ring()];
    plate?.focus();
    plate?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
}
