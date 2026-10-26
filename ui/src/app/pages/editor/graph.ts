import {
  ApplicationRef,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  computed,
  DestroyRef,
  effect,
  inject,
  untracked,
  input,
  output,
  signal,
} from '@angular/core';

export interface GraphPort {
  key: string;
  name: string;
  kind: 'in' | 'out' | string;
  y: number;
}

export interface GraphNode {
  id: string;
  title?: string;
  rect?: { x: number; y: number; w: number; h: number };
  ports?: GraphPort[];
  rows?: { key: string; value: string }[];
  note?: string;
  selected?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  source_key?: string;
  target_key?: string;
}

export interface GraphView {
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

const HEADER = 30;
const BODY_PAD = 10;
const ROW_H = 26;
const PORT_R = 4.5;

/**
 * The prompt graph, drawn from the server's node positions.
 *
 * One card per node: a title band, the input ports down the left, the output
 * ports down the right, then the widget rows and the prompt note. A click
 * picks or drops a card; Enter and Space do the same so the graph is usable
 * from the keyboard. A wheel or the three buttons zoom around the centre, so
 * a dense layout can be read; Fit returns to the whole graph.
 */
@Component({
  selector: 'app-graph',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!nodes().length) {
      <p class="none">No prompt graph.</p>
    } @else {
      <svg [attr.viewBox]="viewBox()" role="group" aria-label="Prompt graph" (wheel)="wheel($event)"
           (pointerdown)="startDrag($event)" (pointermove)="drag($event)"
           (pointerup)="endDrag()" (pointerleave)="endDrag()">
        @for (edge of paths(); track $index) {
          <path [attr.d]="edge" fill="none" stroke="var(--rule)" stroke-width="1.5" />
        }
        @for (edge of litPaths(); track $index) {
          <path [attr.d]="edge" fill="none" stroke="var(--accent)" stroke-width="2" pointer-events="none" />
        }
        @for (node of laid(); track node.id) {
          <g
            class="node"
            [class.selected]="selected().includes(node.id)"
            [attr.transform]="'translate(' + node.rect?.x + ' ' + node.rect?.y + ')'"
            [class.dim]="dimmed(node.id)"
            tabindex="0"
            role="button"
            [attr.aria-label]="node.title"
            [attr.aria-pressed]="selected().includes(node.id)"
            (click)="pickNode(node.id)"
            (keydown.enter)="pick.emit(node.id); $event.preventDefault()"
            (keydown.space)="pick.emit(node.id); $event.preventDefault()"
          >
            <rect class="card" [attr.width]="node.rect?.w" [attr.height]="node.rect?.h" rx="3" />
            <text class="title" x="10" y="19" [attr.font-size]="textSize()">{{ node.title }}</text>
            @for (port of node.ins; track port.key) {
              <circle [attr.cx]="0" [attr.cy]="port.y" [attr.r]="portR" [attr.fill]="'var(--info)'" />
              <text class="port" x="9" [attr.y]="port.y + 4" [attr.font-size]="smallSize()">{{ port.name }}</text>
            }
            @for (port of node.outs; track port.key) {
              <circle [attr.cx]="node.rect?.w" [attr.cy]="port.y" [attr.r]="portR" [attr.fill]="'var(--valid)'" />
              <text class="port end" [attr.x]="(node.rect?.w ?? 0) - 9" [attr.y]="port.y + 4" [attr.font-size]="smallSize()">{{ port.name }}</text>
            }
            @for (row of node.rows; track row.key; let i = $index) {
              <text class="row" x="10" [attr.y]="rowY(node, i)" [attr.font-size]="smallSize()">{{ row.key }}: {{ row.value }}</text>
            }
            @if (node.note) {
              <text class="note" x="10" [attr.y]="rowY(node, node.rows?.length ?? 0)" [attr.font-size]="smallSize()">{{ clip(node.note) }}</text>
            }
          </g>
        }
      </svg>
      <div class="zoom" role="group" aria-label="Graph zoom">
        <button type="button" (click)="zoomBy(1 / 1.5)" [disabled]="zoom() <= 1" aria-label="Zoom out">−</button>
        <button type="button" class="fit" (click)="fit()" [disabled]="zoom() === 1" [attr.title]="'Showing the whole graph, drawn at ' + percent() + '. Click to fit again'">{{ percent() }}</button>
        <button type="button" (click)="zoomBy(1.5)" [disabled]="zoom() >= MAX_ZOOM" aria-label="Zoom in">+</button>
      </div>
    }
  `,
  styles: `
    :host { display: block; position: relative; height: 100%; min-height: 0; }
    svg { display: block; width: 100%; height: 100%; background: var(--field); border: 1px solid var(--rule); border-radius: var(--radius-control); }
    svg { cursor: grab; }
    svg:active { cursor: grabbing; }
    .none { margin: 0; padding: 14px; color: var(--fg-muted); font-size: 12.5px; }
    .node { cursor: pointer; outline: none; }
    .card { fill: var(--surface); stroke: var(--rule); stroke-width: 1; }
    .node:hover .card { stroke: var(--fg-muted); }
    .node.selected .card { stroke: var(--accent); stroke-width: 2.5; }
    .node:focus-visible .card { stroke: var(--accent); stroke-width: 2; stroke-dasharray: 4 3; }
    /* A pick dims what it does not connect to, so a wire can be followed from
       end to end instead of read off a tangle. */
    .node.dim { opacity: 0.3; }
    .zoom .fit { min-width: 44px; }
    .title { fill: var(--fg); font-family: var(--font-ui); font-weight: 600; }
    .port { fill: var(--fg-muted); font-family: var(--font-mono); }
    .port.end { text-anchor: end; }
    .row { fill: var(--fg-muted); font-family: var(--font-mono); }
    .note { fill: var(--fg); font-family: var(--font-ui); }
    .zoom {
      position: absolute; top: 8px; right: 8px;
      display: inline-flex; align-items: center; gap: 1px;
      padding: 2px;
      background: var(--surface);
      border: 1px solid var(--rule);
      border-radius: var(--radius-control);
      box-shadow: 0 2px 8px rgb(0 0 0 / 0.3);
    }
    .zoom button {
      height: 24px; min-width: 26px; padding: 0 6px;
      border: 0; border-radius: 2px; background: none; color: var(--fg-muted);
      font-family: var(--font-mono); font-size: 11px; cursor: pointer;
    }
    .zoom button:hover:not(:disabled) { background: var(--wash); color: var(--fg); }
    .zoom button:disabled { opacity: 0.35; cursor: default; }
  `,
})
export class Graph {
  readonly graph = input<GraphView | undefined>(undefined);
  /** The page's own pick pair, so a click paints before the server replies. */
  readonly selected = input<readonly string[]>([]);
  readonly pick = output<string>();

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly app = inject(ApplicationRef);
  private watch: ResizeObserver | null = null;
  private watchCleanup: (() => void) | null = null;

  protected readonly portR = PORT_R;
  /**
   * A fit that lands near 30% leaves a port label at six screen pixels, which
   * is unreadable. Four steps of 1.5 reach 5x, where that label is back to its
   * own size and a card's title has room to be read.
   */
  protected readonly MAX_ZOOM = 5;
  protected readonly zoom = signal(1);
  /**
   * The pane's drawn size. A signal written from a template binding moves the
   * viewBox on the next render, which this zoneless page never gets on its own.
   */
  private readonly box = signal({ w: 0, h: 0 });
  protected readonly pan = signal({ x: 0, y: 0 });
  private dragStart: { x: number; y: number; panX: number; panY: number } | null = null;
  private dragged = false;
  private lastLayout = '';

  constructor() {
    // The pane's box is read after every render. It is zero on the frame this
    // component first draws and real on the next, so the graph is redrawn once
    // it has a size; the same hook answers a later resize.
    // The hook's ref comes back before its callback runs, so the observer it
    // tears down already exists. Registering on the injected `DestroyRef` from
    // the callback is too late: by then that reference is torn down, and
    // registering on it throws on every hop off this page.
    const render = afterNextRender({
      write: () => {
        this.watch = new ResizeObserver(() => this.measurePane());
        this.watch.observe(this.host.nativeElement);
        this.measurePane();
      },
    });
    this.watchCleanup = () => render.destroy();
    // A new layout starts at the whole graph; a prompt edit that keeps the
    // same layout must not throw away the reader's zoom.
    effect(() => {
      const key = this.layoutKey();
      if (key === this.lastLayout) return;
      this.lastLayout = key;
      this.zoom.set(1);
      this.pan.set({ x: 0, y: 0 });
    });
    // Registered up front, where the reference is alive; the callback only
    // runs if the component is destroyed after the hook returned.
    inject(DestroyRef).onDestroy(() => this.watchCleanup?.());
  }

  /**
   * The crop the pane shows. At a zoom of 1 the whole layout fills the pane,
   * whichever of the two is the tighter fit; above that the crop is one
   * zoomth of the pane, moved by a drag or the wheel and held inside the graph.
   */
  protected readonly viewBox = computed(() => {
    const { w, h } = this.size();
    const pane = this.pane();
    const fit = Math.min(pane.w / w, pane.h / h);
    const view = { x: -((pane.w / fit - w) / 2), y: -((pane.h / fit - h) / 2), w: pane.w / fit, h: pane.h / fit };
    const zoom = this.zoom();
    const vw = view.w / zoom;
    const vh = view.h / zoom;
    const roomX = (view.w - vw) / 2;
    const roomY = (view.h - vh) / 2;
    const pan = this.pan();
    return `${view.x + roomX + clamp(pan.x, -roomX, roomX)} ${view.y + roomY + clamp(pan.y, -roomY, roomY)} ${vw} ${vh}`;
  });

  /** The crop's unit scale: text drawn at 1/scale keeps one size on screen. */
  private readonly unit = computed(() => {
    const { w, h } = this.size();
    const pane = this.pane();
    return Math.min(pane.w / w, pane.h / h) * this.zoom();
  });

  protected readonly textSize = computed(() => Math.min(28, Math.max(11, 11 / this.unit())));
  protected readonly smallSize = computed(() => Math.min(24, Math.max(9, 9.5 / this.unit())));

  /** The share of life size the drawn graph is at, for the zoom readout. */
  protected readonly percent = computed(() => {
    const { w, h } = this.size();
    const pane = this.pane();
    const share = Math.min(pane.w / w, pane.h / h) * this.zoom();
    return `${Math.round(share * 100)}%`;
  });

  /** Take the pane's box, once per change, so the crop follows the layout. */
  measurePane(): void {
    const r = this.host.nativeElement.getBoundingClientRect();
    const next = { w: Math.max(1, Math.round(r.width)), h: Math.max(1, Math.round(r.height)) };
    const now = this.box();
    if (now.w !== next.w || now.h !== next.h) this.box.set(next);
  }

  private pane(): { w: number; h: number } {
    const box = this.box();
    return box.w > 0 ? box : { w: 800, h: 500 };
  }

  protected readonly picked = computed(() => {
    const ids = new Set(this.selected());
    if (!ids.size) return null;
    const edges = this.graph()?.edges ?? [];
    const reach = new Set(ids);
    for (const edge of edges) {
      const touches = ids.has(edge.source) || ids.has(edge.target);
      if (touches) {
        reach.add(edge.source);
        reach.add(edge.target);
      }
    }
    return { ids, reach };
  });

  /** Which wires run from a picked card, or into one. */
  protected readonly litPaths = computed(() => {
    const lit = this.picked();
    if (!lit) return [];
    return this.paths((edge) => lit.reach.has(edge.source) && lit.reach.has(edge.target)
      && (lit.ids.has(edge.source) || lit.ids.has(edge.target)));
  });

  /** A card that is not one picked and not wired to one steps back. */
  protected dimmed(id: string): boolean {
    const lit = this.picked();
    return !!lit && !lit.reach.has(id);
  }

  protected zoomBy(factor: number): void {
    const next = Math.min(this.MAX_ZOOM, Math.max(1, this.zoom() * factor));
    this.zoom.set(next);
    if (next === 1) this.pan.set({ x: 0, y: 0 });
  }

  protected fit(): void {
    this.zoom.set(1);
    this.pan.set({ x: 0, y: 0 });
  }

  /** Zoom around the pointer, so a wheel can walk into the node being read. */
  protected wheel(event: WheelEvent): void {
    event.preventDefault();
    const svg = event.currentTarget as SVGSVGElement;
    const box = svg.getBoundingClientRect();
    const { w, h } = this.size();
    const before = this.zoom();
    const after = Math.min(this.MAX_ZOOM, Math.max(1, before * (event.deltaY < 0 ? 1.2 : 1 / 1.2)));
    if (after === before) return;
    const vw = w / before;
    const vh = h / before;
    const roomX = (w - vw) / 2;
    const roomY = (h - vh) / 2;
    const pan = this.pan();
    const px = roomX + pan.x + ((event.clientX - box.left) / box.width) * vw;
    const py = roomY + pan.y + ((event.clientY - box.top) / box.height) * vh;
    const nvw = w / after;
    const nvh = h / after;
    const next = {
      x: px - ((event.clientX - box.left) / box.width) * nvw - (w - nvw) / 2,
      y: py - ((event.clientY - box.top) / box.height) * nvh - (h - nvh) / 2,
    };
    this.zoom.set(after);
    this.pan.set(next);
  }

  protected startDrag(event: PointerEvent): void {
    if (event.button !== 0) return;
    this.dragged = false;
    this.dragStart = { x: event.clientX, y: event.clientY, panX: this.pan().x, panY: this.pan().y };
    (event.currentTarget as SVGSVGElement).setPointerCapture(event.pointerId);
  }

  protected drag(event: PointerEvent): void {
    if (!this.dragStart) return;
    const svg = event.currentTarget as SVGSVGElement;
    const box = svg.getBoundingClientRect();
    const { w, h } = this.size();
    const zoom = this.zoom();
    const dx = ((event.clientX - this.dragStart.x) / box.width) * (w / zoom);
    const dy = ((event.clientY - this.dragStart.y) / box.height) * (h / zoom);
    if (Math.abs(dx) + Math.abs(dy) > 3) this.dragged = true;
    this.pan.set({ x: this.dragStart.panX - dx, y: this.dragStart.panY - dy });
  }

  protected endDrag(): void {
    this.dragStart = null;
  }

  /** A drag that pans must not also pick the card it started on. */
  protected pickNode(id: string): void {
    if (this.dragged) {
      this.dragged = false;
      return;
    }
    this.pick.emit(id);
  }

  protected readonly nodes = () => this.graph()?.nodes ?? [];

  /** A card's position and size, joined: the same string means the same drawing. */
  private readonly layoutKey = computed(() =>
    this.nodes()
      .map((node) => `${node.id}:${node.rect?.x},${node.rect?.y},${node.rect?.w},${node.rect?.h}`)
      .join('|'),
  );

  /** The extents of the layout, with room for the card edges and a port's radius. */
  protected readonly size = () => {
    let w = 480;
    let h = 320;
    for (const node of this.nodes()) {
      const rect = node.rect;
      if (!rect) continue;
      w = Math.max(w, rect.x + rect.w + 32);
      h = Math.max(h, rect.y + rect.h + 32);
    }
    return { w, h };
  };

  protected readonly laid = () =>
    this.nodes().map((node) => ({
      ...node,
      ins: (node.ports ?? []).filter((p) => p.kind === 'in'),
      outs: (node.ports ?? []).filter((p) => p.kind !== 'in'),
    }));

  /** Wires, each on its own port: a card's second input is not its first. */
  protected readonly paths = (keep: (edge: GraphEdge) => boolean = () => true) => {
    const byId = new Map(this.nodes().map((n) => [n.id, n]));
    return (this.graph()?.edges ?? []).filter(keep).flatMap((edge) => {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      if (!from?.rect || !to?.rect) return [];
      const cy = (p?: GraphPort) => p?.y ?? 0;
      const a = { x: from.rect.x + from.rect.w, y: from.rect.y + cy(from.ports?.find((p) => p.key === edge.source_key)) };
      const b = { x: to.rect.x, y: to.rect.y + cy(to.ports?.find((p) => p.key === edge.target_key)) };
      const bend = Math.max(24, (b.x - a.x) / 2);
      return [`M${a.x} ${a.y} C${a.x + bend} ${a.y} ${b.x - bend} ${b.y} ${b.x} ${b.y}`];
    });
  };

  protected rowY(node: GraphNode, index: number): number {
    return HEADER + BODY_PAD + index * ROW_H;
  }

  protected clip(text: string): string {
    const one = text.replace(/\s+/g, ' ').trim();
    return one.length > 60 ? one.slice(0, 59) + '…' : one;
  }
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}
