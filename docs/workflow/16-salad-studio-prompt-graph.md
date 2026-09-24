# Salad Studio prompt-editor graph (HTML libraries + live JointJS)

> **Studio graph pane**, not eldermark. Code:
> [`salad_studio/graph_view.py`](../../salad_studio/graph_view.py).
> Helper README: [`salad_studio/README.md`](../../salad_studio/README.md).
> Klein groups: [`15-salad-flux2-klein-group.md`](15-salad-flux2-klein-group.md).

This file is the durable copy of the 2026-09-20 diagram-library
research, plus what we actually shipped afterward.

## Decision (2026-09-20)

**Stay on JointJS + tkwry** (user, 2026-09-20): do not rewrite Salad
Studio in Qt for NodeGraphQt. NodeGraphQt is the best Python-native
node editor, but it is a second GUI toolkit and does not manhattan-route
around cards. Live pane stays HTML JointJS in WebView2.

**Live graph is JointJS** (`@joint/core` 4.2.5), served as local HTML
under `salad_studio/graph_html/` and embedded with **tkwry**
(WebView2 child HWND). No Graphviz `dot` on the live path. tkinterweb
`HtmlFrame` cannot run Canvas2D / SVG diagram JS (PythonMonkey, not a
browser).

Python places cards with Comfy columns sized to the JointJS card (`prompt_to_joint`); unknown classes are not forced into the sampler column. JointJS draws
rounded dark cards, left/right ports, and **manhattan** orthogonal
wires with **rounded** corners that **route around other cards**.

| Piece | Where |
|---|---|
| Prompt → JointJS JSON | `prompt_to_joint` |
| HTML shell | `graph_html/viewer.html` + vendored `joint.min.js` |
| Pane | `GraphPane` → tkwry `WebView` (`app=_current.html`, `user_data_dir` under `%LOCALAPPDATA%\SaladStudio\WebView2`) |
| Fallback | **Open in browser** (same HTML). **Open as Comfy** = LiteGraph |
| Tests | `test_graph_view.py` class `JointGraphExport` |

