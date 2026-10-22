import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { StudioStore } from '../core/studio-store';
import { PAGES, pageIdFromUrl } from '../core/models';

/**
 * Every page's heading: a mono address, a hairline, the serif title and its
 * subtitle, then the note line that says what last happened here. The serif
 * is used twice in the whole app, here and in the rail, so it stays a sign
 * rather than a voice.
 */
@Component({
  selector: 'app-page-frame',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="frame">
      <header class="plate">
        <span class="address">{{ info().number }}</span>
        <div class="titles">
          <h1>{{ info().title }}</h1>
          <p>{{ info().subtitle }}</p>
        </div>
        @if (busy()) {
          <span class="working" role="status"><span class="tick" aria-hidden="true"></span>Working</span>
        }
      </header>
      <p class="note" [class.ok]="note().level === 'ok'" [class.warn]="note().level === 'warn'" [class.error]="note().level === 'error'">
        <span class="stamp">{{ stamp() }}</span>
        @if (note().text) { {{ note().text }} } @else { Ready. }
      </p>
      <div class="body"><ng-content /></div>
    </section>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .frame { display: grid; grid-template-rows: auto auto minmax(0, 1fr); height: 100%; min-height: 0; }
    .plate {
      display: flex;
      align-items: baseline;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--hairline);
    }
    .address {
      font-family: var(--font-mono);
      font-size: 9.5px;
      letter-spacing: 0.1em;
      color: var(--accent-fg);
      background: var(--accent);
      padding: 2px 5px;
      border-radius: 2px;
      transform: translateY(-6px);
    }
    h1 {
      margin: 0;
      font-family: var(--font-display);
      font-size: 31px;
      line-height: 1.05;
      font-weight: 400;
      letter-spacing: -0.015em;
      color: var(--fg);
    }
    .titles p { margin: 2px 0 0; font-size: 12.5px; color: var(--fg-muted); }
    .working {
      margin-left: auto;
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--font-mono);
      font-size: 9px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent);
    }
    .tick { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: breathe 1.1s ease-in-out infinite; }
    @keyframes breathe { 50% { opacity: 0.3; } }
    .note {
      display: flex; align-items: baseline; gap: 10px;
      margin: 0;
      padding: 8px 0;
      font-size: 12.5px;
      color: var(--fg-muted);
      min-height: 34px;
    }
    .stamp { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.04em; color: var(--rule); white-space: nowrap; }
    .note::before { content: ''; width: 4px; height: 4px; border-radius: 50%; background: var(--fg-muted); align-self: center; flex: none; }
    .note.ok { color: var(--valid); } .note.ok::before { background: var(--valid); }
    .note.warn { color: var(--warn); } .note.warn::before { background: var(--warn); }
    .note.error { color: var(--invalid); } .note.error::before { background: var(--invalid); }
    .body { min-height: 0; padding-top: 4px; overflow: hidden; }
  `,
})
export class PageFrame {
  private readonly store = inject(StudioStore);
  private readonly router = inject(Router);


  /** The open page, read from the router so a shortcut and a rail click agree. */
  protected readonly info = computed(() => {
    this.store.routeRev();
    const id = pageIdFromUrl(this.router.url);
    const found = PAGES.find((p) => p.id === id) ?? PAGES[0];
    return found;
  });
  protected readonly note = computed(() => this.store.shell().note);
  protected readonly busy = computed(() => this.store.isBusy());
  /** The note's time, read once per note so the line reads like a ledger entry. */
  protected readonly stamp = computed(() => {
    const line = this.note().text;
    return line ? new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
  });
}
