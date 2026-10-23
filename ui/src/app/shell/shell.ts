import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { StudioStore } from '../core/studio-store';
import { PAGES } from '../core/models';
import { HistoryStrip } from './history-strip';
import { DialogHost } from './dialog-host';

/**
 * The window: action bar, numbered rail, the open page, the status line, the
 * strip. The rail's numbers are the page's address, which is why they stay:
 * Ctrl+2 opens the second page, and the number is what the eye follows.
 */
@Component({
  selector: 'app-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, HistoryStrip, DialogHost],
  host: { '(document:keydown)': 'onKey($event)' },
  template: `
    <a class="skip" href="#page" (click)="skipToPage($event)">Skip to page</a>
    <div class="window" [attr.inert]="store.dialog() || store.confirm() ? '' : null">
      <header class="bar">
        <button class="btn primary" type="button" (click)="generate()" [disabled]="shell().gen.busy">
          @if (shell().gen.busy) { <span class="spinner" aria-hidden="true"></span> }
          {{ shell().gen.busy ? 'Rendering' : 'Generate' }}
        </button>
        <button class="btn ghost" type="button" (click)="cleanGallery()">Clean gallery</button>
        <span class="state" role="status" aria-live="polite">
          <span class="pulse" [class.live]="shell().gen.busy" aria-hidden="true"></span>
          {{ shell().gen.word }}
        </span>

        <div class="meters" [attr.aria-label]="'Replicas: ' + counts()[0] + ' ready, ' + counts()[1] + ' starting, ' + counts()[2] + ' not started'">
          <span class="meter ready"><span class="eyebrow">Ready</span><span class="bar" [style.--fill]="scale(counts()[0])"></span><b>{{ counts()[0] }}</b></span>
          <span class="meter starting"><span class="eyebrow">Starting</span><span class="bar" [style.--fill]="scale(counts()[1])"></span><b>{{ counts()[1] }}</b></span>
          <span class="meter idle"><span class="eyebrow">Not started</span><span class="bar" [style.--fill]="scale(counts()[2])"></span><b>{{ counts()[2] }}</b></span>
        </div>
        <button class="btn ghost" type="button" (click)="checkSalad()" [disabled]="store.isBusy()">
          Check Salad status
        </button>
      </header>

      <nav class="rail" aria-label="Pages">
        <div class="rail-head">
          <span class="wordmark">Salad Studio</span>
          <span class="eyebrow">Image bench · local</span>
        </div>
        <span class="eyebrow rail-eyebrow">Pages</span>
        <ul class="rail-list">
          @for (page of pages; track page.id) {
            <li>
              <a class="rail-link" [routerLink]="['/' + page.id]" routerLinkActive="active"
                 ariaCurrentWhenActive="page">
                <span class="rail-num">{{ page.number }}</span>
                <span class="rail-name">{{ page.title }}</span>
              </a>
            </li>
          }
        </ul>
        <div class="rail-foot">
          <span>{{ pages.length }} pages</span>
          <span>Ctrl+1–9 jumps</span>
        </div>
      </nav>

      <main class="pane" id="page" tabindex="-1">
        <router-outlet />
      </main>

      <footer class="status" [class.warn]="shell().status.level === 'warn'" [class.error]="shell().status.level === 'error'">
        <span class="dot" aria-hidden="true"></span>
        <span class="status-text" [attr.title]="shell().status.text">{{ shell().status.text }}</span>
        <span class="keys">
          <span class="kbd">Ctrl+Tab</span><span>pages</span>
          <span class="kbd">← →</span><span>plates</span>
        </span>
      </footer>

      <app-history-strip [plates]="shell().plates" />
    </div>
    <app-dialog-host />
  `,
  styles: `
    :host { display: block; height: 100vh; }
    .skip {
      position: absolute;
      left: -9999px;
      top: 0;
      z-index: 20;
      padding: 8px 12px;
      background: var(--surface);
      color: var(--fg);
      border: 1px solid var(--accent);
      border-radius: var(--radius-control);
    }
    .skip:focus { left: 12px; top: 12px; }
    .window {
      display: grid;
      height: 100%;
      grid-template-columns: 232px minmax(0, 1fr);
      grid-template-rows: 58px minmax(0, 1fr) auto auto;
      grid-template-areas:
        'bar bar'
        'rail pane'
        'rail status'
        'strip strip';
      background: var(--bg);
    }

    .bar {
      grid-area: bar;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 20px;
      background: var(--surface);
      border-bottom: 1px solid var(--rule);
    }
    .state { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--fg-muted); padding-left: 6px; }
    .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--rule); }
    .pulse.live { background: var(--accent); box-shadow: 0 0 0 3px rgb(227 154 169 / 0.16); }
    .spinner {
      width: 11px; height: 11px; border-radius: 50%;
      border: 2px solid currentColor; border-right-color: transparent;
      animation: spin 700ms linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    .meters { margin-left: auto; display: flex; align-items: center; gap: 20px; }
    .meter { display: inline-flex; align-items: center; gap: 7px; }
    .meter .eyebrow { font-size: 10px; letter-spacing: 0.11em; color: var(--fg-muted); }
    .meter b { font-family: var(--font-mono); font-size: 12px; font-weight: 500; font-variant-numeric: tabular-nums; }
    .meter .bar {
      position: relative;
      width: 22px; height: 3px;
      background: var(--hairline);
      border-radius: 1px;
      overflow: hidden;
    }
    .meter .bar::after {
      content: '';
      position: absolute; inset: 0 auto 0 0;
      width: calc(var(--fill, 0) * 100%);
      background: currentColor;
    }
    .meter.ready { color: var(--valid); }
    .meter.starting { color: var(--warn); }
    .meter.idle { color: var(--invalid); }
    .meter b { color: var(--fg); }

    .rail {
      grid-area: rail;
      display: flex;
      flex-direction: column;
      min-height: 0;
      padding: 16px 10px 10px;
      background: var(--surface);
      border-right: 1px solid var(--rule);
    }
    .rail-head { display: grid; gap: 2px; padding: 0 10px 16px; }
    .wordmark { font-family: var(--font-display); font-size: 20px; letter-spacing: -0.01em; color: var(--fg); }
    .rail-eyebrow { padding: 0 10px 8px; font-size: 10px; letter-spacing: 0.16em; }
    .rail-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
    .rail-link {
      display: flex;
      align-items: baseline;
      gap: 10px;
      padding: 6px 10px;
      border-left: 2px solid transparent;
      color: var(--fg-muted);
      text-decoration: none;
      transition: background 100ms ease, color 100ms ease;
    }
    .rail-link:hover { background: var(--wash); color: var(--fg); }
    .rail-num { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.04em; min-width: 2ch; }
    .rail-name { font-size: 13px; line-height: 1.2; }
    .rail-link.active { background: var(--rose-wash); color: var(--fg); border-left-color: var(--accent); }
    .rail-link.active .rail-num { color: var(--accent); }
    .rail-foot {
      margin-top: auto;
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 12px 10px 0;
      border-top: 1px solid var(--hairline);
      font-family: var(--font-mono);
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--fg-muted);
    }

    .pane {
      grid-area: pane;
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      padding: 20px 24px 16px;
      background: var(--ground);
    }
    .pane:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }

    .status {
      grid-area: status;
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 32px;
      padding: 5px 20px;
      background: var(--status);
      border-top: 1px solid var(--rule);
      font-size: 12px;
      color: var(--fg-muted);
    }
    .status .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--valid); flex: none; }
    .status.warn .dot { background: var(--warn); }
    .status.error .dot { background: var(--invalid); }
    .status.warn .status-text { color: var(--warn); }
    .status.error .status-text { color: var(--invalid); }
    .status-text { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .status .keys {
      margin-left: auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 10px;
      color: var(--fg-muted);
      white-space: nowrap;
    }
    .status .keys .kbd { font-size: 10px; }

    @media (max-width: 860px) {
      .window {
        grid-template-columns: 1fr;
        grid-template-rows: auto auto minmax(0, 1fr) auto auto;
        grid-template-areas: 'bar' 'rail' 'pane' 'status' 'strip';
      }
      .bar { flex-wrap: wrap; height: auto; padding: 8px 16px; }
      .meters { width: auto; margin-left: auto; }
      .rail { flex-direction: row; flex-wrap: wrap; align-items: center; overflow-x: auto; padding: 6px 10px; border-right: 0; border-bottom: 1px solid var(--rule); }
      .rail-head, .rail-eyebrow, .rail-foot { display: none; }
      .rail-list { flex-direction: row; flex-wrap: wrap; }
      .rail-link { border-left: 0; border-bottom: 2px solid transparent; white-space: nowrap; }
      .rail-link.active { border-bottom-color: var(--accent); }
      .pane { padding: 14px 16px; }
      /* The strip's keyboard hint is the first thing to go when the status
         line needs its width for the sentence itself. */
      .status .keys { display: none; }
    }
  `,
})
export class Shell {
  protected readonly store = inject(StudioStore);
  private readonly router = inject(Router);
  protected readonly pages = PAGES;
  protected readonly shell = this.store.shell;
  protected readonly counts = () => this.shell().counts;

