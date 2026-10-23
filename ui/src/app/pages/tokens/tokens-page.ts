import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';

type DotState = 'valid' | 'invalid' | 'unknown';

interface Slot {
  id: string;
  label: string;
  value: string;
  present: boolean;
  hint: string;
  state: DotState;
  tooltip: string;
}

interface TokensState {
  slots: Slot[];
}

/**
 * The provider keys, each with the state its last check answered.
 *
 * The key is a password until Show is pressed. Show is per slot and lives on
 * this component only: the server never learns which keys were revealed.
 *
 * Check is per slot too. One provider can hang for its whole timeout, and a
 * single check that probed all five would make the person wait for the slowest
 * one to learn about the key in front of them.
 */
@Component({
  selector: 'app-tokens-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame],
  template: `
    <app-page-frame>
      <form class="slots" (submit)="$event.preventDefault(); save()">
        @if (!slots().length) {
          @for (label of slotLabels; track label) {
            <div class="slot" aria-hidden="true">
              <span class="dot unknown"></span>
              <span class="name"><span class="word">{{ label }}</span></span>
              <div class="control"><input disabled placeholder="Loading…" /></div>
              <button class="btn ghost probe" type="button" disabled>Check</button>
            </div>
          }
        }
        @for (slot of slots(); track slot.id) {
          <div class="slot">
            <span class="dot" [class]="slot.state" [attr.title]="slot.tooltip" role="img" [attr.aria-label]="slot.label + ' key ' + slot.tooltip"></span>
            <span class="name">
              <label class="word" [attr.for]="'key-' + slot.id">{{ slot.label }}</label>
              <span class="state" [class]="slot.state">{{ slot.tooltip }}</span>
            </span>
            <div class="control">
              <input
                [id]="'key-' + slot.id"
                [type]="revealed().has(slot.id) ? 'text' : 'password'"
                [value]="draft()[slot.id] ?? ''"
                [placeholder]="slot.present ? slot.hint : 'not set'"
                (input)="edit(slot.id, $event)"
                autocomplete="off"
                spellcheck="false"
              />
              <button type="button" class="reveal" (click)="toggle(slot.id)" [attr.aria-pressed]="revealed().has(slot.id)">
                {{ revealed().has(slot.id) ? 'Hide' : 'Show' }}
              </button>
            </div>
            <button
              class="btn ghost probe"
              type="button"
              [disabled]="checking() !== null || busy('check_keys')"
              [attr.title]="'Ask ' + slot.label + ' whether the saved key is accepted'"
              (click)="checkOne(slot.id)"
            >
              @if (checking() === slot.id && busy('check_keys')) { <span class="spinner" aria-hidden="true"></span> }
              {{ checking() === slot.id && busy('check_keys') ? 'Checking' : 'Check' }}
            </button>
          </div>
        }
        <div class="foot">
          <button type="submit" class="btn primary" [disabled]="busy('save_key')">
            {{ busy('save_key') ? 'Saving' : 'Save keys' }}
          </button>
          <p class="hint">Check asks one provider whether its saved key is accepted. Save a typed key first.</p>
        </div>
      </form>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .slots { display: grid; gap: var(--space-sm); max-width: 900px; }
    .slot {
      display: grid;
      grid-template-columns: 14px 142px minmax(0, 1fr) auto;
      align-items: center;
      gap: var(--space-md);
    }
    .dot {
      width: 9px; height: 9px; border-radius: 50%;
      background: var(--unknown);
    }
    .dot.valid { background: var(--valid); box-shadow: 0 0 0 3px color-mix(in srgb, var(--valid) 16%, transparent); }
    .dot.invalid { background: var(--invalid); box-shadow: 0 0 0 3px color-mix(in srgb, var(--invalid) 16%, transparent); }
    .name { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .word { font-size: 13px; color: var(--fg); }
    .state {
      font-family: var(--font-mono);
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-muted);
    }
    .state.valid { color: var(--valid); }
    .state.invalid { color: var(--invalid); }
    .control { display: grid; grid-template-columns: minmax(0, 1fr) auto; }
    input {
      min-width: 0;
      height: 36px;
      padding: 0 10px;
      background: var(--field);
      border: 1px solid var(--rule);
      border-right: 0;
      border-radius: var(--radius-control) 0 0 var(--radius-control);
      color: var(--fg);
      font-family: var(--font-mono);
      font-size: 12.5px;
      box-shadow: inset 0 1px 0 rgb(0 0 0 / 0.35);
      transition: border-color 120ms ease, background 120ms ease;
    }
    input:hover { border-color: var(--fg-muted); }
    input:focus { outline: none; background: var(--bg); border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
    .reveal {
      height: 36px;
      padding: 0 12px;
      background: var(--surface);
      border: 1px solid var(--rule);
      border-radius: 0 var(--radius-control) var(--radius-control) 0;
      color: var(--fg-muted);
      font-family: var(--font-ui);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
    }
    .reveal:hover { color: var(--fg); border-color: var(--fg-muted); }
    .probe { height: 36px; min-width: 78px; }
    .foot { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: var(--space-sm); }
    .foot .hint { flex-basis: 100%; }
    @media (max-width: 760px) {
      .slot { grid-template-columns: 14px minmax(0, 1fr) auto; }
      .name { grid-column: 2; }
      .control { grid-column: 2; }
      .probe { grid-column: 3; grid-row: 2; }
    }
  `,
})
export class TokensPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as TokensState | null);
  protected readonly slots = computed(() => this.state()?.slots ?? []);
  /** The five labels to draw while the first reply is in flight. */
  protected readonly slotLabels = ['Salad', 'Hugging Face', 'Civitai', 'DeepSeek', 'Vast.ai'];

  /** Revealed slots and typed values live here only: the server never learns a reveal. */
  protected readonly revealed = signal(new Set<string>());
  protected readonly draft = signal<Record<string, string>>({});
  /** The slot whose check is in flight, so only its own row shows the spinner. */
  protected readonly checking = signal<string | null>(null);

  protected edit(id: string, event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.draft.set({ ...this.draft(), [id]: value });
  }

  protected toggle(id: string): void {
    const next = new Set(this.revealed());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.revealed.set(next);
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`tokens.${action}`);
  }

  protected save(): void {
    const values = Object.fromEntries(this.slots().map((s) => [s.id, this.draft()[s.id] ?? '']));
    void this.store.act('tokens', 'save_key', { values });
  }

  /** Check one provider's saved key, not all five. */
  protected checkOne(id: string): void {
    this.checking.set(id);
    void this.store.act('tokens', 'check_keys', { kinds: [id] });
  }
}
