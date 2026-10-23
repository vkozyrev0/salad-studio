import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ColDef } from 'ag-grid-community';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { DataGrid, numeric } from '../../shared/data-grid';

interface JobRow {
  key: string;
  id?: string;
  profile?: string;
  state?: string;
  attempts?: string;
  status?: string;
  reason?: string;
  request?: string;
  finished?: string;
  cancellable?: boolean;
  retryable?: boolean;
}

interface QueueState {
  rows?: JobRow[];
  empty_text?: string;
  summary?: {
    requests?: number;
    pending?: number;
    lines?: Record<string, number>;
    states?: { word: string; count: number }[];
  };
  selected?: string | null;
  can_cancel?: boolean;
  can_retry?: boolean;
  note?: string;
}

const STANDING_NOTE =
  'Cancel drops a request that has not been submitted yet. A request the container has already accepted keeps rendering.';

/**
 * Queue: one row per request, read back from the queue on every tick.
 *
 * The row the person picked is the page's, held by key so a finish landing
 * above it does not move the selection. Cancel and Retry act on that key and
 * say why they are off from the server's row, instead of failing after a
 * click.
 */
@Component({
  selector: 'app-queue-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, DataGrid],
  template: `
    <app-page-frame>
      <div class="wrap">
        <div class="head">
          <div class="btn-row" role="group" aria-label="Queue actions">
            <button
              class="btn ghost"
              type="button"
              [disabled]="busy('cancel') || !state()?.can_cancel"
              [attr.title]="refusal('cancel')"
              (click)="act('cancel')"
            >
              @if (busy('cancel')) { <span class="spinner" aria-hidden="true"></span> }
              Cancel selected
            </button>
            <button
              class="btn ghost"
              type="button"
              [disabled]="busy('retry') || !state()?.can_retry"
              [attr.title]="refusal('retry')"
              (click)="act('retry')"
            >
              @if (busy('retry')) { <span class="spinner" aria-hidden="true"></span> }
              Retry selected
            </button>
            <button class="btn ghost" type="button" [disabled]="busy('clear_finished')" (click)="act('clear_finished')">
              @if (busy('clear_finished')) { <span class="spinner" aria-hidden="true"></span> }
              Clear finished
            </button>
          </div>
          <p class="summary" id="queue-summary">{{ summary() }}</p>
        </div>

        <div class="table">
          @if (rows().length || store.loading() || store.loadError()) {
            <app-data-grid
              [rows]="rows()"
              [columns]="columns"
              field="key"
              [selected]="selected()"
              (picked)="pick($event)"
            />
          } @else {
            <div class="empty-sheet">
              <p class="empty-title">Nothing queued</p>
              <p class="empty-hint">{{ state()?.empty_text || 'The queue is empty. Press Generate to submit a render.' }}</p>
            </div>
          }
        </div>

        <div class="foot">
          <p class="note" role="status">{{ state()?.note || standard }}</p>
          <span class="hint">Select a request, then Cancel or Retry.</span>
        </div>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .wrap { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr) auto; height: 100%; min-height: 0; padding-top: 12px; }
    .head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px; padding-bottom: 10px; }
    .summary { margin: 0; font-family: var(--font-mono); font-size: 10.5px; color: var(--fg-muted); text-align: right; }
    .table { min-width: 0; width: 100%; max-width: 100%; min-height: 0; overflow: hidden; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .foot { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 16px; padding-top: 10px; }
    .note { margin: 0; font-size: 12px; color: var(--fg-muted); max-width: 80ch; }
    .hint { font-family: var(--font-mono); font-size: 10px; color: var(--fg-muted); white-space: nowrap; }
  `,
})
export class QueuePage {
  protected readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as QueueState | null);
  protected readonly rows = computed(() => this.state()?.rows ?? []);
  /** The page's pick, or the server's, so a reload or a second tab shows the same row. */
  private readonly local = signal<string | null>(null);
  protected readonly selected = computed(() => this.local() ?? this.state()?.selected ?? null);
  protected readonly standard = STANDING_NOTE;

  protected readonly columns: ColDef[] = [
    numeric('#', 'id', 45),
    { headerName: 'Profile', field: 'profile', start: 105 },
    { headerName: 'State', field: 'state', start: 80 },
    numeric('Attempts', 'attempts', 75),
    numeric('Last status', 'status', 90),
    { headerName: 'Reason', field: 'reason', flex: 1, minWidth: 140, tooltipField: 'reason' },
    { headerName: 'Request', field: 'request', start: 115, tooltipField: 'request' },
    numeric('Finished', 'finished', 75),
  ];

  protected readonly summary = computed(() => {
    const s = this.state()?.summary;
    const requests = s?.requests ?? this.rows().length;
    const lines = Object.keys(s?.lines ?? {}).length;
    const states = (s?.states ?? []).map((st) => `${st.word} ${st.count}`).join('   ');
    return [
      `${requests} request${requests === 1 ? '' : 's'}`,
      s?.pending ? `${s.pending} not finished` : '',
      lines > 1 ? `${lines} profiles in flight` : '',
      states,
    ]
      .filter(Boolean)
      .join(' · ');
  });

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`queue.${action}`);
  }

  /** Why an action is off, in words, rather than leaving a disabled button unexplained. */
  protected refusal(action: 'cancel' | 'retry'): string {
    const state = this.state();
    if (!this.selected()) return 'Select a request first.';
    if (action === 'cancel' && !state?.can_cancel) return 'This request has already been sent, so it cannot be cancelled.';
    if (action === 'retry' && !state?.can_retry) return 'Only a failed request can be retried.';
    return '';
  }

  protected pick(key: string): void {
    this.local.set(key);
    // Cancel and Retry act on the server's selection, not on the row key.
    void this.store.act('queue', 'select', { key });
  }

  protected act(action: 'cancel' | 'retry' | 'clear_finished'): void {
    const job = this.selected();
    if (action !== 'clear_finished' && !job) return;
    void this.store.act('queue', action, job ? { job } : {});
  }
}
