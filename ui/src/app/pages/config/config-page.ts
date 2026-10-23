import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { ColDef } from 'ag-grid-community';
import { StudioStore } from '../../core/studio-store';
import { PageFrame } from '../../shell/page-frame';
import { DataGrid, numeric } from '../../shared/data-grid';
import { Selection } from '../../shared/selection';
import { Field, checked } from '../../shared/field';
import { PROBE_KEYS, PROBE_LABELS, PROBE_WIDTHS, ProbeKey } from '../../shared/catalogs';

interface Section {
  id: string;
  label: string;
}

interface Mode {
  id: string;
  label: string;
}

interface Checkpoint {
  name: string;
  selected?: boolean;
}

interface ProfileState {
  profiles?: string[];
  name?: string;
  gateway?: string;
  label?: string;
  modes?: Mode[];
  mode?: string;
  checkpoints?: Checkpoint[];
  selected_checkpoint?: string | null;
  checkpoints_editable?: boolean;
  serves?: string;
}

interface PolicyState {
  group?: string;
  group_name?: string;
  version?: number | string | null;
  image?: string;
  us_only?: boolean;
  gpus?: { id: string; name: string; selected?: boolean }[];
  probes?: Record<'startup' | 'readiness', Partial<Record<ProbeKey, string>>>;
  open?: boolean;
}

interface Instance {
  key: string;
  label?: string;
  endpoint?: string;
  image?: string;
  state?: string;
  gpu?: string;
  active?: boolean;
  selected?: boolean;
}

interface Offer {
  id?: string;
  cells?: string[];
}

interface VastState {
  instances?: Instance[];
  selected_instance?: string | null;
  gpus?: string;
  floors?: string;
  offers?: (Offer | string[])[];
}

/**
 * The Images section's state. The controller has not written this block yet,
 * so every read below is real, but the key names are this page's guess at the
 * shape the inventory describes (tags, environment rows, a dry run).
 */
interface ImagesState {
  tags?: string[];
  image?: string;
  show_tokens?: boolean;
  env?: { name: string; value: string; editable?: boolean; note?: string }[];
  script?: string;
  own_image?: { name?: string; tag?: string; build_arg?: string; context?: string };
}

interface ConfigState {
  section?: string;
  sections?: Section[];
  profile?: ProfileState;
  images?: ImagesState;
  policy?: PolicyState;
  vast?: VastState;
}

const PROBE_KINDS = ['startup', 'readiness'] as const;

/**
 * Config: the profile, its images, the Salad group policy and the vast.ai hosts.
 *
 * The four sections are one page, and each action carries only its own
 * section's fields, so a save on Profile cannot write a half-edited policy.
 * The checkpoint list is a pick, not a table; the two vast.ai tables are grids
 * whose selection goes to the server by key or by position, as each names it.
 */
