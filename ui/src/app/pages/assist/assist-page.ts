import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { Field, checked } from '../../shared/field';
import { DEFAULT_LOCAL_URL } from '../../shared/catalogs';

interface AssistState {
  localUrl?: string;
  local_url?: string;
  sendImage?: boolean;
  send_image?: boolean;
  imageNote?: string;
  issue?: string;
  positive?: string;
  negative?: string;
  reply?: string;
  status?: { text?: string; level?: string };
}

/**
 * Prompt Assist: ask for a prompt fix, then commit it to the editor.
 *
 * The edited boxes ride on Help and Commit, so the server reads exactly what
 * is on screen when either is pressed. Help is one background round trip;
 * both buttons share its busy key, so a second ask cannot start over it.
 */
@Component({
  selector: 'app-assist-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field],
  template: `
    <app-page-frame>
      <div class="scroll">
        <div class="url">
          <app-field label="Local LLM URL" [value]="edited().localUrl" [w]="420" [mono]="true" (changed)="edit({ localUrl: $event })" />
          <label class="check">
            <input type="checkbox" [checked]="edited().sendImage" (change)="image($event)" />
            Send the latest generated image
          </label>
        </div>
        <p class="hint">{{ state()?.imageNote || 'off, no image is sent' }}</p>

        <app-field label="Image issue / problem" kind="textarea" [rows]="2" [value]="edited().issue" (changed)="edit({ issue: $event })" />
        <app-field label="Adjusted positive prompt" kind="textarea" [rows]="2" [value]="edited().positive" (changed)="edit({ positive: $event })" />
        <app-field label="Adjusted negative prompt" kind="textarea" [rows]="2" [value]="edited().negative" (changed)="edit({ negative: $event })" />

        <div class="btn-row">
          <button class="btn ghost" type="button" [disabled]="helping()" (click)="help('deepseek')">
            @if (helping()) { <span class="spinner" aria-hidden="true"></span> }
            {{ helping() ? 'Asking' : 'Help (DeepSeek)' }}
          </button>
          <button class="btn ghost" type="button" [disabled]="helping()" (click)="help('local')">Help (local)</button>
          <button class="btn primary" type="button" [disabled]="busy('commit')" (click)="commit()">
            {{ busy('commit') ? 'Committing' : 'Commit to Prompts + JSON' }}
          </button>
        </div>

        <p class="state" [class.error]="status().level === 'error'" [class.ok]="status().level === 'ok'" role="status">{{ status().text }}</p>

        <section class="reply" aria-labelledby="reply-head">
          <h2 class="eyebrow" id="reply-head">Reply</h2>
          <pre class="readout prose" tabindex="0">{{ state()?.reply || '' }}</pre>
        </section>
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .scroll { display: flex; flex-direction: column; gap: 8px; height: 100%; min-height: 0; padding-top: 12px; overflow: auto; }
    .url { display: flex; align-items: flex-end; gap: 16px; flex-wrap: wrap; }
    .hint { margin: -4px 0 4px; }
    .state { margin: 4px 0 0; min-height: 18px; font-size: 12px; color: var(--fg-muted); }
    .state.ok { color: var(--valid); }
    .state.error { color: var(--invalid); }
    .reply { display: grid; grid-template-rows: auto minmax(120px, 1fr); min-height: 160px; }
    .reply h2 { margin: 0 0 6px; }
    .readout { min-height: 120px; white-space: pre-wrap; }
  `,
})
export class AssistPage {
  private readonly store = inject(StudioStore);

  protected readonly state = computed(() => this.store.page() as AssistState | null);
  protected readonly status = computed(() => this.state()?.status ?? {});

  /** The boxes as typed, until the next reply replaces them. */
  private readonly draft = signal<Partial<AssistState> | null>(null);
  protected readonly edited = computed(() => ({
    localUrl: this.draft()?.localUrl ?? this.state()?.localUrl ?? this.state()?.local_url ?? DEFAULT_LOCAL_URL,
    sendImage: this.draft()?.sendImage ?? this.state()?.sendImage ?? this.state()?.send_image ?? false,
    issue: this.draft()?.issue ?? this.state()?.issue ?? '',
    positive: this.draft()?.positive ?? this.state()?.positive ?? '',
    negative: this.draft()?.negative ?? this.state()?.negative ?? '',
  }));

  constructor() {
    effect(() => {
      this.store.page();
      untracked(() => this.draft.set(null));
    });
  }

  protected helping(): boolean {
    return this.store.inFlight().has('assist.help');
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`assist.${action}`);
  }

  protected image(event: Event): void {
    this.edit({ sendImage: checked(event) });
  }

  protected edit(patch: Partial<AssistState>): void {
    this.draft.set({ ...this.edited(), ...patch });
  }

  protected help(backend: 'deepseek' | 'local'): void {
    void this.store.act('assist', 'help', { backend, edited: this.edited() });
  }

  protected commit(): void {
    void this.store.act('assist', 'commit', { edited: this.edited() });
  }
}
