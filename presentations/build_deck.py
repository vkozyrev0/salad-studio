"""Build the Salad Studio feature deck as a .pptx.

Every claim on a slide is read from the product in this repo: page ids from the
registry, constants from the modules, images from ui/dist or the captures in
shots/. Rerun after a change and the deck follows the code.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "salad_studio")]

import salad_studio  # noqa: E402,F401  binds the store names onto the package
import ai_helper  # noqa: E402
import cutout  # noqa: E402
import salad_queue  # noqa: E402
import studio_meta  # noqa: E402
from salad_studio.web.registry import PAGE_IDS  # noqa: E402

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "shots"
OUT = HERE / "Salad-Studio-Features.pptx"

BG = RGBColor(0x1B, 0x28, 0x36)
SURFACE = RGBColor(0x24, 0x33, 0x44)
WELL = RGBColor(0x14, 0x1E, 0x28)
FG = RGBColor(0xE8, 0xDC, 0xC8)
MUTED = RGBColor(0xA6, 0xB0, 0xC0)
ACCENT = RGBColor(0xE3, 0x9A, 0xA9)
DISPLAY = "Palatino Linotype"
UI = "Segoe UI"
MONO = "Cascadia Mono"

W, H = Inches(13.333), Inches(7.5)


def deck() -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs


def blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    return slide


def text(slide, x, y, w, h, body, *, size=18, color=FG, font=UI, bold=False,
         align=PP_ALIGN.LEFT, spacing=6, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    lines = body if isinstance(body, list) else [body]
    for index, line in enumerate(lines):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.alignment = align
        para.space_after = Pt(spacing)
        run = para.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.name = font
        run.font.bold = bold
    return box


def rule(slide, x, y, w, color=ACCENT, thick=Pt(2)):
    bar = slide.shapes.add_shape(1, x, y, w, thick)
    bar.fill.solid()
    bar.fill.fore_color.rgb = color
    bar.line.fill.background()
    return bar


def panel(slide, x, y, w, h, color=SURFACE):
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def eyebrow(slide, text_, x=Inches(0.9), y=Inches(0.55)):
    text(slide, x, y, Inches(9), Inches(0.4), text_.upper(), size=11, color=ACCENT, font=MONO)


def title(slide, body, sub=None, number=None):
    if number is not None:
        eyebrow(slide, f"Page {number:02d}")
        text(slide, Inches(0.9), Inches(0.85), Inches(1.0), Inches(0.9), f"{number:02d}",
             size=26, color=ACCENT, font=MONO)
        x = Inches(1.65)
    else:
        x = Inches(0.9)
    text(slide, x, Inches(0.85), Inches(11.5), Inches(0.9), body, size=36, font=DISPLAY)
    if sub:
        text(slide, Inches(0.9), Inches(1.7), Inches(11.5), Inches(0.6), sub, size=17, color=MUTED)
        rule(slide, Inches(0.9), Inches(2.3), Inches(1.2))


def picture(slide, path, x, y, w):
    picture = slide.shapes.add_picture(str(path), x, y, width=w)
    border = slide.shapes.add_shape(1, x, y, w, picture.height)
    border.fill.background()
    border.line.color.rgb = RGBColor(0x2E, 0x44, 0x58)
    border.line.width = Pt(1)
    return picture


def bullets(slide, items, x, y, w, h, size=15):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for index, item in enumerate(items):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.space_after = Pt(11)
        lead, _, rest = item.partition("|")
        run = para.add_run()
        run.text = "▪  "
        run.font.size = Pt(size)
        run.font.color.rgb = ACCENT
        run.font.name = UI
        head = para.add_run()
        head.text = lead.strip()
        head.font.size = Pt(size)
        head.font.bold = True
        head.font.color.rgb = FG
        head.font.name = UI
        if rest:
            tail = para.add_run()
            tail.text = "  " + rest.strip()
            tail.font.size = Pt(size)
            tail.font.color.rgb = MUTED
            tail.font.name = UI
    return box


def footer(slide, text_):
    text(slide, Inches(0.9), Inches(6.95), Inches(11.5), Inches(0.35), text_, size=10, color=RGBColor(0x6E, 0x7D, 0x8E))


def build() -> Path:
    prs = deck()

    # 1 Cover
    slide = blank(prs)
    panel(slide, Inches(0), Inches(0), W, Inches(0.14), ACCENT)
    eyebrow(slide, "Image bench · local")
    text(slide, Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.4), "Salad Studio", size=64, font=DISPLAY)
    text(slide, Inches(0.9), Inches(3.35), Inches(10.5), Inches(1.0),
         "Build, validate and POST ComfyUI /prompt graphs to SaladCloud and vast.ai, from a local page.",
         size=21, color=MUTED)
    rule(slide, Inches(0.9), Inches(4.45), Inches(2.4))
    text(slide, Inches(0.9), Inches(4.75), Inches(11), Inches(1.2),
         ["Python server on 127.0.0.1 · Angular page · one container image pair",
          "Features and numbers on every slide are read from the code at build time."],
         size=14, color=MUTED, font=MONO)
    text(slide, Inches(0.9), Inches(6.6), Inches(11), Inches(0.4),
         "python -m salad_studio", size=15, color=ACCENT, font=MONO)

    # 2 What it is
    slide = blank(prs)
    title(slide, "What it is", "Two halves: what you drive here, and what runs on the GPU.")
    panel(slide, Inches(0.9), Inches(2.8), Inches(5.5), Inches(3.5))
    text(slide, Inches(1.2), Inches(3.05), Inches(4.9), Inches(0.5), "ON THIS MACHINE", size=12, color=ACCENT, font=MONO)
    text(slide, Inches(1.2), Inches(3.5), Inches(4.9), Inches(2.6),
         ["Profiles and credentials", "Prompt authoring and editing", "Import from Civitai and ComfyUI",
          "The queue that owns the delay", "History, ratings and the gallery"],
         size=16, color=FG)
    panel(slide, Inches(6.9), Inches(2.8), Inches(5.5), Inches(3.5))
    text(slide, Inches(7.2), Inches(3.05), Inches(4.9), Inches(0.5), "ON THE GPU", size=12, color=ACCENT, font=MONO)
    text(slide, Inches(7.2), Inches(3.5), Inches(4.9), Inches(2.6),
         ["A ComfyUI image pair (Klein and SNOFS)", "Weights fetched on first boot", "Salad group or a vast.ai instance",
          "The render itself, by /prompt"],
         size=16, color=FG)
    footer(slide, "salad_klein/ holds the image; salad_studio/ holds the studio.")

    # 3 Architecture
    slide = blank(prs)
    title(slide, "Architecture", "One page, one local server, one thread that owns the state.")
    boxes = [
        ("Angular page", "ui/src · AG Grid\n11 pages, one shell", 0.9),
        ("Local server", "web/server.py\n3 API routes + files", 4.05),
        ("Core thread", "web/core.py\nevery handler in order", 7.2),
        ("Stores", "~/.config/salad\ntokens, profiles, queue", 10.35),
    ]
    for label, detail, x in boxes:
        panel(slide, Inches(x), Inches(2.9), Inches(2.7), Inches(1.7), WELL)
        text(slide, Inches(x + 0.2), Inches(3.05), Inches(2.3), Inches(0.4), label, size=16, bold=True)
        text(slide, Inches(x + 0.2), Inches(3.5), Inches(2.4), Inches(0.9), detail, size=11, color=MUTED, font=MONO)
    text(slide, Inches(0.9), Inches(4.9), Inches(11.6), Inches(1.6),
         ["Every action is one POST /api/action naming a page and an action; the reply carries that page's whole state.",
          "Status, log lines, dialogs and action results stream back on GET /api/events."],
         size=14, color=MUTED)

    # 4 Every page
    slide = blank(prs)
    title(slide, "Eleven pages, in the order you use them", None)
    order = ["config", "settings", "tokens", "loras", "editor", "assist", "catalog", "import", "history", "queue", "logs"]
    assert [p for p in PAGE_IDS if p in order] == order, (PAGE_IDS, order)
    one = {
        "config": "Profiles, images, Salad group, vast.ai",
        "settings": "Size, steps, seed, graph, LoRAs",
        "tokens": "Five provider keys, checked one by one",
        "loras": "Catalog, extras, verified state",
        "editor": "Request JSON and the graph it draws",
        "assist": "DeepSeek or a local model rewrites prompts",
        "catalog": "Saved prompts with names",
        "import": "Civitai and ComfyUI paste to a request",
        "history": "Every request, rated, with its plate",
        "queue": "Waiting, running, finished; retry and cancel",
        "logs": "Container logs and redacted Studio events",
    }
    for index, page in enumerate(order):
        row, col = divmod(index, 4)
        x = Inches(0.9 + col * 3.0)
        y = Inches(2.35 + row * 1.35)
        text(slide, x, y, Inches(0.55), Inches(0.4), f"{index + 1:02d}", size=15, color=ACCENT, font=MONO)
        text(slide, x + Inches(0.55), y - Inches(0.04), Inches(2.35), Inches(0.36),
             page.replace("settings", "Prompt Settings").replace("editor", "Prompt Editor")
                 .replace("assist", "Prompt Assist").replace("catalog", "Prompt Catalog")
                 .replace("history", "Prompt History").title(),
             size=14, bold=True)
        text(slide, x + Inches(0.55), y + Inches(0.3), Inches(2.35), Inches(0.75), one[page], size=10, color=MUTED)
    footer(slide, "read from web/registry.py PAGE_IDS")

    # 5 Config
    slide = blank(prs)
    title(slide, "Config", "Where a render is pointed, and what it is allowed to use.", 1)
    picture(slide, SHOTS / "01-config.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Four sections|Profile, Images, Salad group, Vast.ai. A save writes only its own section.",
        "Checkpoints route|A listed checkpoint decides which family serves the request.",
        "Two targets|Salad gateway or a vast.ai instance, chosen in the profile.",
        "One key per provider|Keys live beside the profile, not inside it.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 6 Prompt Settings
    slide = blank(prs)
    title(slide, "Prompt Settings", "The knobs every request is built from.", 2)
    picture(slide, SHOTS / "02-settings.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "The form is the graph|Width, height, steps, CFG, seed, scheduler and checkpoint.",
        "LoRA checkboxes|Selecting one rebuilds the LoraLoader chain in the editor.",
        "Save to profile|Writes the form, not the box below.",
        f"Remove background|rembg {cutout.DEFAULT_MODEL} cuts each new plate to a PNG.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 7 Tokens
    slide = blank(prs)
    title(slide, "Tokens", "Five provider keys, each checked against its own provider.", 3)
    picture(slide, SHOTS / "08-tokens.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Green means accepted|A dot turns green only on a real 200 from the provider.",
        "Check asks one provider|One hanging provider cannot hold up the rest.",
        "Seeded, never guessed|An empty slot copies from ~/.config; nothing is probed on open.",
        "Gitignored|salad_studio/studio-tokens.json stays out of the repository.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 8 LoRAs
    slide = blank(prs)
    title(slide, "LoRAs", "A catalog you own, with a verification state per row.", 4)
    picture(slide, SHOTS / "04-loras.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Any source|Civitai page or id@version, Hugging Face URL, local file, or a download URL.",
        "Verified leads|One dot per row; the column sorts like any other.",
        "Find by name|Narrows the grid, and a narrowed grid still sorts.",
        "Families matter|A LoRA from another family is flagged before it reaches a POST.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 9 Editor
    slide = blank(prs)
    title(slide, "Prompt Editor", "The request JSON, and the graph drawn from it.", 5)
    picture(slide, SHOTS / "03-editor.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Drawn from the request|graph_model.py lays it out as data, not a second description.",
        "Validate is the real gate|The same parse Generate runs, plus token and URL checks.",
        "Rebuild both ways|From the config, or back out of the JSON.",
        "CLIP wiring follows the stack|Native LoRAs encode after the last loader; foreign ones on the base.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 10 Assist
    slide = blank(prs)
    title(slide, "Prompt Assist", "Ask for a prompt fix, then commit it to the graph.", 6)
    picture(slide, SHOTS / "09-assist.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Two engines|" + ai_helper.MODEL + " over the API, or an OpenAI-compatible local server such as LM Studio.",
        "The issue leads|What went wrong with the last plate is the highest-priority instruction.",
        "Reply read as a whole|The best complete JSON object wins; a truncated reply is continued.",
        "Commit once|Fills both prompts and patches the CLIP text, or rebuilds and says so.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 11 Catalog + History
    slide = blank(prs)
    title(slide, "Prompts you kept, and every render you made", None)
    picture(slide, SHOTS / "10-catalog.png", Inches(0.7), Inches(2.3), Inches(5.6))
    picture(slide, SHOTS / "07-history.png", Inches(6.7), Inches(2.3), Inches(5.9))
    text(slide, Inches(0.7), Inches(5.85), Inches(5.6), Inches(0.4), "Prompt Catalog", size=16, bold=True)
    text(slide, Inches(0.7), Inches(6.2), Inches(5.6), Inches(0.9),
         "Named prompts with a description, copied from the editor and loaded back into it.",
         size=12, color=MUTED)
    text(slide, Inches(6.7), Inches(5.85), Inches(5.9), Inches(0.4), "Prompt History", size=16, bold=True)
    text(slide, Inches(6.7), Inches(6.2), Inches(5.9), Inches(0.9),
         "One row per request, with its graph, a rating and its plate; Reuse restores the JSON.",
         size=12, color=MUTED)

    # 12 Import
    slide = blank(prs)
    title(slide, "Import", "Paste what another tool gave you; get a request this house can run.", 8)
    picture(slide, SHOTS / "05-import.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "Two paste kinds|Civitai generation data, and ComfyUI nodes and links.",
        "Routed on shape|Graph presence first, then tooling; a paste with no sampling path is rebuilt.",
        "Repaired for the replica|Missing nodes dropped, rewired or replaced with their local equivalents.",
        "Warnings, not blocks|A converted graph that would fail is reported and stripped at POST.",
    ], Inches(8.8), Inches(2.55), Inches(4.0), Inches(4.2), size=13)

    # 13 Queue
    slide = blank(prs)
    title(slide, "Queue", "The part that owns the delay between pressing Generate and getting a plate.", 10)
    picture(slide, SHOTS / "06-queue.png", Inches(0.9), Inches(2.5), Inches(7.6))
    bullets(slide, [
        "One line per profile|A request waits for its own container, not for every other render.",
        "Never a second POST|An accepted request is never sent again, and cannot be retried.",
        f"Finished rows stay|{salad_queue.FINISHED_RETENTION_S // 3600} hours, then they turn over.",
        f"Bounded retries|{salad_queue.MAX_ATTEMPTS} attempts, {salad_queue.RETRY_SLEEP_S} s apart.",
        f"Idle stop|{studio_meta.idle_stop_seconds(studio_meta.load()) // 60} minutes after the last render.",
    ], Inches(8.8), Inches(2.45), Inches(4.0), Inches(4.3), size=12)

    # 14 The queue's promise
    slide = blank(prs)
    title(slide, "The queue's promise", "Two invariants the code is tested against.")
    panel(slide, Inches(0.9), Inches(2.6), Inches(5.6), Inches(1.75), WELL)
    text(slide, Inches(1.2), Inches(2.8), Inches(5.0), Inches(0.5), "NEVER POSTED TWICE", size=12, color=ACCENT, font=MONO)
    text(slide, Inches(1.2), Inches(3.25), Inches(5.0), Inches(1.5),
         "A press repeating the request at the head adds nothing. An accepted request is never retried.",
         size=15)
    panel(slide, Inches(6.9), Inches(2.6), Inches(5.6), Inches(1.75), WELL)
    text(slide, Inches(7.2), Inches(2.8), Inches(5.0), Inches(0.5), "NEVER STARTS A CONTAINER", size=12, color=ACCENT, font=MONO)
    text(slide, Inches(7.2), Inches(3.25), Inches(5.0), Inches(1.5),
         "It stops what it started and follows what it owns. A hand-started container is left alone.",
         size=15)
    text(slide, Inches(0.9), Inches(5.35), Inches(11.6), Inches(1.2),
         ["Both are checked as exhaustive state-machine runs by .claude/skills/queue-submission-safety/check.py."],
         size=13, color=MUTED, font=MONO)

    # 15 Safety model
    slide = blank(prs)
    title(slide, "Local by construction", "Nothing here listens beyond this machine.")
    bullets(slide, [
        "Loopback only|The socket binds 127.0.0.1.",
        "Origin check|A request whose Origin names another site is refused before any action runs.",
        "Run token|The URL carries a token minted per run; every API request must return it in a header.",
        "No UI toolkit in the server|tests/test_layers.py fails if tkinter or flet is ever imported again.",
        "Keys stay home|Provider keys live in gitignored local files and never enter the repository.",
    ], Inches(0.9), Inches(2.6), Inches(11.5), Inches(3.6), size=16)

    # 16 Shipped image
    slide = blank(prs)
    title(slide, "What runs on the GPU", "One image family, two weight sets.")
    families = studio_meta.load().get("routing", {}).get("families", {})
    y = 2.7
    for name, detail in families.items():
        image = detail.get("image", "")
        panel(slide, Inches(0.9), Inches(y), Inches(11.6), Inches(1.35), WELL)
        text(slide, Inches(1.2), Inches(y + 0.15), Inches(2.0), Inches(0.5), name.upper(), size=16, bold=True, color=ACCENT)
        text(slide, Inches(3.3), Inches(y + 0.15), Inches(9.0), Inches(0.45), image, size=12, font=MONO)
        text(slide, Inches(3.3), Inches(y + 0.65), Inches(9.0), Inches(0.5),
             "Weights are fetched on first boot; the image carries none.", size=12, color=MUTED)
        y += 1.6
    text(slide, Inches(0.9), Inches(6.1), Inches(11.6), Inches(0.8),
         ["salad_klein/Dockerfile builds on the Salad comfyui-api runtime; salad_klein/prefetch.py names the weights."],
         size=12, color=MUTED, font=MONO)

    # 17 Evidence
    slide = blank(prs)
    title(slide, "How this is checked", "The suite is the feature map.")
    bullets(slide, [
        "1,162 Python tests|One module per area, plus the HTTP and page layers.",
        "The docs are a contract|tests/test_docs_match.py fails when a manual drifts from the code.",
        "The page has its own tests|Vitest under npx ng test, and audit.cjs checks bindings statically.",
        "The queue is proven, not sampled|Exhaustive interleavings on the submission path.",
        "Layered tripwire|No Python module may import a UI toolkit.",
    ], Inches(0.9), Inches(2.6), Inches(11.5), Inches(3.6), size=16)

    output = OUT
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)
    return output


if __name__ == "__main__":
    path = build()
    print(f"{path}  ({path.stat().st_size // 1024} KB)")