@Component({
  selector: 'app-config-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageFrame, Field, DataGrid],
  template: `
    <app-page-frame>
      <div class="tabs" role="tablist" aria-label="Config sections" (keydown)="tabKey($event)">
        @for (tab of sections(); track tab.id) {
          <button
            class="tab"
            type="button"
            role="tab"
            [attr.tabindex]="section() === tab.id ? 0 : -1"
            [id]="'tab-' + tab.id"
            [attr.aria-selected]="section() === tab.id"
            [attr.aria-controls]="'panel-' + tab.id"
            [disabled]="unported(tab.id)"
            [attr.title]="unported(tab.id) ? 'The server does not send this section yet.' : null"
            (click)="section.set(tab.id)"
          >
            {{ tab.label }}
          </button>
        }
      </div>

      <div class="body" role="tabpanel" [id]="'panel-' + section()" [attr.aria-labelledby]="'tab-' + section()">
        @switch (section()) {
          @case ('profile') {
            <p class="empty-line">Provider keys live on Tokens. Paste them there before the first render.</p>
            <div class="cols">
              <section class="main" aria-labelledby="profiles-head">
                <div class="section" role="group" aria-labelledby="profiles-head">
                  <div class="section-head">
                    <h2 class="eyebrow" id="profiles-head">Profiles</h2>
                    <span class="section-meta">{{ profile().profiles?.length ?? 0 }} saved</span>
                  </div>
                  <div class="rows">
                    <app-field
                      label="Active profile"
                      kind="select"
                      [value]="profile().name ?? ''"
                      [options]="profileOptions()"
                      [w]="220"
                      (changed)="loadProfile($event)"
                    />
                    <app-field label="Profile name" [value]="name()" [w]="220" (changed)="name.set($event)" />
                  </div>
                  <div class="btn-row">
                    <button class="btn ghost" type="button" [disabled]="busy('add_profile')" (click)="profileAct('add_profile')">Add profile</button>
                    <button class="btn primary" type="button" [disabled]="busy('save_profile')" (click)="profileAct('save_profile')">
                      @if (busy('save_profile')) { <span class="spinner" aria-hidden="true"></span> }
                      Save profile
                    </button>
                    <button class="btn danger push" type="button" [disabled]="busy('delete_profile')" (click)="profileAct('delete_profile')">Delete profile</button>
                  </div>
                  @if (profile().serves) { <p class="hint">{{ profile().serves }}</p> }
                </div>

                <div class="section" role="group" aria-labelledby="target-head">
                  <div class="section-head">
                    <h2 class="eyebrow" id="target-head">Target</h2>
                    <span class="section-meta">{{ modeLabel() }}</span>
                  </div>
                  <span class="field-label" id="target-label">Connection</span>
                  <div class="seg" role="group" aria-labelledby="target-label">
                    @for (mode of profile().modes ?? [] ; track mode.id) {
                      <button type="button" [attr.aria-pressed]="(profile().mode ?? 'salad') === mode.id" (click)="setMode(mode.id)">{{ mode.label }}</button>
                    }
                  </div>
                  <div class="rows url">
                    <app-field
                      [label]="profile().mode === 'vast' ? 'Instance URL' : 'Gateway URL'"
                      [value]="gateway()"
                      [w]="420"
                      [mono]="true"
                      (changed)="gateway.set($event)"
                    />
                    <button class="btn ghost" type="button" [disabled]="busy('use_selected_instance')" (click)="profileAct('use_selected_instance')">Use the selected instance</button>
                  </div>
                </div>

                <div class="section" role="group" aria-labelledby="checkpoints-head">
                  <div class="section-head">
                    <h2 class="eyebrow" id="checkpoints-head">Checkpoints this profile serves</h2>
                  </div>
                  @if (profile().checkpoints?.length) {
                    <ol class="pick-list" aria-label="Checkpoints, the first is primary">
                      @for (checkpoint of profile().checkpoints ?? []; track checkpoint.name) {
                        <li>
                          <button
                            class="pick-row"
                            type="button"
                            [attr.aria-current]="profile().selected_checkpoint === checkpoint.name"
                            (click)="selectCheckpoint(checkpoint.name)"
                          >
                            <span class="what mono">{{ checkpoint.name }}</span>
                            @if ($first) { <span class="eyebrow">Primary</span> }
                          </button>
                        </li>
                      }
                    </ol>
                  } @else {
                    <p class="empty-line">(none)</p>
                  }
                  <div class="btn-row">
                    <app-field label="Checkpoint filename or label" [value]="checkpointText()" [w]="420" (changed)="checkpointText.set($event)" [enter]="true" (submitted)="addCheckpoint()" />
                    <button class="btn ghost" type="button" [disabled]="!profile().checkpoints_editable || busy('add_checkpoint')" (click)="addCheckpoint()">Add</button>
                    <button class="btn ghost" type="button" [disabled]="!profile().selected_checkpoint || busy('remove_checkpoint')" (click)="removeCheckpoint()">Remove selected</button>
                  </div>
                </div>
              </section>

              <aside class="aside" aria-label="Active target">
                <span class="eyebrow">Active target</span>
                <p class="name">{{ profile().name || 'No profile' }}</p>
                <dl class="stats">
                  <div><dt>Mode</dt><dd>{{ modeLabel() }}</dd></div>
                  <div><dt>Checkpoints</dt><dd>{{ profile().checkpoints?.length ?? 0 }}</dd></div>
                  <div class="wide">
                    <dt>Gateway</dt>
                    <dd class="url" [attr.title]="gateway() || 'No gateway set'">{{ gateway() || 'No gateway set' }}</dd>
                  </div>
                </dl>
              </aside>
            </div>
          }

          @case ('images') {
            @if (unported('images')) {
              <p class="empty-line">The server does not send the Images section yet, so there is nothing to show here.</p>
            } @else {
            <section class="main" aria-labelledby="images-head">
              <div class="section" role="group" aria-labelledby="images-head">
                <div class="section-head"><h2 class="eyebrow" id="images-head">Container images</h2></div>
                <div class="rows">
                  <app-field label="Image" kind="select" [value]="imageTag()" [options]="imageTags()" [id]="'config-image'" [w]="380" (changed)="pickImage($event)" />
                  <label class="check">
                    <input type="checkbox" [checked]="images().show_tokens ?? false" (change)="showTokens($event)" />
                    show token values
                  </label>
                </div>
              </div>

              <div class="section" role="group" aria-labelledby="env-head">
                <div class="section-head"><h2 class="eyebrow" id="env-head">Environment</h2></div>
                @if (images().env?.length) {
                  <ul class="pick-list" aria-label="Environment">
                    @for (row of images().env ?? []; track row.name) {
                      <li class="env-row">
                        <span class="mono mono-line">{{ row.name }}={{ row.value }}</span>
                        @if (row.note) { <span class="hint">{{ row.note }}</span> }
                      </li>
                    }
                  </ul>
                } @else {
                  <p class="empty-line">(no entries)</p>
                }
                <div class="btn-row">
                  <app-field label="NAME" [value]="envName()" [w]="220" [mono]="true" (changed)="envName.set($event)" />
                  <app-field label="value" [value]="envValue()" [w]="320" kind="password" [mono]="true" (changed)="envValue.set($event)" />
                  <button class="btn ghost" type="button" [disabled]="busy('add_env')" (click)="set({ name: envName(), value: envValue() }, 'add_env')">Add env</button>
                  <button class="btn ghost" type="button" [disabled]="busy('remove_env')" (click)="set({ name: envName() }, 'remove_env')">Remove selected</button>
                  <button class="btn primary" type="button" [disabled]="busy('save_env')" (click)="set({}, 'save_env')">Save environment</button>
                </div>
              </div>

              <div class="section" role="group" aria-labelledby="deploy-head">
                <div class="section-head"><h2 class="eyebrow" id="deploy-head">Deploy</h2></div>
                <pre class="readout" tabindex="0">{{ images().script || '(no image selected)' }}</pre>
                <div class="btn-row">
                  <button class="btn ghost" type="button" (click)="copyCommands()">Copy commands</button>
                </div>
                <details class="own">
                  <summary class="eyebrow">Your own image</summary>
                  <div class="rows">
                    <app-field label="Name" [value]="images().own_image?.name ?? ''" [w]="160" [readonly]="true" />
                    <app-field label="Tag" [value]="images().own_image?.tag ?? ''" [w]="280" [readonly]="true" [mono]="true" />
                    <app-field label="Build arg" [value]="images().own_image?.build_arg ?? ''" [w]="300" [readonly]="true" [mono]="true" />
                    <app-field label="Context" [value]="images().own_image?.context ?? ''" [w]="200" [readonly]="true" [mono]="true" />
                  </div>
                </details>
              </div>
            </section>
            }
          }

          @case ('policy') {
            <section class="main" aria-labelledby="policy-head">
              <div class="section" role="group" aria-labelledby="policy-head">
                <div class="section-head">
                  <h2 class="eyebrow" id="policy-head">Salad group for this profile</h2>
                  <span class="section-meta">{{ policyGroup() }}</span>
                </div>
                <div class="rows">
                  <app-field label="Image" [id]="'policy-image'" [value]="policy().image ?? ''" [w]="420" [mono]="true" (changed)="policySet({ image: $event })" />
                  <label class="check">
                    <input type="checkbox" [checked]="policy().us_only ?? false" (change)="usOnly($event)" />
                    US-only
                  </label>
                </div>
                @if (policy().gpus?.length) {
                  <fieldset class="gpus">
                    <legend class="field-label">GPU classes</legend>
                    @for (gpu of policy().gpus ?? []; track gpu.id) {
                      <label class="check">
                        <input type="checkbox" [checked]="gpu.selected ?? false" (change)="toggleGpu(gpu.id, $event)" />
                        {{ gpu.name }}
                      </label>
                    }
                  </fieldset>
                } @else {
                  <p class="hint">(press Load from Salad for the classes)</p>
                }
              </div>

              <div class="section" aria-labelledby="probes-head">
                <h2 class="eyebrow" id="probes-head">Probes</h2>
                @for (kind of probeKinds; track kind) {
                  <div class="probe">
                    <span class="probe-kind">{{ kind === 'startup' ? 'Startup' : 'Readiness' }}</span>
                    @for (key of probeKeys; track key) {
                      <app-field [label]="probeLabel(key)" [value]="probe(kind, key)" [w]="probeWidth(key)" [mono]="true" (changed)="probeSet(kind, key, $event)" />
                    }
                  </div>
                }
              </div>

              <div class="btn-row">
                <button class="btn ghost" type="button" [disabled]="busy('load_policy')" (click)="set({}, 'load_policy')">
                  @if (busy('load_policy')) { <span class="spinner" aria-hidden="true"></span> }
                  Load from Salad
                </button>
                <button class="btn primary" type="button" [disabled]="busy('apply_policy')" (click)="set({}, 'apply_policy')">
                  @if (busy('apply_policy')) { <span class="spinner" aria-hidden="true"></span> }
                  Apply to Salad
                </button>
                <button class="btn danger" type="button" [disabled]="busy('reallocate')" (click)="set({}, 'reallocate')">Reallocate instance</button>
              </div>
            </section>
          }

          @case ('vast') {
            <section class="main" aria-labelledby="vast-head">
              <div class="section" role="group" aria-labelledby="vast-head">
                <div class="section-head"><h2 class="eyebrow" id="vast-head">vast.ai instances</h2></div>
                <div class="table short">
                  @if (instances().length || store.loading() || store.loadError()) {
                    <app-data-grid [rows]="instances()" [columns]="instanceColumns" field="key" [selected]="instanceKey()" (picked)="pickInstance($event)" />
                  } @else {
                    <p class="empty-line">(no instances)</p>
                  }
                </div>
                <div class="btn-row">
                  <app-field label="Instance URL or id" [value]="vastEndpoint()" [w]="420" [mono]="true" (changed)="vastEndpoint.set($event)" />
                  <button class="btn ghost" type="button" [disabled]="busy('add_vast')" (click)="vastAct('add_vast')">Add instance</button>
                  <button class="btn ghost" type="button" [disabled]="busy('fetch_vast')" (click)="vastAct('fetch_vast')">
                    @if (busy('fetch_vast')) { <span class="spinner" aria-hidden="true"></span> }
                    Fetch instances
                  </button>
                  <button class="btn ghost" type="button" [disabled]="!instanceKey()" (click)="vastAct('set_vast_image')">Set image</button>
                  <button class="btn ghost" type="button" [disabled]="!instanceKey()" (click)="vastAct('make_profile_for_vast')">New profile for instance</button>
                  <button class="btn danger" type="button" [disabled]="!instanceKey()" (click)="vastAct('remove_vast')">Remove</button>
                  <button class="btn primary" type="button" [disabled]="busy('save_vast')" (click)="vastAct('save_vast')">Save list</button>
                </div>
              </div>

              <div class="section" role="group" aria-labelledby="rent-head">
                <div class="section-head"><h2 class="eyebrow" id="rent-head">Rent a machine</h2></div>
                <div class="btn-row">
                  <app-field label="GPU models" [value]="vastGpus()" [w]="300" (changed)="vastGpus.set($event)" />
                  <button class="btn ghost" type="button" [disabled]="busy('search_offers')" (click)="vastAct('search_offers')">
                    @if (busy('search_offers')) { <span class="spinner" aria-hidden="true"></span> }
                    Find offers
                  </button>
                  <button class="btn danger" type="button" [disabled]="!offerId()" (click)="vastAct('rent_offer')">Create instance</button>
                  <button class="btn ghost" type="button" [disabled]="busy('replace_destroyed')" (click)="vastAct('replace_destroyed')">Replace if destroyed</button>
                </div>
                <p class="hint mono">Floors: {{ vast().floors }}</p>
                <div class="table tall">
                  @if (offers().length || store.loading() || store.loadError()) {
                    <app-data-grid [rows]="offers()" [columns]="offerColumns" field="id" [selected]="offerId()" (picked)="pickOffer($event)" />
                  } @else {
                    <p class="empty-line">(Find offers)</p>
                  }
                </div>
              </div>
            </section>
          }
        }
      </div>
    </app-page-frame>
  `,
  styles: `
    :host { display: block; height: 100%; }
    .tabs { display: flex; flex-wrap: wrap; gap: 26px; margin-top: 6px; border-bottom: 1px solid var(--rule); }
    .tab {
      position: relative;
      height: 38px;
      padding: 0 1px;
      border: 0;
      background: none;
      color: var(--fg-muted);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
    }
    .tab:hover { color: var(--fg); }
    .tab[aria-selected='true'] { color: var(--fg); }
    .tab[aria-selected='true']::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--accent); }
    .body { min-height: 0; height: calc(100% - 45px); padding-top: 16px; overflow: auto; }
    .cols { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 30px; align-items: start; }
    .main { display: flex; flex-direction: column; gap: 22px; max-width: 1180px; padding-bottom: 16px; }
    .rows { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; }
    .rows.url { margin-top: 14px; }
    .push { margin-left: auto; }
    .aside { position: sticky; top: 0; padding: 16px; border: 1px solid var(--rule); border-radius: var(--radius-card); background: var(--surface); }
    .aside .name { margin: 10px 0 0; font-family: var(--font-display); font-size: 21px; overflow-wrap: anywhere; }
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; margin: 14px 0 0; padding-top: 12px; border-top: 1px solid var(--hairline); }
    .stats .wide { grid-column: 1 / -1; min-width: 0; }
    .stats dt { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.11em; text-transform: uppercase; color: var(--fg-muted); }
    .stats dd { margin: 2px 0 0; font-family: var(--font-mono); font-size: 11.5px; }
    .stats .url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--fg); }
    .env-row { display: flex; align-items: baseline; gap: 10px; padding: 6px 8px; border-bottom: 1px solid var(--hairline); }
    .own { margin-top: 14px; }
    .own summary { cursor: pointer; }
    .own .rows { margin-top: 10px; }
    .gpus { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 12px 0 0; padding: 0; border: 0; }
    .gpus legend { margin-bottom: 6px; }
    /* The seven probe fields add up to less than the pane at 1440px, and wrap
       on one line each rather than scrolling sideways below that. */
    .probe { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px; margin-top: 10px; }
    .probe-kind { flex: none; width: 80px; padding-bottom: 10px; font-size: 12px; color: var(--fg-muted); }
    .table { border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .table.short { height: 190px; }
    .table.tall { height: 300px; }
    @media (max-width: 1080px) { .cols { grid-template-columns: minmax(0, 1fr); } }
  `,
})
export class ConfigPage {
  protected readonly store = inject(StudioStore);
  private readonly offerSelection = new Selection();
  private readonly instanceSelection = new Selection();