LiteGraph.js (ComfyUI's editor) is also vendored. Spline links look
like Comfy; they do **not** pathfind around nodes — that is why it is
not the live pane.

Graphviz was the earlier approach. Its helpers (`prompt_to_dot`, `run_dot`,
`graphviz_layout`, `find_dot`, `parse_dot_plain`) and the grandalf layout
(`grandalf_resolve`, `resolve_layout`) have been **removed** from
`graph_view.py` — nothing on the shipped path called them. Do not require
`dot` to open Studio.

## HTML / JS libraries

These run in a **browser or WebView2**, not in Tk Canvas.

| Library | Comfy-like? | Smooth wires | Avoid node overlap | Embed notes |
|---|---|---|---|---|
| **JointJS** (`manhattan` + `rounded`) | Dark cards + L/R ports if we style them | Orthogonal with circular fillets | **Yes** — manhattan treats other elements as obstacles | One UMD file. **Live pick.** |
| **LiteGraph.js** | **Yes — ComfyUI's editor** | Bezier/spline | No; wires can cross cards (same as Comfy) | Vendored. **Open as Comfy** |
| **Drawflow** | HTML nodes, not Comfy cards | Curved SVG | No | Vanilla JS |
| **Rete.js** | Visual programming | Plugin renderers | No | Heavy, needs a renderer |
| **xyflow + SmartBezier / avoid-nodes-edge** | Customizable cards | Bezier or orthogonal | **Best “no intersection”** (libavoid WASM) | React, not a drop-in in Tk |
| **ELK.js** (`edgeRouting: SPLINES`, conservative) | Layout engine, we paint | Splines that hug a layered graph | Conservative mode routes around nodes; sloppy can clip | Needs a real JS engine; worker-based bundle is awkward in file:// |
| **nodegraph-js** | Dark cards, L/R slots | Bezier | Auto-arrange, not obstacle routing | Vanilla JS |
| **@gravity-ui/graph** | Node editor | Bezier | Canvas+HTML | Needs a bundler |
| **tkinterweb HtmlFrame** | Not a graph lib | — | — | HTML/CSS in Tk. JS is PythonMonkey — **cannot** run JointJS/LiteGraph |
| **tkwry (WebView2)** | Host for any JS graph | — | — | Real Edge in a Tk frame. **Live host.** |

**Why not LiteGraph as the pane:** it *is* the Comfy look, including
wires through boxes. The whole complaint was intersections.

**Why not xyflow:** best obstacle routing (`avoid-nodes-edge` / libavoid)
but it is a React app, not one script tag.

**Why not Graphviz:** `dot` is an extra binary; converting `-Tplain` back
to Tk looked worse than drawing in Tk. HTML JointJS keeps routing in the
library that paints the wires.

## What we needed

Comfy-style **left-to-right** cards, **side ports**, **smooth wires that
do not run through boxes**, and **field text that stays inside** the
card (`name` / `lora_name`).

No inspected Python widget already does all of that as a drop-in for
Tk Salad Studio.

## Survey (research)

| Stack | L→R cards + ports | Smooth ortho corners | Wires miss boxes | Text in box |
|---|---|---|---|---|
| **Graphviz `dot`** | Yes (`rankdir=LR`, record/HTML ports) | **Only stack with documented circular fillets**: `splines=ortho` + `radius>0` (Graphviz ≥14.1.0) | Hierarchical layout; `splines=true` routes around nodes. `splines=ortho` is **incomplete with ports** and can still clip shapes | Node **grows** to the label unless `fixedsize=true` (then it overflows). Wrap is manual (`<BR/>` / HTML table) |
| **grandalf** | Coordinates only (Sugiyama). Does not paint | Bézier (`route_with_splines`) or extra polyline points (`route_with_rounded_corners`) — **not** circular fillets | Clips polylines to the **endpoint** bbox; not an obstacle-avoiding router | No labels at all |
| **NodeGraphQt** | Real Qt node editor, L/R ports | Angled = sharp 90°; curved = cubic Bézier | Qt pipes, not libavoid | Title grows the card; no wrap/clip on `NodeTextItem` |
| **netext** | Terminal boxes + magnets | Orthogonal arrows | Sugiyama L→R | Terminal width |
| **Tk Canvas** | We paint cards | Polyline / Bézier / `joinstyle`; no ortho fillet router | Whatever we code | `create_text(width=)` wraps; otherwise as wide as the line |
| **ELK Layered / libavoid / yFiles** | Strong layout/routing | Orthogonal / octilinear | Best overlap control | Not a Tk widget |

**Python `graphviz` package** only writes DOT. Rendering still needs a
`dot` binary on PATH.

**Not a fit:** Nodezator (pygame app, not a library); NetworkX+Matplotlib
(no named side ports in inspected sources); rewriting Studio in Qt for
NodeGraphQt.

### Caveats (research)

- Graphviz “ports” are record/HTML fields or compass points (`:e`/`:w`),
  not Comfy circular sockets. Visual match is approximate.
- `radius` needs Graphviz **≥14.1.0** (2025-12-06). Older `dot` keeps
  sharp ortho corners.
- No engine is globally best at **both** node overlap and edge crossings;
  those are separate NP-hard stages.
- yFiles “few crossings” is a vendor claim for medium sparse graphs, not
  a zero-crossing guarantee.
- Ordinary Graphviz string labels do **not** auto-wrap.

## What we tried in Studio before Graphviz

1. **In-house Comfy columns + gutter polylines** — looked closest to
   Comfy (loaders → LoRA → CLIP → sampler). Wires still crossed cards
   unless gaps grew a lot. Chamfered corners, not circular fillets.
2. **grandalf Sugiyama as live placement** — scattered nodes (VAE to the
   top, decode to a far corner, huge loops). Rank-by-topology is not
   Comfy column order. Reverted; `grandalf_resolve` stayed in
   `graph_view.py` unused until the dead layout stack was deleted.

Both were abandoned, and the Graphviz/grandalf code is gone. Live path is
JointJS HTML, not Graphviz.

## What the Graphviz attempt used (now removed)

- **`splines=true`**, not `splines=ortho`. Ortho + ports is documented
  incomplete and was clipping cards. `true` routes around nodes.
- **HTML `<TABLE>` labels** so Graphviz **grows** the node around
  `name` / `lora_name` / CLIP text (`<BR/>` wrap). Tk then draws the
  same fields into that box.
- Compass `:e` → `:w` on edges (approximate side ports).
- **No `dot` dependency today.** The pane never invokes Graphviz — the live
  pane is JointJS HTML in WebView2 and the fallback is **Open in browser**
  (the same HTML). There is no install message and no `layout_xy` fallback
  because there is no `dot` path at all.

## Sources (survey)

- JointJS manhattan router + rounded connector — docs.jointjs.com
- LiteGraph.js — github.com/jagenjo/litegraph.js (ComfyUI editor)
- tkwry WebView2 embed — pypi.org/project/tkwry
- Graphviz `rankdir`, shapes, `splines`, `radius`, `fixedsize`, `dot` layout
  — graphviz.org docs
- Python graphviz user guide — graphviz.readthedocs.io
- NodeGraphQt README + `node_base.py` / `pipe.py`
- grandalf (`bdcht/grandalf`) `layouts.py` / `routing.py`
- netext (`mahrz24/netext`)
- ELK Layered — eclipse.dev/elk
- libavoid — adaptagrams.org
- yFiles Automatic Layouts
- Tkinter / Tcl canvas manuals
- This repo: `salad_studio/graph_view.py`
