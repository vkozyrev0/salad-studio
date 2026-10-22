import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ColDef } from 'ag-grid-community';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { DataGrid } from '../../shared/data-grid';
import { Field } from '../../shared/field';

interface LoraRow {
  id: string;
  name?: string;
  verified?: boolean;
  version?: string;
  model?: string;
  source?: string;
}

type FormField = 'name' | 'filename' | 'family' | 'strength_model' | 'strength_clip';

interface LoraForm {
  ref?: string;
  name?: string;
  filename?: string;
  family?: string;
  strength_model?: string;
  strength_clip?: string;
}

interface LorasState {
  rows?: LoraRow[];
  empty_text?: string;
  find?: string;
  families?: string[];
  form?: LoraForm;
  selected?: string | null;
}

/**
 * LoRAs: the library as a table, the find box narrowing it, the add/edit form.
 *
 * The form is the page's edit buffer. A typed field is written to the server
 * at once, so the selected row's checks and the Add button both see what is
 * on screen, and a Save has nothing left to carry but the selection.
 */
@Component({
  selector: 'app-loras-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, DataGrid, Field],
  template: `
    <app-page-frame>
      <div class="grid-page">
        <div class="find">
          <app-field label="Find by name" [value]="find()" [w]="300" (changed)="findIt($event)" />
          <button class="btn quiet" type="button" [disabled]="!find()" (click)="findIt('')">Clear</button>
          <span class="hint">a part of the name is enough</span>
        </div>

        <div class="table">
          @if (rows().length || store.loading() || store.loadError()) {
            <app-data-grid [rows]="rows()" [columns]="columns" field="id" [selected]="selected()" (picked)="pick($event)" />
          } @else {
            <p class="empty">{{ state()?.empty_text || 'No LoRAs in the library.' }}</p>
          }
        </div>

        <section class="section form" aria-labelledby="form-head">
          <div class="section-head"><h2 class="eyebrow" id="form-head">Add / edit LoRA</h2></div>
          <app-field
            label="Civitai / HF URL / civitai:id@version / local path"
            [value]="form().ref ?? ''"
            [w]="520"
            [mono]="true"
            placeholder="https://civitai.com/models/12345"
            (changed)="draft('ref', $event)"
          />
          <div class="rows">
            <app-field label="Name (optional)" [value]="form().name ?? ''" [w]="320" (changed)="edit('name', $event)" />
            <app-field label="Filename (optional)" [value]="form().filename ?? ''" [w]="320" (changed)="edit('filename', $event)" />
          </div>
          <div class="rows">
            <app-field label="Works with" kind="select" [value]="form().family ?? ''" [options]="families()" [w]="200" (changed)="edit('family', $event)" />
            <app-field label="Strength model" [value]="form().strength_model ?? ''" [w]="120" [inputMode]="'decimal'" (changed)="edit('strength_model', $event)" />
            <app-field label="Strength clip" [value]="form().strength_clip ?? ''" [w]="120" [inputMode]="'decimal'" (changed)="edit('strength_clip', $event)" />
          </div>
          <div class="btn-row">
            <button class="btn primary" type="button" [disabled]="busy('add_lora')" (click)="add()">
              @if (busy('add_lora')) { <span class="spinner" aria-hidden="true"></span> }
              {{ busy('add_lora') ? 'Adding' : 'Add' }}
            </button>
            <button class="btn ghost" type="button" [disabled]="!selected() || busy('save_edits')" (click)="act('save_edits')">Save edits</button>
            <button class="btn ghost" type="button" [disabled]="!selected() || busy('verify_selected')" (click)="verify()">
              @if (busy('verify_selected')) { <span class="spinner" aria-hidden="true"></span> }
              Verify
            </button>
            <button class="btn ghost" type="button" [disabled]="busy('verify_unverified')" (click)="act('verify_unverified')">
              @if (busy('verify_unverified')) { <span class="spinner" aria-hidden="true"></span> }
              Verify unverified
            </button>
            <button class="btn danger" type="button" [disabled]="!selected()" (click)="act('remove_selected')">Remove</button>
          </div>
        </section>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .grid-page {
      display: grid;
      grid-template-rows: auto minmax(220px, 1fr) auto;
      gap: 12px;
      height: 100%;
      min-height: 0;
      padding-top: 12px;
      overflow: auto;
    }
    .find { display: flex; align-items: flex-end; gap: 9px; }
    .table { min-height: 220px; overflow: hidden; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .empty { margin: 0; padding: 16px 2px; font-size: 12.5px; color: var(--fg-muted); }
    .form { display: flex; flex-direction: column; gap: 12px; padding-bottom: 12px; }
    .form .section-head { margin-bottom: 0; }
    .rows { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; }
  `,
})
export class LorasPage {
  protected readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as LorasState | null);
  protected readonly rows = computed(() => this.state()?.rows ?? []);
  private readonly local = signal<string | null>(null);
  protected readonly selected = computed(() => this.local() ?? this.state()?.selected ?? null);
  protected readonly families = computed(() =>
    (this.state()?.families ?? ['Flux.2 Klein', 'Flux.1 Dev', 'Pony', 'SDXL', 'Krea 2', 'Illustrious', 'unknown']).map(
      (f) => ({ value: f, label: f }),
    ),
  );
  private readonly formDraft = signal<LoraForm | null>(null);
  protected readonly form = computed(() => this.formDraft() ?? this.state()?.form ?? {});

  /** The text box holds what was typed; once sent, the server's copy is the one read. */
  private readonly findText = signal<string | null>(null);
  protected readonly find = computed(() => this.findText() ?? this.state()?.find ?? '');

  protected readonly columns: ColDef[] = [
    {
      headerName: 'Verified',
      field: 'verified',
      start: 100,
      filter: false,
      valueFormatter: (p) => (p.value ? '● yes' : '● no'),
      cellStyle: (p) => ({ color: p.value ? 'var(--valid)' : 'var(--invalid)' }),
    },
    { headerName: 'Id', field: 'id', start: 110, filter: false, tooltipField: 'source' },
    { headerName: 'Name', field: 'name', start: 220 },
    { headerName: 'Version', field: 'version', start: 120 },
    { headerName: 'Model', field: 'model', start: 140 },
    { headerName: 'Source', field: 'source', start: 140, tooltipField: 'source', cellStyle: { 'font-family': 'var(--font-mono)', 'font-size': '11.5px' } },
  ];

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`loras.${action}`);
  }

  protected findIt(text: string): void {
    this.findText.set(text);
    void this.store.act('loras', 'find', { text });
  }

  protected pick(id: string): void {
    this.local.set(id);
    this.formDraft.set(null);
    // The edit box takes the selection and goes blank: it names a new LoRA.
    void this.store.act('loras', 'select', { id }).then(() => {
      if (this.selected() === id) this.formDraft.set(null);
    });
  }

  /** The reference the Add sends is read from the box at click time; the rest is already saved. */
  protected draft(field: 'ref', value: string): void {
    this.formDraft.set({ ...this.form(), [field]: value });
  }

  protected edit(field: FormField, value: string): void {
    this.formDraft.set({ ...this.form(), [field]: value });
    void this.store.act('loras', 'edit_form', { field, value });
  }

  protected add(): void {
    const ref = (this.form().ref ?? '').trim();
    if (!ref) return;
    // The form rides along, so the box reaches the store before any click can.
    void this.store.act('loras', 'add_lora', { ref, ...this.form() });
  }

  protected verify(): void {
    const id = this.selected();
    void this.store.act('loras', 'verify_selected', id ? { id } : {});
  }

  protected act(action: 'save_edits' | 'verify_unverified' | 'remove_selected'): void {
    const id = this.selected();
    const selection = id ? { id } : {};
    void this.store.act('loras', action, action === 'save_edits' ? { ...selection, ...this.form() } : selection);
    if (action === 'remove_selected') this.local.set(null);
  }
}