  protected readonly state = computed(() => this.store.page() as ConfigState | null);
  protected readonly profile = computed(() => this.state()?.profile ?? {});
  protected readonly images = computed(() => this.state()?.images ?? {});
  protected readonly policy = computed(() => this.state()?.policy ?? {});
  protected readonly vast = computed(() => this.state()?.vast ?? {});
  protected readonly instances = computed(() => this.vast().instances ?? []);
  protected readonly offers = computed(() =>
    (this.vast().offers ?? []).map((offer, index) => {
      const cells = Array.isArray(offer) ? offer : offer.cells ?? [];
      const id = Array.isArray(offer) ? String(index) : String(offer.id ?? index);
      return Object.fromEntries([['id', id], ...cells.map((text, i) => [`c${i}`, text])]) as Record<string, string>;
    }),
  );
  protected readonly probeKinds = PROBE_KINDS;
  protected readonly probeKeys = PROBE_KEYS;
  protected probeLabel(key: ProbeKey): string {
    return PROBE_LABELS[key];
  }
  protected probeWidth(key: ProbeKey): number {
    return PROBE_WIDTHS[key];
  }

  /** The open tab is the page's; the reply's section is the start. */
  protected readonly section = signal<string>('profile');

  /** The Profile section's typed fields, until a reply replaces the form. */
  protected readonly name = signal('');
  protected readonly gateway = signal('');
  protected readonly checkpointText = signal('');
  protected readonly envName = signal('');
  protected readonly envValue = signal('');
  protected readonly vastEndpoint = signal('');
  protected readonly vastGpus = signal('');
  protected readonly offerSelectionRev = signal(0);
  private readonly drafts = signal<Record<string, string>>({});

