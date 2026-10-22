import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { StudioStore } from '../core/studio-store';

/**
 * The newest plates, as a contact sheet. Each plate is printed: a paper
 * margin, a mono index caption under it, and a rose loupe ring on the one the
 * arrow keys sit on. Opening a plate is the server's job, since the file is
 * on its disk.
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
    <div class="head">
      <span class="eyebrow">Recent plates</span>
      <span class="count">{{ plates().length }} {{ plates().length === 1 ? 'plate' : 'plates' }}</span>
    </div>
    <div class="body">
      <button class="arrow" type="button" (click)="step(-1)" aria-label="Newer plates" [disabled]="ring() <= 0">‹</button>
      <div class="reel">
        @if (plates().length === 0) {
          <div class="empty">
            <span class="blank-print" aria-hidden="true"></span>
            <p>No plates yet. A finished render appears here.</p>
          </div>
        }
        @for (plate of plates(); track plate.name; let i = $index) {
          <button
            class="plate"
            type="button"
            [class.current]="i === ring()"
            (click)="ring.set(i)"
            (dblclick)="open(plate.name)"
            (keydown.enter)="open(plate.name)"
            (keydown.space)="open(plate.name)"
            [attr.aria-label]="caption(plate.name) + ', ' + plate.name"
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
    .head { display: flex; align-items: baseline; justify-content: space-between; padding-bottom: 4px; }
    .count { font-family: var(--font-mono); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--fg-muted); }
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
    .plate .print { width: 56px; height: 48px; }
    .plate .print img { object-fit: cover; }
    .plate:hover .print { outline: 1px solid var(--rule); outline-offset: 2px; }
    .plate.current .print { outline: 2px solid var(--accent); outline-offset: 2px; }
    .cap {
      font-family: var(--font-mono);
      font-size: 8.5px;
      line-height: 1;
      letter-spacing: 0.02em;
      color: var(--fg-muted);
      white-space: nowrap;
    }
    .cap b { font-weight: 500; color: var(--fg); }
    .plate.current .cap, .plate.current .cap b { color: var(--accent); }
    .empty { display: flex; align-items: center; gap: 16px; padding: 0 12px; }
    .empty p { margin: 0; font-size: 12.5px; color: var(--fg-muted); }
    .blank-print {
      width: 56px; height: 48px;
      border: 1px dashed var(--rule);
      border-radius: 1px;
    }
  `,
})
export class HistoryStrip {
  private readonly store = inject(StudioStore);
  readonly plates = input<readonly { name: string; url: string }[]>([]);
  protected readonly ring = signal(0);

  /** The index part of a plate's file name, or the name without its extension. */
  protected caption(name: string): string {
    return name.replace(/\.[^.]+$/, '');
  }

  protected step(delta: number): void {
    const next = Math.min(Math.max(this.ring() + delta, 0), Math.max(0, this.plates().length - 1));
    this.ring.set(next);
  }

  protected open(name: string): void {
    void this.store.act('shell', 'open_plate', { name });
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'ArrowLeft') { event.preventDefault(); this.step(-1); }
    else if (event.key === 'ArrowRight') { event.preventDefault(); this.step(1); }
    else if (event.key === 'Home') { event.preventDefault(); this.ring.set(0); }
    else if (event.key === 'End') { event.preventDefault(); this.ring.set(Math.max(0, this.plates().length - 1)); }
    else if (event.key === 'Enter') {
      const plate = this.plates()[this.ring()];
      if (plate) { event.preventDefault(); this.open(plate.name); }
    }
  }
}
