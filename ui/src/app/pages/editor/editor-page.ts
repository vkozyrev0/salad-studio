import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { Field } from '../../shared/field';
import { Graph, GraphNode, GraphView } from './graph';

interface EditorState {
  json?: string;
  positive?: string;
  negative?: string;
  status?: { text?: string; level?: string };
  errors?: string[];
  graph?: GraphView;
  rev?: number;
}

const JSON_DEBOUNCE_MS = 300;
const PROMPT_DEBOUNCE_MS = 200;

/**
 * Prompt Editor: the request JSON, the graph it draws, and the two prompts.
 *
 * The server owns the JSON and its revision. The boxes keep a draft while it
 * differs from the reply, post it after a short pause with the revision it was
 * typed into, and then take the reply again: a late keystroke cannot overwrite
 * an Import that landed first. Graph clicks are the page's selection; the
 * two selected cards are what Swap exchanges.
 */
@Component({
  selector: 'app-editor-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field, Graph],
  template: `
    <app-page-frame>
      <div class="wrap">
        <div class="split">
          <app-field class="json" label="Request JSON" kind="textarea" [value]="json()" [mono]="true" [rows]="14" (changed)="typeJson($event)" />
          <app-graph [graph]="graph()" [selected]="selection()" (pick)="toggle($event)" />
        </div>

        <div class="prompts">
          <app-field label="Positive prompt" kind="textarea" [value]="positive()" [rows]="3" (changed)="typePrompt('pos', $event)" />
          <app-field label="Negative prompt" kind="textarea" [value]="negative()" [rows]="3" (changed)="typePrompt('neg', $event)" />
        </div>

        <div class="bar">
          <button class="btn ghost" type="button" [disabled]="busy('rebuild_from_config')" (click)="act('rebuild_from_config')">
            @if (busy('rebuild_from_config')) { <span class="spinner" aria-hidden="true"></span> }
            Rebuild from Config
          </button>
          <button class="btn ghost" type="button" [disabled]="busy('rebuild_from_json')" (click)="act('rebuild_from_json')">Rebuild from JSON</button>
          <button class="btn key" type="button" [disabled]="busy('validate')" (click)="act('validate')">Validate</button>
          <p class="status" [class.ok]="status().level === 'ok'" [class.error]="status().level === 'error'" [class.warn]="status().level === 'warn'" role="status">
            {{ status().text }}
          </p>
          <button class="btn quiet" type="button" [disabled]="!selection().length" (click)="selection.set([])">Clear selection</button>
          <button class="btn ghost" type="button" [disabled]="selection().length !== 2 || busy('swap_selected')" (click)="swap()">
            @if (busy('swap_selected')) { <span class="spinner" aria-hidden="true"></span> }
            Swap selected
          </button>
        </div>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .wrap { display: grid; grid-template-rows: minmax(0, 3fr) auto auto; gap: 8px; height: 100%; min-height: 0; padding-top: 12px; }
    .split { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 8px; min-height: 0; }
    /* The JSON box fills its column; its row count is a floor, not a height. */
    .json { height: 100%; min-height: 0; }
    .json ::ng-deep .field { height: 100%; width: 100%; }
    .json { display: flex; flex-direction: column; min-width: 0; }
    .json ::ng-deep .field { flex: 1; min-height: 0; }
    .json ::ng-deep textarea { flex: 1; min-height: 0; resize: none; }
    .prompts { display: grid; grid-template-columns: minmax(0, 66fr) minmax(0, 34fr); gap: 8px; }
    .bar { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
    .status { margin: 0; min-width: 12ch; font-size: 12px; color: var(--fg-muted); white-space: pre-line; }
    .status.ok { color: var(--valid); }
    .status.error { color: var(--invalid); }
    .status.warn { color: var(--warn); }
    @media (max-width: 900px) {
      .wrap { overflow: auto; }
      .split, .prompts { grid-template-columns: minmax(0, 1fr); }
    }
  `,
})
export class EditorPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as EditorState | null);
  protected readonly graph = computed(() => this.state()?.graph);
  protected readonly status = computed(() => this.state()?.status ?? {});
  protected readonly selection = signal<string[]>([]);

  /** A draft is shown only while it differs from the reply it was typed against. */
  private readonly drafts = signal<Record<string, string>>({});
  private timers: Record<string, ReturnType<typeof setTimeout>> = {};

  protected readonly json = computed(() => this.pick('json', this.state()?.json ?? ''));
  protected readonly positive = computed(() => this.pick('pos', this.state()?.positive ?? ''));
  protected readonly negative = computed(() => this.pick('neg', this.state()?.negative ?? ''));

  constructor() {
    effect(() => {
      const rev = this.state()?.rev;
      const graph = this.graph();
      untracked(() => {
        this.drafts.set({});
        if (rev === undefined) return;
        const kept = this.selection().filter((id) => graph?.nodes?.some((n: GraphNode) => n.id === id));
        if (kept.length !== this.selection().length) this.selection.set(kept);
      });
    });
  }

  protected typeJson(text: string): void {
    this.drafts.update((d) => ({ ...d, json: text }));
    this.after('json', JSON_DEBOUNCE_MS, () => {
      void this.store.act('editor', 'set_json', { text, base: this.state()?.rev ?? 0 });
    });
  }

  protected typePrompt(which: 'pos' | 'neg', text: string): void {
    this.drafts.update((d) => ({ ...d, [which]: text }));
    this.after(which, PROMPT_DEBOUNCE_MS, () => {
      void this.store.act('editor', 'set_prompt', {
        positive: this.positive(),
        negative: this.negative(),
      });
    });
  }

  protected toggle(id: string): void {
    const current = this.selection();
    // Two cards at most, as a swap takes a pair; a third pick drops the oldest.
    if (current.includes(id)) this.selection.set(current.filter((x) => x !== id));
    else this.selection.set([...current, id].slice(-2));
  }

  protected swap(): void {
    void this.store.act('editor', 'swap_selected', { ids: this.selection() });
    this.selection.set([]);
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`editor.${action}`);
  }

  protected act(action: 'rebuild_from_config' | 'rebuild_from_json' | 'validate'): void {
    void this.store.act('editor', action);
  }

  private pick(key: string, reply: string): string {
    const draft = this.drafts()[key];
    return draft !== undefined && draft !== reply ? draft : reply;
  }

  private after(key: string, ms: number, run: () => void): void {
    clearTimeout(this.timers[key]);
    this.timers[key] = setTimeout(() => {
      delete this.timers[key];
      run();
    }, ms);
  }
}