  /** The page the URL names, which is why the rail and the shortcuts agree. */
  /** The meter's bar, capped so one replica fills it and ten do not overflow. */
  protected scale(value: number): number {
    return Math.min(1, value / 4);
  }

  /** The skip link moves focus, not the route: `#page` is not a route under hash routing. */
  protected skipToPage(event: Event): void {
    event.preventDefault();
    const main = document.getElementById('page');
    main?.focus();
    main?.scrollIntoView({ block: 'start' });
  }

  protected generate(): void {
    void this.store.act('shell', 'generate');
  }

  protected cleanGallery(): void {
    void this.store.act('shell', 'clean_gallery');
  }

  protected checkSalad(): void {
    void this.store.act('shell', 'check_salad');
  }

  protected onKey(event: KeyboardEvent): void {
    if (!event.ctrlKey) return;
    const index = Math.max(0, this.pages.findIndex((p) => p.id === this.store.pageId()));
    // Ctrl+Tab is a page shortcut everywhere, including inside a field; the
    // digits stay with the page body so a form keeps its own number keys.
    if (event.key === 'Tab' || event.key === 'PageDown') {
      event.preventDefault();
      const delta = event.shiftKey ? -1 : 1;
      void this.router.navigateByUrl('/' + this.pages[(index + delta + this.pages.length) % this.pages.length].id);
      return;
    }
    if (event.key === 'PageUp') {
      event.preventDefault();
      void this.router.navigateByUrl('/' + this.pages[(index - 1 + this.pages.length) % this.pages.length].id);
      return;
    }
    const target = event.target as HTMLElement | null;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
    if (/^[0-9]$/.test(event.key)) {
      event.preventDefault();
      // Digits follow the rail: 1-9 are the first nine pages, 0 is the tenth.
      const wanted = event.key === '0' ? 10 : Number(event.key);
      if (wanted <= this.pages.length) void this.router.navigateByUrl('/' + this.pages[wanted - 1].id);
    }
  }
}
