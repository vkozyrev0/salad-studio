import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ColDef } from 'ag-grid-community';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { DataGrid } from '../../shared/data-grid';
import { clock } from '../../shared/format';

interface HistoryRow {
  id: string;
  ts?: number;
  prompt?: string;
  graph?: string;
  rating?: number;
  image?: string;
  profile?: string;
}

interface HistoryState {
  rows?: HistoryRow[];
  empty_text?: string;
  selected?: string | null;
}

/**
 * Prompt History: every request, its prompt, its graph and its rating.
 *
 * The graph cell is the request's shape — nodes, LoRAs and size — with the
 * whole line as its tooltip; the model ids are left to the tooltip because the
 * column has no room for them. A rating is stars, and a rating that is not
 * there reads as a dash rather than as an empty cell.
 */
@Component({
  selector: 'app-history-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, DataGrid],
  template: `
    <app-page-frame>
      <div class="wrap">
        <div class="meta">
          <span><b>{{ rows().length }}</b> requests · <b>{{ rated() }}</b> rated</span>
          <span>Newest first</span>
        </div>

        <div class="table">
          @if (rows().length || store.loading() || store.loadError()) {
            <app-data-grid [rows]="rows()" [columns]="columns" field="id" [selected]="selected()" (picked)="pick($event)" />
          } @else {
            <div class="empty-sheet">
              <p class="empty-title">The reel is empty</p>
              <p class="empty-hint">{{ state()?.empty_text || 'No prompts yet. Every Generate stores its request here.' }}</p>
            </div>
          }
        </div>

        <div class="foot">
          <div class="selection">
            <span class="eyebrow">Selected</span>
            <span class="selection-meta">{{ chosen()?.prompt || 'No request selected' }}</span>
          </div>

          <div class="rating-control" role="group" aria-label="Rate the selected request">
            <span class="eyebrow">Rating</span>
            @for (n of stars; track n) {
              <button
                class="star"
                type="button"
                [class.on]="n <= (chosen()?.rating ?? 0)"
                [attr.aria-label]="'Rate ' + n + (n === 1 ? ' star' : ' stars')"
                [attr.aria-pressed]="n === chosen()?.rating"
                [disabled]="!chosen() || busy('rate')"
                (click)="rate(n)"
              >★</button>
            }
            <button class="btn quiet sm" type="button" [disabled]="!chosen() || busy('rate')" (click)="rate(0)">No stars</button>
          </div>

          <div class="btn-row">
            <button class="btn primary" type="button" [disabled]="!chosen() || busy('reuse')" (click)="act('reuse')">
              @if (busy('reuse')) { <span class="spinner" aria-hidden="true"></span> }
              Reuse
            </button>
            <button class="btn danger" type="button" [disabled]="!chosen() || busy('delete')" (click)="act('delete')">
              Delete
            </button>
          </div>
        </div>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .wrap { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; height: 100%; min-height: 0; }
    .meta {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      padding: 13px 0 8px;
      font-family: var(--font-mono);
      font-size: 10px;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--fg-muted);
    }
    .meta b { font-weight: 500; color: var(--fg); }
    .table { min-height: 0; overflow: hidden; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .foot { display: flex; align-items: center; gap: 20px; min-height: 58px; padding-top: 8px; }
    .selection { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex: 1; }
    .selection-meta {
      font-family: var(--font-mono);
      font-size: 10.5px;
      color: var(--fg);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .rating-control { display: flex; align-items: center; gap: 1px; flex: none; }
    .rating-control .eyebrow { margin-right: 9px; }
    .star {
      width: 26px;
      height: 28px;
      padding: 0;
      border: 0;
      border-radius: 2px;
      background: none;
      color: var(--rule);
      font-family: 'Segoe UI Symbol', var(--font-ui);
      font-size: 15px;
      line-height: 1;
      cursor: pointer;
    }
    .star:hover:not(:disabled) { color: var(--fg); background: var(--wash); }
    .star.on { color: var(--accent); }
    .star:disabled { opacity: 0.35; cursor: default; }
    :host ::ng-deep .plate-cell { display: flex; align-items: center; justify-content: center; padding: 0; }
    @media (max-width: 900px) {
      .foot { flex-wrap: wrap; gap: 10px; }
      .selection { flex-basis: 100%; }
    }
  `,
})
export class HistoryPage {
  protected readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as HistoryState | null);
  protected readonly rows = computed(() => this.state()?.rows ?? []);
  private readonly local = signal<string | null>(null);
  protected readonly selected = computed(() => this.local() ?? this.state()?.selected ?? null);
  protected readonly chosen = computed(() => this.rows().find((row) => row.id === this.selected()) ?? null);
  protected readonly rated = computed(() => this.rows().filter((row) => (row.rating ?? 0) > 0).length);
  protected readonly stars = [1, 2, 3, 4, 5];

  /**
   * The prompt is the only column that grows. Every other one has a base
   * width its content fits, so the grid never crushes Graph or Rating into an
   * ellipsis while the prompt takes all the slack.
   */
  protected readonly columns: ColDef[] = [
    { headerName: 'When', field: 'ts', start: 82, flex: 0, valueFormatter: (p) => clock(p.value) },
    { headerName: 'Prompt', field: 'prompt', flex: 3, minWidth: 240, tooltipField: 'prompt' },
    {
      headerName: 'Graph',
      field: 'graph',
      start: 250,
      flex: 0,
      tooltipField: 'graph',
      valueFormatter: (p) => compactGraph(String(p.value ?? '')),
      cellStyle: { 'font-family': 'var(--font-mono)', 'font-size': '11.5px', color: 'var(--fg-muted)' },
    },
    {
      headerName: 'Rating',
      field: 'rating',
      start: 92,
      flex: 0,
      valueFormatter: (p) => (Number(p.value) > 0 ? '★'.repeat(Number(p.value)) : '-'),
      cellStyle: { color: 'var(--accent)', 'letter-spacing': '1px' },
    },
    {
      headerName: 'Plate',
      field: 'image',
      start: 74,
      flex: 0,
      sortable: false,
      filter: false,
      cellClass: 'plate-cell',
      cellRenderer: (p: { value?: string }) =>
        p.value
          ? `<span class="print small" style="width:36px;height:36px;display:inline-block"><img src="${p.value}" alt="" loading="lazy" style="width:100%;height:100%;object-fit:cover"></span>`
          : '',
    },
  ];

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`history.${action}`);
  }

  protected pick(id: string): void {
    this.local.set(id);
    // The server's Rate, Reuse and Delete act on its own selection.
    void this.store.act('history', 'select', { id });
  }

  protected rate(stars: number): void {
    void this.store.act('history', 'rate', { id: this.selected(), stars });
    this.local.set(null);
  }

  protected act(action: 'reuse' | 'delete'): void {
    void this.store.act('history', action, { id: this.selected() });
  }
}

/**
 * A graph summary without the model ids. A history cell has room for the
 * shape of the request, not for every civitai id; the tooltip keeps the
 * whole line.
 */
function compactGraph(text: string): string {
  const parts = text
    .replace(/\s*\(civitai:[^)]*\)/gi, '')
    .split('·')
    .map((part) => part.trim())
    .filter(Boolean);
  return parts.slice(0, 3).join(' · ');
}
