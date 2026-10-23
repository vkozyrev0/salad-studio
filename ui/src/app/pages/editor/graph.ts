import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';

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
      <svg [attr.viewBox]="viewBox()" [class.zoomed]="zoom() > 1" role="group" aria-label="Prompt graph" (wheel)="wheel($event)"
           (pointerdown)="startDrag($event)" (pointermove)="drag($event)"
           (pointerup)="endDrag()" (pointerleave)="endDrag()">
        @for (edge of paths(); track $index) {
          <path [attr.d]="edge" fill="none" stroke="var(--rule)" stroke-width="1.5" />
        }
        @for (node of laid(); track node.id) {
          <g
            class="node"
            [class.selected]="selected().includes(node.id)"
            [attr.transform]="'translate(' + node.rect?.x + ' ' + node.rect?.y + ')'"
            tabindex="0"
            role="button"
            [attr.aria-label]="node.title"
            [attr.aria-pressed]="selected().includes(node.id)"
            (click)="pickNode(node.id)"
            (keydown.enter)="pick.emit(node.id); $event.preventDefault()"
            (keydown.space)="pick.emit(node.id); $event.preventDefault()"
          >
            <rect class="card" [attr.width]="node.rect?.w" [attr.height]="node.rect?.h" rx="3" />
            <text class="title" x="10" y="19">{{ node.title }}</text>
            @for (port of node.ins; track port.key) {
              <circle [attr.cx]="0" [attr.cy]="port.y" [attr.r]="portR" [attr.fill]="'var(--info)'" />
              <text class="port" x="9" [attr.y]="port.y + 4">{{ port.name }}</text>
            }
            @for (port of node.outs; track port.key) {
              <circle [attr.cx]="node.rect?.w" [attr.cy]="port.y" [attr.r]="portR" [attr.fill]="'var(--valid)'" />
              <text class="port end" [attr.x]="(node.rect?.w ?? 0) - 9" [attr.y]="port.y + 4">{{ port.name }}</text>
            }
            @for (row of node.rows; track row.key; let i = $index) {
              <text class="row" x="10" [attr.y]="rowY(node, i)">{{ row.key }}: {{ row.value }}</text>
            }
            @if (node.note) {
              <text class="note" x="10" [attr.y]="rowY(node, node.rows?.length ?? 0)">{{ clip(node.note) }}</text>
            }
          </g>
        }
      </svg>
      <div class="zoom" role="group" aria-label="Graph zoom">
        <button type="button" (click)="zoomBy(1 / 1.5)" [disabled]="zoom() <= 1" aria-label="Zoom out">−</button>
        <button type="button" (click)="fit()" [disabled]="zoom() === 1">Fit</button>
        <button type="button" (click)="zoomBy(1.5)" [disabled]="zoom() >= MAX_ZOOM" aria-label="Zoom in">+</button>
      </div>
    }
  `,
  styles: `
    :host { display: block; position: relative; height: 100%; min-height: 0; }
    svg { display: block; width: 100%; height: 100%; background: var(--field); border: 1px solid var(--rule); border-radius: var(--radius-control); }
    svg.zoomed { cursor: grab; }
    svg.zoomed:active { cursor: grabbing; }
    .none { margin: 0; padding: 14px; color: var(--fg-muted); font-size: 12.5px; }
    .node { cursor: pointer; outline: none; }
    .card { fill: var(--surface); stroke: var(--rule); stroke-width: 1; }
    .node:hover .card { stroke: var(--fg-muted); }
    .node.selected .card { stroke: var(--accent); stroke-width: 2.5; }
    .node:focus-visible .card { stroke: var(--accent); stroke-width: 2; stroke-dasharray: 4 3; }
    .title { fill: var(--fg); font-family: var(--font-ui); font-size: 12px; font-weight: 600; }
    .port { fill: var(--fg-muted); font-family: var(--font-mono); font-size: 10px; }
    .port.end { text-anchor: end; }
    .row { fill: var(--fg-muted); font-family: var(--font-mono); font-size: 10px; }
    .note { fill: var(--fg); font-family: var(--font-ui); font-size: 10px; }
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

  protected readonly portR = PORT_R;
  protected readonly MAX_ZOOM = 4;
  protected readonly zoom = signal(1);
  protected readonly pan = signal({ x: 0, y: 0 });
  private dragStart: { x: number; y: number; panX: number; panY: number } | null = null;
  private dragged = false;
  private lastLayout = '';

  constructor() {
    // A new layout starts at the whole graph; a prompt edit that keeps the
    // same layout must not throw away the reader's zoom.
    effect(() => {
      const key = (this.graph()?.nodes ?? [])
        .map((node) => `${node.id}:${node.rect?.x},${node.rect?.y},${node.rect?.w},${node.rect?.h}`)
        .join('|');
      if (key === this.lastLayout) return;
      this.lastLayout = key;
      this.zoom.set(1);
      this.pan.set({ x: 0, y: 0 });
    });
  }

  /** The visible crop of the layout: the zoom, moved by a drag or the wheel. */
  protected readonly viewBox = computed(() => {
    const { w, h } = this.size();
    const zoom = this.zoom();
    const vw = w / zoom;
    const vh = h / zoom;
    const roomX = (w - vw) / 2;
    const roomY = (h - vh) / 2;
    const pan = this.pan();
    return `${roomX + clamp(pan.x, -roomX, roomX)} ${roomY + clamp(pan.y, -roomY, roomY)} ${vw} ${vh}`;
  });

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
    if (this.zoom() === 1 || event.button !== 0) return;
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

  protected readonly paths = () => {
    const byId = new Map(this.nodes().map((n) => [n.id, n]));
    return (this.graph()?.edges ?? []).flatMap((edge) => {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      if (!from?.rect || !to?.rect) return [];
      const cy = (p?: GraphPort) => p?.y ?? 0;
      const a = { x: from.rect.x + from.rect.w, y: from.rect.y + cy(from.ports?.find((p) => p.kind !== 'in')) };
      const b = { x: to.rect.x, y: to.rect.y + cy(to.ports?.find((p) => p.kind === 'in')) };
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
