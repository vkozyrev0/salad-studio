import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';

type DotState = 'valid' | 'invalid' | 'unknown';

interface Slot {
  id: string;
  label: string;
  value: string;
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
 */
@Component({
  selector: 'app-tokens-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame],
  template: `
    <app-page-frame>
      <form class="slots" (submit)="$event.preventDefault(); save()">
        @for (slot of slots(); track slot.id) {
          <div class="slot">
            <span class="dot" [class]="slot.state" [attr.title]="slot.tooltip" role="img" [attr.aria-label]="slot.tooltip"></span>
            <label class="name" [attr.for]="'key-' + slot.id">{{ slot.label }}</label>
            <div class="control">
              <input
                [id]="'key-' + slot.id"
                [type]="revealed().has(slot.id) ? 'text' : 'password'"
                [value]="draft()[slot.id] ?? slot.value"
                (input)="edit(slot.id, $event)"
                autocomplete="off"
                spellcheck="false"
              />
              <button type="button" class="ghost" (click)="toggle(slot.id)" [attr.aria-pressed]="revealed().has(slot.id)">
                {{ revealed().has(slot.id) ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
        }
        <div class="foot">
          <button type="submit" class="primary" [disabled]="busy('save_key')">
            {{ busy('save_key') ? 'Saving' : 'Save keys' }}
          </button>
          <button type="button" class="quiet" [disabled]="busy('check_keys')" (click)="check()">
            {{ busy('check_keys') ? 'Checking' : 'Check keys' }}
          </button>
          <span class="hint">Check keys asks each provider whether the key is accepted.</span>
        </div>
      </form>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .slots { display: grid; gap: var(--space-sm); max-width: 760px; }
    .slot {
      display: grid;
      grid-template-columns: 14px 116px minmax(0, 1fr);
      align-items: center;
      gap: var(--space-md);
    }
    .dot {
      width: 9px; height: 9px; border-radius: 50%;
      background: var(--unknown);
    }
    .dot.valid { background: var(--valid); box-shadow: 0 0 0 3px rgb(143 191 154 / 0.16); }
    .dot.invalid { background: var(--invalid); box-shadow: 0 0 0 3px rgb(212 138 154 / 0.16); }
    .name { font-size: 13px; color: var(--fg); }
    .control { display: grid; grid-template-columns: minmax(0, 1fr) auto; }
    input {
      min-width: 0;
      padding: 8px 10px;
      background: var(--well);
      border: 1px solid var(--border);
      border-right: 0;
      border-radius: var(--radius-control) 0 0 var(--radius-control);
      color: var(--fg);
      font-family: var(--font-mono);
      font-size: 12.5px;
      transition: border-color 120ms ease, background 120ms ease;
    }
    input:hover { border-color: var(--fg-muted); }
    input:focus { outline: none; background: var(--bg); border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
    .ghost {
      padding: 0 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 0 var(--radius-control) var(--radius-control) 0;
      color: var(--fg-muted);
      font-size: 12px;
      cursor: pointer;
    }
    .ghost:hover { color: var(--fg); border-color: var(--fg-muted); }
    .foot { display: flex; align-items: baseline; gap: var(--space-sm); margin-top: var(--space-md); }
    .primary {
      padding: 7px 16px;
      background: var(--accent);
      border: 1px solid var(--accent);
      border-radius: var(--radius-control);
      color: var(--accent-fg);
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
    }
    .primary:disabled { opacity: 0.6; cursor: progress; }
    .quiet {
      padding: 7px 14px;
      background: transparent;
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      color: var(--fg);
      font-size: 13px;
      cursor: pointer;
    }
    .quiet:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
    .quiet:disabled { opacity: 0.6; cursor: progress; }
    .hint { margin-left: auto; font-size: 12px; color: var(--fg-muted); }
  `,
})
export class TokensPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as TokensState | null);
  protected readonly slots = computed(() => this.state()?.slots ?? []);

  /** Revealed slots and typed values live here only: the server never learns a reveal. */
  protected readonly revealed = signal(new Set<string>());
  protected readonly draft = signal<Record<string, string>>({});

  constructor() {
    void this.store.load('tokens');
  }

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
    const values = Object.fromEntries(this.slots().map((s) => [s.id, this.draft()[s.id] ?? s.value]));
    void this.store.act('tokens', 'save_key', { values });
  }

  protected check(): void {
    void this.store.act('tokens', 'check_keys');
  }
}
