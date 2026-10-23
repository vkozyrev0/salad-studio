import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { Field } from '../../shared/field';
import { SCHEDULERS } from '../../shared/catalogs';

type Knob = 'width' | 'height' | 'steps' | 'cfg' | 'seed';

interface LoraChoice {
  id: string;
  label: string;
  selected: boolean;
}

interface SettingsState {
  knobs?: Partial<Record<Knob, string>>;
  graphs?: string[];
  graph?: string;
  schedulers?: string[];
  scheduler?: string;
  checkpoints?: string[];
  checkpoint?: string;
  loras?: LoraChoice[];
}

const KNOBS: readonly { key: Knob; label: string; w: number }[] = [
  { key: 'width', label: 'Width', w: 0 },
  { key: 'height', label: 'Height', w: 0 },
  { key: 'steps', label: 'Steps', w: 0 },
  { key: 'cfg', label: 'CFG', w: 0 },
  { key: 'seed', label: 'Seed', w: 0 },
];

/**
 * Prompt Settings: the knobs a request carries, and the LoRAs it selects.
 *
 * Every change writes the server's form at once, so the editor and Generate
 * read what is on screen. A box keeps what was typed while the next reply is
 * in flight and takes the reply's value once it lands.
 */
@Component({
  selector: 'app-settings-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field],
  template: `
    <app-page-frame>
      <div class="split">
        <div class="knobs">
          @for (knob of knobs; track knob.key) {
            <app-field
              [class.wide]="knob.key === 'seed'"
              [label]="knob.label"
              [value]="knobValue(knob.key)"
              [w]="knob.w"
              [inputMode]="'decimal'"
              (changed)="setKnob(knob.key, $event)"
            />
          }
          <app-field class="wide" label="Graph" kind="select" [value]="state()?.graph ?? ''" [options]="graphs()" [w]="0" (changed)="set({ graph: $event })" />
          <app-field class="wide" label="Scheduler" [id]="'settings-scheduler'" kind="select" [value]="state()?.scheduler ?? 'Flux2 (Klein)'" [options]="schedulers()" [w]="0" (changed)="set({ scheduler: $event })" />
          <app-field class="wide" label="Checkpoint" [id]="'settings-checkpoint'" kind="select" [value]="state()?.checkpoint ?? ''" [options]="checkpoints()" [w]="0" (changed)="set({ checkpoint: $event }, 'select_checkpoint')" />

          <div class="save">
            <button class="btn primary" type="button" [disabled]="busy('save')" (click)="set({}, 'save')">
              @if (busy('save')) { <span class="spinner" aria-hidden="true"></span> }
              {{ busy('save') ? 'Saving' : 'Save to profile' }}
            </button>
          </div>
        </div>

        <section class="loras" aria-labelledby="loras-head">
          <div class="lora-head">
            <h2 class="eyebrow" id="loras-head">LoRAs</h2>
            <span class="section-meta">{{ onCount() }} of {{ loras().length }} on</span>
          </div>
          @if (loras().length) {
            <app-field class="filter" label="Find a LoRA" [value]="query()" [w]="380" placeholder="part of a name" (changed)="query.set($event)" />
            <div class="choices">
              @for (lora of shownLoras(); track lora.id) {
                <label class="check">
                  <input type="checkbox" [checked]="lora.selected" (change)="toggle(lora, $event)" />
                  <span>{{ lora.label }}</span>
                </label>
              }
            </div>
            @if (!shownLoras().length) {
              <p class="hint">No LoRA matches “{{ query() }}”.</p>
            }
          } @else {
            <p class="hint">No LoRAs for this graph.</p>
          }
        </section>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    /* Knobs are a two-column sheet so Save stays above the fold; the selects
       and the seed take the full width, which is what their values need. */
    .split { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 32px; height: 100%; min-height: 0; padding-top: 14px; }
    .knobs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-content: start;
      gap: 10px 12px;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding-right: 12px;
    }
    .knobs .wide { grid-column: 1 / -1; }
    .save { grid-column: 1 / -1; margin-top: 6px; }
    .loras { min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 12px; border-left: 1px solid var(--hairline); }
    .lora-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
    .lora-head h2 { margin: 0; }
    .filter { margin-bottom: 12px; }
    .choices { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 2px 24px; align-content: start; }
    .choices .check { align-items: flex-start; gap: 8px; padding: 5px 0; line-height: 1.3; }
    .choices .check input { flex: none; margin-top: 1px; }
    /* Below this width the LoRA list would end up narrower than a name, so the
       two columns stack and each scrolls inside the pane. */
    @media (max-width: 1040px) {
      .split { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); gap: 16px; overflow-y: auto; }
      .knobs { overflow: visible; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
      .knobs .wide { grid-column: auto; }
      .loras { border-left: 0; padding-left: 0; }
    }
  `,
})
export class SettingsPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as SettingsState | null);
  protected readonly loras = computed(() => this.state()?.loras ?? []);
  protected readonly knobs = KNOBS;

  /** The find box narrows the list on this page; it is not a server query. */
  protected readonly query = signal('');
  protected readonly shownLoras = computed(() => {
    const needle = this.query().trim().toLowerCase();
    const all = this.loras();
    return needle ? all.filter((lora) => lora.label.toLowerCase().includes(needle)) : all;
  });
  protected readonly onCount = computed(() => this.loras().filter((lora) => lora.selected).length);

  /** The typed knob values, kept until the reply to them lands. */
  private readonly draft = signal<Partial<Record<Knob, string>>>({});

  protected readonly graphs = computed(() =>
    (this.state()?.graphs?.length ? this.state()?.graphs ?? [] : ['Flux.2 Klein', 'Flux.1 Dev']).map((g) => ({
      value: g,
      label: g,
    })),
  );
  protected readonly schedulers = computed(() => {
    const labels = this.state()?.schedulers ?? [];
    return (labels.length ? labels : SCHEDULERS.map((s) => s.label)).map((label) => ({ value: label, label }));
  });
  protected readonly checkpoints = computed(() =>
    (this.state()?.checkpoints ?? ['Base 9B', 'Distilled 9B', 'SNOFS 9B']).map((label) => ({ value: label, label })),
  );

  constructor() {
    // A reply may carry a value older than the last keystroke. Drop a draft
    // only once the server's value is the one that was typed, so an unrelated
    // reply cannot pull the field back.
    effect(() => {
      const state = this.state();
      untracked(() => {
        const draft = this.draft();
        const keys = Object.keys(draft) as Knob[];
        if (!keys.length) return;
        const next = { ...draft };
        for (const key of keys) {
          if (String(state?.knobs?.[key] ?? '') === next[key]) delete next[key];
        }
        this.draft.set(next);
      });
    });
  }

  protected knobValue(key: Knob): string {
    return this.draft()[key] ?? String(this.state()?.knobs?.[key] ?? '');
  }

  protected setKnob(key: Knob, value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
    void this.store.act('settings', 'set_knobs', { [key]: value });
  }

  protected set(
    args: Record<string, unknown>,
    action: 'set_knobs' | 'select_checkpoint' | 'save' = 'set_knobs',
  ): void {
    void this.store.act('settings', action, args);
  }

  protected toggle(lora: LoraChoice, event: Event): void {
    const on = (event.target as HTMLInputElement).checked;
    void this.store.act('settings', 'toggle_lora', { id: lora.id, on });
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`settings.${action}`);
  }
}
