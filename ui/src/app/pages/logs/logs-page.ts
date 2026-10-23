import { ChangeDetectionStrategy, Component, computed, effect, inject, viewChild, ElementRef } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';

interface LogsState {
  salad?: { version?: number; text?: string; empty_text?: string };
  salad_state?: string;
}

/**
 * Logs: the container's own log beside the Studio and HTTP lines.
 *
 * Studio lines arrive on the event stream and live in the store, so they are
 * current without a refresh. The container's log is a fetched block with a
 * version, and a new version scrolls to its end.
 */
@Component({
  selector: 'app-logs-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame],
  template: `
    <app-page-frame>
      <div class="panes">
        <section class="pane" aria-labelledby="salad-logs-head">
          <h2 class="eyebrow" id="salad-logs-head">Salad container logs (active gateway)</h2>
          <div class="log-view" #saladView tabindex="0" role="log" aria-labelledby="salad-logs-head" aria-live="off">
            @for (line of saladLines(); track $index) {
              <span class="log-line">{{ line }}</span>
            } @empty {
              <span class="empty">{{ salad().empty_text || '(nothing fetched yet)' }}</span>
            }
          </div>
        </section>

        <div class="bar">
          <button class="btn ghost" type="button" [disabled]="busy('refresh_salad_logs')" (click)="act('refresh_salad_logs')">
            @if (busy('refresh_salad_logs')) { <span class="spinner" aria-hidden="true"></span> }
            Refresh Salad logs
          </button>
          <button class="btn ghost" type="button" [disabled]="busy('check_salad')" (click)="act('check_salad')">
            @if (busy('check_salad')) { <span class="spinner" aria-hidden="true"></span> }
            Check Salad status
          </button>
          <p class="status" role="status">{{ state()?.salad_state }}</p>
        </div>

        <section class="pane" aria-labelledby="studio-logs-head">
          <div class="pane-head">
            <h2 class="eyebrow" id="studio-logs-head">Studio / HTTP</h2>
            <button class="btn quiet sm" type="button" [disabled]="busy('clear')" (click)="act('clear')">Clear logs</button>
          </div>
          <div class="log-view" #studio tabindex="0" role="log" aria-labelledby="studio-logs-head" aria-live="polite">
            @for (line of lines(); track $index) {
              <span class="log-line" [class]="line.level">
                <span class="lvl">{{ levelWord(line.level) }}</span>{{ line.text }}
              </span>
            } @empty {
              <span class="empty">No Studio lines yet.</span>
            }
          </div>
        </section>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .panes { display: grid; grid-template-rows: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; height: 100%; min-height: 0; padding-top: 12px; }
    .pane { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; }
    .pane:last-child { grid-template-rows: auto minmax(0, 1fr); }
    .pane h2 { margin: 0 0 6px; }
    .pane-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
    .pane-head h2 { margin: 0; }
    .empty { color: var(--fg-muted); }
    .bar { display: flex; align-items: center; gap: 9px; }
    .status { margin: 0 0 0 auto; font-size: 12px; color: var(--fg-muted); }
  `,
})
export class LogsPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as LogsState | null);
  protected readonly salad = computed(() => this.state()?.salad ?? {});
  protected readonly saladLines = computed(() => (this.salad().text ?? '').split(/\r?\n/).filter((l) => l.length));
  protected readonly lines = computed(() => this.store.logLines());

  private readonly saladView = viewChild<ElementRef<HTMLDivElement>>('saladView');
  private readonly studioView = viewChild<ElementRef<HTMLDivElement>>('studio');
  private saladVersion: number | undefined;

  constructor() {
    effect(() => {
      const version = this.salad().version;
      const view = this.saladView()?.nativeElement;
      if (!view) return;
      if (version !== this.saladVersion) {
        this.saladVersion = version;
        queueMicrotask(() => (view.scrollTop = view.scrollHeight));
      }
    });
    effect(() => {
      this.lines();
      const view = this.studioView()?.nativeElement;
      if (view) queueMicrotask(() => (view.scrollTop = view.scrollHeight));
    });
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`logs.${action}`);
  }

  /** The level in a word, so colour is never the only signal. */
  protected levelWord(level: string): string {
    return (level || 'info').toUpperCase().padEnd(5, ' ');
  }

  protected act(action: 'refresh_salad_logs' | 'check_salad' | 'clear'): void {
    void this.store.act('logs', action);
  }
}
