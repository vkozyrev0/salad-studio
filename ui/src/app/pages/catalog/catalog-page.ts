import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { ColDef } from 'ag-grid-community';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { Field } from '../../shared/field';
import { DataGrid } from '../../shared/data-grid';

interface CatalogRow {
  id: string;
  name?: string;
  description?: string;
  cells?: string[];
}

interface CatalogState {
  rows?: CatalogRow[];
  empty?: string;
  status?: string;
}

/**
 * Prompt Catalog: kept requests under a short name and a description.
 *
 * A click fills the two fields from the row, and the fields then belong to the
 * person editing them. Every action names the row it means, so a Delete that
 * goes through a confirm still deletes the row the dialog named.
 */
@Component({
  selector: 'app-catalog-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field, DataGrid],
  template: `
    <app-page-frame>
      <div class="wrap">
        <div class="meta" role="group" aria-label="Name and description of the selected entry">
          <app-field label="Short name" [value]="name()" [w]="240" (changed)="name.set($event)" />
          <app-field label="Description" [value]="description()" [w]="460" (changed)="description.set($event)" />
        </div>

        <div class="table">
          @if (rows().length || store.loading() || store.loadError()) {
            <app-data-grid [rows]="rows()" [columns]="columns" field="id" [selected]="selected()" (picked)="pick($event)" />
          } @else {
            <div class="empty-sheet">
              <p class="empty-title">The shelf is empty</p>
              <p class="empty-hint">{{ state()?.empty || 'No kept prompts yet. Give one a short name and copy it from the Prompt Editor.' }}</p>
            </div>
          }
        </div>

        <div class="strip">
          <button class="btn ghost" type="button" [disabled]="busy('add')" (click)="act('add')">
            @if (busy('add')) { <span class="spinner" aria-hidden="true"></span> }
            Copy from Prompt Editor
          </button>
          <button class="btn ghost" type="button" [disabled]="!selected() || busy('save_meta')" (click)="act('save_meta')">
            Save name / description
          </button>
          <button class="btn ghost" type="button" [disabled]="!selected() || busy('update_json')" (click)="act('update_json')">
            Update JSON
          </button>
          <button class="btn primary" type="button" [disabled]="!selected() || busy('load')" (click)="act('load')">
            @if (busy('load')) { <span class="spinner" aria-hidden="true"></span> }
            Load into Prompt Editor
          </button>
          <button class="btn danger" type="button" [disabled]="!selected()" (click)="act('delete')">Delete</button>
          <p class="status" role="status">{{ status() }}</p>
        </div>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .wrap { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; height: 100%; min-height: 0; }
    .meta { display: flex; flex-wrap: wrap; gap: 12px; padding: 12px 0; }
    .table { min-height: 0; overflow: hidden; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .strip { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; padding-top: 12px; }
    .status { margin: 0 0 0 auto; font-size: 12px; color: var(--fg-muted); }
  `,
})
export class CatalogPage {
  protected readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as CatalogState | null);
  protected readonly rows = computed(() => this.state()?.rows ?? []);
  protected readonly status = computed(() => this.state()?.status ?? '');

  protected readonly name = signal('');
  protected readonly description = signal('');
  private readonly chosen = signal<string | null>(null);
  protected readonly selected = computed(() => this.chosen());

  protected readonly columns: ColDef[] = [
    { headerName: 'Added', colId: 'added', start: 150, valueGetter: (p) => cell(p.data, 0), valueFormatter: (p) => String(p.value ?? '') },
    { headerName: 'Short name', colId: 'name', start: 160, valueGetter: (p) => cell(p.data, 1), tooltipValueGetter: (p) => cell(p.data, 1) },
    {
      headerName: 'Description',
      colId: 'description',
      start: 190,
      valueGetter: (p) => cell(p.data, 2),
      tooltipValueGetter: (p) => cell(p.data, 2),
    },
    { headerName: 'Prompt', colId: 'prompt', flex: 1, minWidth: 240, tooltipValueGetter: (p) => cell(p.data, 3), valueGetter: (p) => cell(p.data, 3) },
    {
      headerName: 'Graph',
      colId: 'graph',
      start: 250,
      flex: 0,
      valueGetter: (p) => cell(p.data, 4),
      valueFormatter: (p) => compactGraph(String(p.value ?? '')),
      tooltipValueGetter: (p) => cell(p.data, 4),
      cellStyle: { 'font-family': 'var(--font-mono)', 'font-size': '11.5px', color: 'var(--fg-muted)' },
    },
  ];

  constructor() {
    // A new pick, or a row that came back changed, fills the fields. Untouched
    // fields are never overwritten, so typing survives an event-driven reply.
    effect(() => {
      const id = this.selected();
      const row = this.rows().find((r) => r.id === id);
      if (!row) return;
      untracked(() => {
        this.name.set(row.name ?? '');
        this.description.set(row.description ?? '');
      });
    });
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`catalog.${action}`);
  }

  protected pick(id: string): void {
    if (id === this.chosen()) return;
    this.chosen.set(id);
    const row = this.rows().find((r) => r.id === id);
    this.name.set(row?.name ?? '');
    this.description.set(row?.description ?? '');
  }

  protected act(action: 'add' | 'save_meta' | 'update_json' | 'load' | 'delete'): void {
    const id = this.selected();
    if (action === 'add') {
      void this.store.act('catalog', action, { name: this.name(), description: this.description() });
      return;
    }
    if (!id) return;
    const args =
      action === 'save_meta'
        ? { id, name: this.name(), description: this.description() }
        : { id };
    void this.store.act('catalog', action, args);
    if (action === 'delete') this.chosen.set(null);
  }
}

/** The cell text `columns` names for a row, read positionally from the server's `cells`. */
function cell(row: unknown, index: number): string {
  const cells = (row as CatalogRow | null | undefined)?.cells;
  return Array.isArray(cells) ? String(cells[index] ?? '') : '';
}

/**
 * A graph summary without the model ids. The cell has room for the shape of
 * the request, not for every civitai id; the tooltip keeps the whole line.
 */
function compactGraph(text: string): string {
  return text.replace(/\s*\(civitai:[^)]*\)/gi, '').replace(/\s+/g, ' ').trim();
}
