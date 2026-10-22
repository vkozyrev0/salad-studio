import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { StudioStore } from '../core/studio-store';
import { AgGridAngular } from 'ag-grid-angular';
import {
  ColDef,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  RowSelectionOptions,
  SelectionChangedEvent,
} from 'ag-grid-community';
import { studioGridTheme } from '../core/studio-grid-theme';

declare module 'ag-grid-community' {
  interface ColDef {
    /** The column's width at load. A column without one takes the leftover space. */
    start?: number;
  }
}

/**
 * The studio's table: AG Grid Community with one row selectable, sorting and
 * filtering client-side. A page passes its rows and the property that
 * identifies one; the selected row's key goes out as `picked`, for the
 * actions that need a selection.
 *
 * The theme is `studioGridTheme` with the visual prototype's 48px row on top.
 * A page also passes `order`, the grid's displayed order once a sort has
 * happened, so the page's arrows step through what is on screen.
 */
@Component({
  selector: 'app-data-grid',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AgGridAngular],
  template: `
    <ag-grid-angular
      class="grid"
      [theme]="theme"
      [columnDefs]="defs()"
      [rowData]="data()"
      [getRowId]="rowId"
      [rowSelection]="selection"
      [gridOptions]="options"
      [loading]="loading() || store.loading()"
      [overlayNoRowsTemplate]="emptyText()"
      (gridReady)="ready($event)"
      (selectionChanged)="pick($event)"
      (sortChanged)="orderChanged()"
      (filterChanged)="orderChanged()"
    />
  `,
  styles: `
    :host { display: block; min-height: 0; height: 100%; }
    /* AG Grid lays itself out from its container's height. Without this the
       grid computes a zero-height body and draws no rows at all. */
    .grid { display: block; width: 100%; height: 100%; min-height: 180px; }
    :host ::ng-deep .ag-root-wrapper,
    :host ::ng-deep .ag-body-viewport { scrollbar-color: var(--fg-muted) var(--well); scrollbar-width: thin; }
  `,
})
export class DataGrid {
  readonly rows = input.required<readonly object[]>();
  readonly columns = input.required<ColDef[]>();
  /** The property that identifies a row across refreshes. */
  readonly field = input.required<string>();
  readonly selected = input<string | null>(null);
  readonly loading = input(false);
  readonly empty = input('No rows.');

  readonly picked = output<string>();
  /** The displayed keys, in the grid's order, after every sort, filter or data change. */
  readonly order = output<string[]>();

  /** `studioGridTheme` keeps its palette and takes the prototype's 48px row; the page draws the frame. */
  protected readonly theme = studioGridTheme.withParams({
    rowHeight: 48,
    headerHeight: 36,
    wrapperBorderRadius: 0,
    wrapperBorder: false,
  });

  private readonly store = inject(StudioStore);

  /** A failed page load is not "no rows"; say which one it is. */
  protected readonly emptyText = computed(() =>
    this.store.loadError() ? 'Could not load this table.' : this.empty());

  protected readonly options = {
    animateRows: false,
    tooltipShowDelay: 300,
  };
  protected readonly selection: RowSelectionOptions = {
    mode: 'singleRow',
    enableClickSelection: true,
    checkboxes: false,
  };
  protected readonly rowId = (params: GetRowIdParams) => this.key(params.data);
  protected readonly data = computed<object[]>(() => [...this.rows()]);

  protected readonly defs = computed<ColDef[]>(() =>
    this.columns().map(({ start, ...column }) => ({
      sortable: true,
      filter: true,
      resizable: true,
      ...column,
      width: column.width ?? start,
      flex: column.flex ?? (column.width === undefined && start === undefined ? 1 : undefined),
    })),
  );

  private readonly view = viewChild(AgGridAngular);
  private api: GridApi | null = null;
  private readonly readyRev = signal(0);
  private applied: readonly object[] = [];

  constructor() {
    effect(() => {
      this.readyRev();
      const api = this.api;
      if (!api) return;
      const rows = this.rows();
      const selected = this.selected();
      untracked(() => {
        if (api.isDestroyed()) return;
        if (rows !== this.applied) {
          this.applied = rows;
          api.setGridOption('rowData', [...rows]);
        }
        const [current] = api.getSelectedRows();
        if ((current ? this.key(current) : null) !== selected) this.select(api, selected);
      });
    });
  }

  protected ready(event: GridReadyEvent): void {
    this.api = event.api;
    this.readyRev.update((n) => n + 1);
    this.orderChanged();
  }

  protected pick(event: SelectionChangedEvent): void {
    const [row] = event.api.getSelectedRows();
    this.picked.emit(this.key(row ?? null));
  }

  protected orderChanged(): void {
    if (!this.api || this.api.isDestroyed()) return;
    const rows: unknown[] = [];
    this.api.forEachNodeAfterFilterAndSort((node) => rows.push(this.key(node.data)));
    this.order.emit(rows.map(String));
  }

  private select(api: GridApi, key: string | null): void {
    // Selecting through the API fires no selectionChanged, so a page's own
    // echo of its choice cannot loop back as a new pick.
    api.forEachNode((node) => node.setSelected(key !== null && this.key(node.data) === key));
    const node = key === null ? undefined : api.getRowNode(key);
    if (node) api.ensureIndexVisible(node.rowIndex ?? 0, 'middle');
  }

  private key(row: unknown): string {
    return String((row as Record<string, unknown> | null | undefined)?.[this.field()] ?? '');
  }
}

/** A right-aligned, tabular number column. */
export function numeric(headerName: string, field: string, start: number): ColDef {
  return {
    headerName,
    field,
    start,
    type: 'rightAligned',
    cellStyle: { 'font-variant-numeric': 'tabular-nums' },
  };
}