  protected readonly sections = computed<Section[]>(
    () =>
      this.state()?.sections ?? [
        { id: 'profile', label: 'Profile' },
        { id: 'images', label: 'Images' },
        { id: 'policy', label: 'Salad group' },
        { id: 'vast', label: 'Vast.ai' },
      ],
  );
  protected readonly profileOptions = computed(() => (this.profile().profiles ?? []).map((p) => ({ value: p, label: p })));
  protected readonly imageTags = computed(() => (this.images().tags ?? []).map((t) => ({ value: t, label: t })));
  /** "name  v3" from the server's one string, or built from the two facts. */
  protected readonly policyGroup = computed(() => {
    const policy = this.policy();
    if (policy.group) return policy.group;
    if (!policy.group_name) return '';
    return `${policy.group_name}  v${policy.version ?? '?'}`;
  });
  protected readonly modeLabel = computed(() => {
    const mode = this.profile().mode ?? 'salad';
    return (this.profile().modes ?? []).find((m) => m.id === mode)?.label ?? mode;
  });

  protected readonly instanceColumns: ColDef[] = [
    { headerName: 'Key', field: 'key', start: 110, filter: false, tooltipField: 'key' },
    { headerName: 'Label', field: 'label', start: 140, tooltipField: 'label' },
    { headerName: 'Address', field: 'endpoint', start: 200, cellStyle: { 'font-family': 'var(--font-mono)', 'font-size': '11.5px' } },
    { headerName: 'Image', field: 'image', start: 160 },
    { headerName: 'State', field: 'state', start: 100 },
    { headerName: 'GPU', field: 'gpu', start: 110 },
    {
      headerName: 'Active',
      field: 'active',
      start: 70,
      filter: false,
      valueFormatter: (p) => (p.value ? '*' : ''),
    },
  ];

