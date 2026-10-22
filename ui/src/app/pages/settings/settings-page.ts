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
  { key: 'width', label: 'Width', w: 120 },
  { key: 'height', label: 'Height', w: 120 },
  { key: 'steps', label: 'Steps', w: 120 },
  { key: 'cfg', label: 'CFG', w: 120 },
  { key: 'seed', label: 'Seed', w: 160 },
];

/**
 * Prompt Settings: the knobs a request carries, and the LoRAs it selects.
 *
 * Every change writes the window's form at once, so the editor and Generate
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
              [label]="knob.label"
              [value]="knobValue(knob.key)"
              [w]="knob.w"
              [inputMode]="'decimal'"
              (changed)="setKnob(knob.key, $event)"
            />
          }
          <app-field label="Graph" kind="select" [value]="state()?.graph ?? ''" [options]="graphs()" [w]="220" (changed)="set({ graph: $event })" />
          <app-field label="Scheduler" [id]="'settings-scheduler'" kind="select" [value]="state()?.scheduler ?? 'Flux2 (Klein)'" [options]="schedulers()" [w]="220" (changed)="set({ scheduler: $event })" />
          <app-field label="Checkpoint" [id]="'settings-checkpoint'" kind="select" [value]="state()?.checkpoint ?? ''" [options]="checkpoints()" [w]="220" (changed)="set({ checkpoint: $event }, 'select_checkpoint')" />

          <div class="save">
            <button class="btn primary" type="button" [disabled]="busy('save')" (click)="set({}, 'save')">
              @if (busy('save')) { <span class="spinner" aria-hidden="true"></span> }
              {{ busy('save') ? 'Saving' : 'Save to profile' }}
            </button>
          </div>
        </div>

        <section class="loras" aria-labelledby="loras-head">
          <h2 class="eyebrow" id="loras-head">LoRAs</h2>
          @if (loras().length) {
            <div class="choices">
              @for (lora of loras(); track lora.id) {
                <label class="check">
                  <input type="checkbox" [checked]="lora.selected" (change)="toggle(lora, $event)" />
                  <span>{{ lora.label }}</span>
                </label>
              }
            </div>
          } @else {
            <p class="hint">No LoRAs for this graph.</p>
          }
        </section>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .split { display: grid; grid-template-columns: 248px minmax(0, 1fr); gap: 32px; height: 100%; min-height: 0; padding-top: 14px; }
    /* Only the knobs column scrolls, and its own scrollbar sits outside the
       fields so a 220px field is not narrowed by it. */
    .knobs { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 12px; }
    .save { margin-top: 6px; }
    .loras { min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 12px; border-left: 1px solid var(--hairline); }
    .loras h2 { margin: 0 0 12px; }
    .choices { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 6px 20px; align-content: start; }
    /* Below this width the LoRA list would end up narrower than a name, so the
       two columns stack and each scrolls inside the pane. */
    @media (max-width: 1040px) {
      .split { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); gap: 16px; overflow-y: auto; }
      .knobs { overflow: visible; flex-direction: row; flex-wrap: wrap; align-items: flex-end; }
      .loras { border-left: 0; padding-left: 0; }
    }
  `,
})
export class SettingsPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as SettingsState | null);
  protected readonly loras = computed(() => this.state()?.loras ?? []);
  protected readonly knobs = KNOBS;

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
    // Every reply is the form, so once it lands the boxes take its values.
    // The effect watches the reply's identity, so a background progress reply
    // that did not change this page does not wipe a half-typed number.
    effect(() => {
      this.store.page();
      untracked(() => this.draft.set({}));
    });
  }

  protected knobValue(key: Knob): string {
    return this.draft()[key] ?? String(this.state()?.knobs?.[key] ?? '');
  }

  protected setKnob(key: Knob, value: string): void {
    this.draft.update((d) => ({ ...d, [key]: value }));
    void this.store.act('settings', 'set_form', { [key]: value });
  }

  protected set(
    args: Record<string, unknown>,
    action: 'set_form' | 'select_checkpoint' | 'save' = 'set_form',
  ): void {
    void this.store.act('settings', action, args);
  }

  protected toggle(lora: LoraChoice, event: Event): void {
    const on = (event.target as HTMLInputElement).checked;
    void this.store.act('settings', 'set_form', { loras: { [lora.id]: on } });
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`settings.${action}`);
  }
}
