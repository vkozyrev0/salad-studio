import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

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
 * from the keyboard. The page owns pan and zoom, which is one attribute on
 * the SVG.
 */
@Component({
  selector: 'app-graph',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!nodes().length) {
      <p class="none">No prompt graph.</p>
    } @else {
      <svg [attr.viewBox]="'0 0 ' + size().w + ' ' + size().h" role="group" aria-label="Prompt graph">
        @for (edge of paths(); track $index) {
          <path [attr.d]="edge" fill="none" stroke="var(--rule)" stroke-width="1.5" />
        }
        @for (node of laid(); track node.id) {
          <g
            class="node"
            [class.selected]="node.selected"
            [attr.transform]="'translate(' + node.rect?.x + ' ' + node.rect?.y + ')'"
            tabindex="0"
            role="button"
            [attr.aria-label]="node.title"
            [attr.aria-pressed]="!!node.selected"
            (click)="pick.emit(node.id)"
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
    }
  `,
  styles: `
    :host { display: block; height: 100%; min-height: 0; }
    svg { display: block; width: 100%; height: 100%; background: var(--field); border: 1px solid var(--rule); border-radius: var(--radius-control); }
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
  `,
})
export class Graph {
  readonly graph = input<GraphView | undefined>(undefined);
  readonly pick = output<string>();

  protected readonly portR = PORT_R;

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