  protected readonly offerColumns: ColDef[] = [
    { headerName: 'GPU', field: 'c0', start: 150 },
    numeric('$/hr', 'c1', 90),
    numeric('Perf', 'c2', 90),
    numeric('Perf/$', 'c3', 80),
    numeric('VRAM GB', 'c4', 90),
    numeric('Disk GB', 'c5', 90),
  ];

  constructor() {
    effect(() => {
      const state = this.state();
      untracked(() => {
        if (state?.section) this.section.set(state.section);
        const instance = this.instances().find((row) => row.selected);
        if (instance) this.instanceSelection.pick(instance.key);
        this.offerSelection.pick(null);
        this.offerSelectionRev.update((n) => n + 1);
        this.drafts.set({});
        this.name.set(state?.profile?.name ?? '');
        this.gateway.set(state?.profile?.gateway ?? '');
        this.vastEndpoint.set('');
        if (!this.vastGpus()) this.vastGpus.set(state?.vast?.gpus ?? 'RTX 5090, RTX 4090');
      });
    });
  }

  /** The instance the actions that need one act on: the page's pick, or the one the server selected. */
  protected instanceKey(): string | null {
    return this.instanceSelection.key() ?? this.instances().find((row) => row.selected)?.key ?? null;
  }

  protected offerId(): string | null {
    this.offerSelectionRev();
    return this.offerSelection.key();
  }

