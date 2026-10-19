# Salad Studio prompt graph decision (2026-10-17)

*Consolidated from `docs/workflow/16-salad-studio-prompt-graph.md` on
2026-10-17. This file is the durable copy; `salad_studio/README.md` keeps the
pane summary.*

> **Studio graph pane**, not eldermark. Code:
> [`graph_model.py`](../../salad_studio/graph_model.py), drawn by
> [`graph_canvas.py`](../../salad_studio/graph_canvas.py).
> Klein groups: [`15-salad-flux2-klein-group.md`](../workflow/15-salad-flux2-klein-group.md).

This file records the 2026-09-20 diagram-library research, plus what shipped
afterward.

## Decision (2026-09-20)

**Stay on JointJS + tkwry** (user, 2026-09-20): do not rewrite Salad Studio in
Qt for NodeGraphQt. NodeGraphQt is the best Python-native node editor, but it is
a second GUI toolkit and does not manhattan-route around cards. The live pane
stays HTML JointJS in WebView2.

**The live graph is JointJS** (`@joint/core` 4.2.5), served as local HTML under
`salad_studio/graph_html/` and embedded with **tkwry** (WebView2 child HWND). No
Graphviz `dot` on the live path. tkinterweb `HtmlFrame` cannot run Canvas2D or
SVG diagram JS (PythonMonkey, not a browser).

Python places cards with Comfy columns sized to the JointJS card
(`prompt_to_joint`); unknown classes are not forced into the sampler column.
JointJS draws rounded dark cards, left and right ports, and **manhattan**
orthogonal wires with **rounded** corners that **route around other cards**.
The requirement was Comfy-style left-to-right cards, side ports, wires that do
not run through boxes, and **field text that stays inside** the card (`name`,
`lora_name`); no inspected Python widget is a drop-in for Tk Salad Studio.

| Piece | Where |
|---|---|
| Prompt to JointJS JSON | `prompt_to_joint` |
| HTML shell | `graph_html/viewer.html` + vendored `joint.min.js` |
| Pane | `GraphPane` to tkwry `WebView` (`app=_current.html`, `user_data_dir` under `%LOCALAPPDATA%\SaladStudio\WebView2`) |
| Fallback | **Open in browser** (same HTML). **Open as Comfy** = LiteGraph |
| Tests | `test_graph_view.py` class `JointGraphExport` |

LiteGraph.js (ComfyUI's editor) is also vendored. Spline links look like Comfy;
they do **not** pathfind around nodes. That is why it is not the live pane.

The Graphviz and grandalf stack is gone; the helper list is in *What we tried
before the live pane*.

## HTML and JS libraries

These run in a **browser or WebView2**, not in a Tk Canvas.

| Library | Comfy-like? | Smooth wires | Avoid node overlap | Embed notes |
|---|---|---|---|---|
| **JointJS** (`manhattan` + `rounded`) | Dark cards and left/right ports if we style them | Orthogonal with circular fillets | **Yes.** Manhattan treats other elements as obstacles | One UMD file. **Live pick.** |
| **LiteGraph.js** | **Yes, ComfyUI's editor** | Bezier or spline | No; wires can cross cards (same as Comfy) | Vendored. **Open as Comfy** |
| **Drawflow** | HTML nodes, not Comfy cards | Curved SVG | No | Vanilla JS |
| **Rete.js** | Visual programming | Plugin renderers | No | Heavy, needs a renderer |
| **xyflow + SmartBezier / avoid-nodes-edge** | Customizable cards | Bezier or orthogonal | **Best "no intersection"** (libavoid WASM) | React, not a drop-in in Tk |
| **ELK.js** (`edgeRouting: SPLINES`, conservative) | Layout engine, we paint | Splines that hug a layered graph | Conservative mode routes around nodes; sloppy can clip | Needs a real JS engine; worker-based bundle is awkward in `file://` |
| **nodegraph-js** | Dark cards, left/right slots | Bezier | Auto-arrange, not obstacle routing | Vanilla JS |
| **@gravity-ui/graph** | Node editor | Bezier | Canvas and HTML | Needs a bundler |
| **tkinterweb HtmlFrame** | Not a graph lib | n/a | n/a | HTML and CSS in Tk. JS is PythonMonkey and **cannot** run JointJS or LiteGraph |
| **tkwry (WebView2)** | Host for any JS graph | n/a | n/a | Real Edge in a Tk frame. **Live host.** |

The table carries each rejection; the Graphviz stack is removed (see "What we
tried").

Not a fit: Nodezator, NetworkX with Matplotlib, Qt/NodeGraphQt.

## What we tried before the live pane (both removed)

Two Tk attempts are gone with the dead layout stack. The in-house Comfy columns
with gutter polylines had chamfered corners, not circular fillets, and wires
still crossed cards. The grandalf Sugiyama placement scattered nodes;
rank-by-topology is not Comfy column order. The Graphviz attempt
(`splines=true`, HTML `<TABLE>` labels, compass `:e` to `:w` edges) went with
them, and its helpers (`prompt_to_dot`, `run_dot`, `graphviz_layout`,
`find_dot`, `parse_dot_plain`, `grandalf_resolve`, `resolve_layout`) were
**removed** from `graph_view.py`: nothing on the shipped path called them.

**No `dot` dependency today.** The pane never invokes Graphviz; the live pane is
JointJS HTML in WebView2 and the fallback is **Open in browser** (the same
HTML). There is no install message and no `layout_xy` fallback because there is
no `dot` path at all.

## Sources (survey)

- JointJS manhattan router and rounded connector (docs.jointjs.com); LiteGraph.js (github.com/jagenjo/litegraph.js, ComfyUI editor); tkwry WebView2 embed (pypi.org/project/tkwry)
- Graphviz `rankdir`, shapes, `splines`, `radius`, `fixedsize`, and `dot` layout (graphviz.org docs); this repo's `salad_studio/graph_view.py`
