import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { Field } from '../../shared/field';
import { SCHEDULERS, UNETS } from '../../shared/catalogs';

interface ImportState {
  url?: string;
  meta?: string;
  workflow?: string;
  stashed?: boolean;
  knobs?: { key: string; label: string; value: string }[];
  scheduler?: string;
  scheduler_labels?: string[];
  unet?: string;
  unet_labels?: string[];
  issues?: string[];
  notes?: string[];
  inspected?: boolean;
}

interface Boxes {
  url: string;
  meta: string;
  workflow: string;
}

const FILL_DELAY_MS = 400;

const KNOBS: readonly { key: string; label: string }[] = [
  { key: 'cfg', label: 'CFG' },
  { key: 'seed', label: 'Seed' },
  { key: 'steps', label: 'Steps' },
  { key: 'width', label: 'Width' },
  { key: 'height', label: 'Height' },
];

/**
 * Import: paste a Comfy workflow or Civitai data, fill the knobs, convert.
 *
 * Typing a paste posts it at once; the knobs fill 400ms after a pause in the
 * generation-data box, and only where they are empty, so a number typed by
 * hand is never overwritten. The issues box states whether a paste was checked
 * at all, so an empty box is not read as "nothing wrong".
 */
@Component({
  selector: 'app-import-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field],
  template: `
    <app-page-frame>
      <div class="scroll">
        <div class="url">
          <app-field label="Civitai image URL" [value]="boxes().url" [w]="560" [mono]="true" (changed)="type('url', $event)" />
          <button class="btn ghost" type="button" [disabled]="busy('fetch_civitai')" (click)="fetch()">
            @if (busy('fetch_civitai')) { <span class="spinner" aria-hidden="true"></span> }
            Fetch from Civitai
          </button>
        </div>

        <app-field
          label="Civitai generation data (prompt + Steps / CFG, or Sampler / Seed / Model)"
          kind="textarea"
          [rows]="4"
          [value]="boxes().meta"
          (changed)="type('meta', $event)"
        />
        @if (state()?.stashed) {
          <app-field
            label="Comfy workflow JSON (a paste is held in memory)"
            kind="textarea"
            [rows]="4"
            [value]="boxes().workflow"
            [readonly]="true"
            [hint]="'Clear Import drops the paste.'"
          />
        } @else {
          <app-field
            label="Comfy workflow JSON (a paste is held in memory)"
            kind="textarea"
            [rows]="5"
            [value]="boxes().workflow"
            (changed)="type('workflow', $event)"
          />
        }

        <div class="knobs">
          @for (knob of knobs; track knob.key) {
            <app-field [label]="knob.label" [value]="knobValue(knob.key)" [w]="110" [inputMode]="'decimal'" (changed)="type(knob.key, $event)" />
          }
          <app-field label="Scheduler" [id]="'import-scheduler'" kind="select" [value]="choices().scheduler" [options]="schedulerOptions()" [w]="200" (changed)="type('scheduler', $event)" />
          <app-field label="Checkpoint" [id]="'import-checkpoint'" kind="select" [value]="choices().unet" [options]="unetOptions()" [w]="200" (changed)="type('unet', $event)" />
        </div>

        <section class="issues" aria-labelledby="issues-head">
          <h2 class="eyebrow" id="issues-head">Salad replica issues</h2>
          <pre class="readout" tabindex="0">{{ issuesText() }}</pre>
        </section>

        <div class="btn-row">
          <button class="btn ghost" type="button" [disabled]="busy('fill_knobs')" (click)="fill()">
            @if (busy('fill_knobs')) { <span class="spinner" aria-hidden="true"></span> }
            Fill knobs from paste
          </button>
          <button class="btn primary" type="button" [disabled]="busy('convert')" (click)="convert()">
            @if (busy('convert')) { <span class="spinner" aria-hidden="true"></span> }
            {{ busy('convert') ? 'Converting' : 'Convert to Prompt Editor' }}
          </button>
          <button class="btn quiet" type="button" [disabled]="busy('clear_import')" (click)="act('clear_import')">Clear Import</button>
        </div>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .scroll { display: flex; flex-direction: column; gap: 8px; height: 100%; min-height: 0; padding-top: 12px; overflow: auto; }
    /* A field in a column takes the column's width; the shared control is
       sized for a row, where its width is set by the page. */
    .scroll > app-field { display: block; width: 100%; }
    .scroll > app-field ::ng-deep .field { width: 100%; }
    .url { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
    .knobs { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
    .issues { display: grid; gap: 6px; }
    .issues h2 { margin: 0; }
    .readout { min-height: 48px; max-height: 260px; }
  `,
})
export class ImportPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as ImportState | null);
  protected readonly knobs = KNOBS;

  /** Every box as typed. A reply re-seeds them unless the box holds a newer keystroke. */
  private readonly draft = signal<Partial<ImportState> | null>(null);
  protected readonly boxes = computed<Boxes>(() => ({
    url: this.draft()?.url ?? this.state()?.url ?? '',
    meta: this.draft()?.meta ?? this.state()?.meta ?? '',
    workflow: this.draft()?.workflow ?? this.state()?.workflow ?? '',
  }));

  protected readonly schedulerOptions = computed(() =>
    (this.state()?.scheduler_labels?.length ? this.state()?.scheduler_labels ?? [] : SCHEDULERS.map((s) => s.label)).map(
      (label) => ({ value: label, label }),
    ),
  );
  protected readonly unetOptions = computed(() => {
    const labels = this.state()?.unet_labels ?? [];
    if (labels.length) return [{ value: '', label: '-' }, ...labels.map((label) => ({ value: label, label }))];
    return UNETS.map((u) => ({ value: u.value, label: u.label }));
  });

  protected readonly issuesText = computed(() => {
    const state = this.state();
    const issues = state?.issues ?? [];
    const notes = state?.notes ?? [];
    if (issues.length) {
      return ['This graph cannot run on the Salad Klein replica:', '', ...issues.map((i) => `• ${i}`)].join('\n');
    }
    if (notes.length) {
      return ['Warnings:', '', ...notes.map((n) => `• ${n}`)].join('\n');
    }
    if (state?.inspected) return 'No replica issues.';
    return '';
  });

  constructor() {
    effect(() => {
      this.store.page();
      untracked(() => this.draft.set(null));
    });
  }

  protected knobValue(key: string): string {
    const draft = this.draft() as Record<string, string> | null;
    if (draft && key in draft) return String(draft[key]);
    return this.state()?.knobs?.find((k) => k.key === key)?.value ?? '';
  }

  protected readonly choices = computed(() => ({
    scheduler: this.draft()?.scheduler ?? this.state()?.scheduler ?? 'Flux2 (Klein)',
    unet: this.draft()?.unet ?? this.state()?.unet ?? '',
  }));

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`import.${action}`);
  }

  /**
   * A box's new text. The four box texts and the knob values go to the server
   * as a paste; the two selects wait for the action that reads them, since
   * the paste action has no place for them.
   */
  protected type(key: keyof ImportState | string, value: string): void {
    this.draft.update((d) => ({ ...(d ?? {}), [key]: value }));
    if (key === 'scheduler' || key === 'unet') return;
    void this.store.act('import', 'set_paste', this.payload());
    // Only a change in the generation data starts the fill; typing elsewhere
    // leaves a fill that is already pending alone.
    if (key === 'meta') this.scheduleFill();
  }

  protected fill(): void {
    clearTimeout(this.fillTimer);
    void this.store.act('import', 'fill_knobs', { ...this.payload(), only_empty: false });
  }

  protected fetch(): void {
    clearTimeout(this.fillTimer);
    void this.store.act('import', 'fetch_civitai', this.payload());
  }

  protected convert(): void {
    clearTimeout(this.fillTimer);
    const args = { ...this.payload(), fill_empty: KNOBS.some((k) => !this.knobValue(k.key).trim()) };
    void this.store.act('import', 'convert', args);
  }

  protected act(action: 'clear_import'): void {
    clearTimeout(this.fillTimer);
    // The boxes go blank now; a stale reply still in flight cannot put them back.
    this.draft.set({ url: '', meta: '', workflow: '', scheduler: '', unet: '' });
    void this.store.act('import', action);
  }

  private fillTimer: ReturnType<typeof setTimeout> | undefined;

  private scheduleFill(): void {
    clearTimeout(this.fillTimer);
    this.fillTimer = setTimeout(() => {
      void this.store.act('import', 'fill_knobs', { ...this.payload(), only_empty: true });
    }, FILL_DELAY_MS);
  }

  /**
   * The boxes as the server adopts them. A stashed workflow is left out: the
   * box shows a summary, and sending it would replace the paste it stands for.
   */
  private payload(): Record<string, string> {
    const boxes = this.boxes();
    const knobs = Object.fromEntries(KNOBS.map((k) => [k.key, this.knobValue(k.key)]));
    return {
      url: boxes.url,
      meta: boxes.meta,
      ...(this.state()?.stashed ? {} : { workflow: boxes.workflow }),
      ...knobs,
      scheduler: this.choices().scheduler,
      unet: this.choices().unet,
    };
  }
}