  protected busy(action: string): boolean {
    return this.store.inFlight().has(`config.${action}`);
  }

  /** A section the reply leaves out cannot be opened; its controls would all be empty. */
  protected unported(id: string): boolean {
    return id === 'images' && this.state()?.images === undefined;
  }

  /** Left and Right walk the tabs, as the ARIA tabs pattern expects. */
  protected tabKey(event: KeyboardEvent): void {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    const tabs = this.sections().filter((tab) => !this.unported(tab.id));
    const at = tabs.findIndex((t) => t.id === this.section());
    const next = tabs[(Math.max(0, at) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    if (!next || next.id === this.section()) return;
    event.preventDefault();
    this.section.set(next.id);
    (event.currentTarget as HTMLElement | null)?.querySelector<HTMLElement>(`#tab-${next.id}`)?.focus();
  }

  // -- Profile

  protected loadProfile(name: string): void {
    this.name.set(name);
    void this.store.act('config', 'load_profile', { name });
  }

  protected profileAct(action: 'add_profile' | 'save_profile' | 'delete_profile' | 'use_selected_instance'): void {
    if (action === 'use_selected_instance') {
      void this.store.act('config', action);
      return;
    }
    void this.store.act('config', action, { name: this.name(), gateway: this.gateway() });
  }

  protected setMode(mode: string): void {
    void this.store.act('config', 'set_mode', { mode });
  }

  protected selectCheckpoint(name: string): void {
    void this.store.act('config', 'select_checkpoint', { name });
  }

  protected addCheckpoint(): void {
    const text = this.checkpointText().trim();
    if (!text) return;
    this.checkpointText.set('');
    void this.store.act('config', 'add_checkpoint', { text });
  }

  protected removeCheckpoint(): void {
    const name = this.profile().selected_checkpoint;
    if (name) void this.store.act('config', 'remove_checkpoint', { name });
  }

  // -- Images

  protected imageTag(): string {
    return this.drafts()['image'] ?? this.images().image ?? this.images().tags?.[0] ?? '';
  }

  protected pickImage(tag: string): void {
    this.drafts.update((d) => ({ ...d, image: tag }));
    void this.store.act('config', 'set_env_image', { image: tag });
  }

  /** Reveal is asked for on every toggle, so a reload goes back to masked rows. */
  protected showTokens(event: Event): void {
    void this.store.act('config', 'set_env_image', { show_tokens: checked(event) });
  }

  protected copyCommands(): void {
    void navigator.clipboard?.writeText(this.images().script ?? '').catch(() => undefined);
  }

  // -- Salad group

  protected probe(kind: 'startup' | 'readiness', key: ProbeKey): string {
    return this.drafts()[`${kind}.${key}`] ?? String(this.policy().probes?.[kind]?.[key] ?? '');
  }

  protected probeSet(kind: 'startup' | 'readiness', key: ProbeKey, value: string): void {
    this.policySet({ probes: { [kind]: { [key]: value } } });
  }

  protected policySet(patch: Record<string, unknown>): void {
    const probes = patch['probes'] as Record<string, Record<string, string>> | undefined;
    if (probes) {
      this.drafts.update((d) => {
        const next = { ...d };
        for (const [kind, keys] of Object.entries(probes)) for (const [key, value] of Object.entries(keys)) next[`${kind}.${key}`] = value;
        return next;
      });
    } else if (typeof patch['image'] === 'string') {
      this.drafts.update((d) => ({ ...d, image: patch['image'] as string }));
    }
    void this.store.act('config', 'set_policy', patch);
  }

  protected usOnly(event: Event): void {
    this.policySet({ us_only: checked(event) });
  }

  protected toggleGpu(id: string, event: Event): void {
    const on = checked(event);
    const ids = (this.policy().gpus ?? []).filter((g) => (g.id === id ? on : g.selected)).map((g) => g.id);
    void this.store.act('config', 'set_policy', { gpu_classes: ids });
  }

  protected set(args: Record<string, string>, action: 'add_env' | 'remove_env' | 'save_env' | 'load_policy' | 'apply_policy' | 'reallocate'): void {
    void this.store.act('config', action, args);
    if (action === 'add_env') {
      this.envName.set('');
      this.envValue.set('');
    }
  }

  // -- Vast.ai

  protected pickInstance(key: string): void {
    this.instanceSelection.pick(key);
    const index = this.instances().findIndex((row) => row.key === key);
    if (index >= 0) void this.store.act('config', 'select_vast', { index });
  }

  protected pickOffer(id: string): void {
    this.offerSelection.pick(id);
    this.offerSelectionRev.update((n) => n + 1);
    const index = this.offers().findIndex((row) => row['id'] === id);
    if (index >= 0) void this.store.act('config', 'select_offer', { index });
  }

  protected vastAct(action: 'add_vast' | 'fetch_vast' | 'set_vast_image' | 'make_profile_for_vast' | 'remove_vast' | 'save_vast' | 'search_offers' | 'rent_offer' | 'replace_destroyed'): void {
    void this.store.act('config', action, {
      key: this.instanceKey(),
      endpoint: this.vastEndpoint(),
      image: this.imageTag(),
      gpus: this.vastGpus(),
      offer: this.offerId(),
    });
  }
}
