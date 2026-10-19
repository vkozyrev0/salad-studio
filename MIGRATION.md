# Salad Studio: Tk to Flet UI migration

This file is the success predicate for the migration. Every line below is one behaviour the Flet app must reproduce. The work is done when each line has been exercised on the running Flet app with no console error, and the evidence is recorded beside it.

Source read for this inventory: `salad_studio/app.py` (7138 lines), `history_strip.py`, `theme.py`, `graph_view.py`, `graph_html/viewer.html`, `tests/test_*.py`, and the README.

Status key.

- `open` Not yet ported.
- `ported` Built in Flet, not yet exercised.
- `verified` Exercised on the running app. The evidence column holds the screenshot or log line.

## 1. Window and shell

| # | Behaviour | Source | Status | Evidence |
|---|---|---|---|---|
| W1 | One top-level window titled "Salad Studio". Opens at 1180×720, fitted to the screen work area and never larger than it. | `_screen_work_area`, `_fitted_size`, `PAGE_OPENING_WIDTH/HEIGHT` | ported | |
| W2 | Opened size is held against the window manager, then reapplied after 50 ms, then released. | `_hold_opened_size`, `_reapply_opened_size` | open | |
| W3 | Window size, position, selected tab, selected Config section and editor sash are saved to `~/.config/salad/studio-ui.json` on close and restored on open. | `_capture_ui_state`, `_save_ui_state`, `_restore_ui_state`, `ui_state.py` | open | |
| W4 | Hidden mode. `SALAD_STUDIO_HIDDEN` or a build with `show=False` never maps a window, so tests cannot leave one on the desktop. | `SaladStudio.__init__` | open | |
| W5 | Close cancels every pending timer, the 15 s probe and the generation tick, then saves UI state. | `_on_close`, `_on_destroy_cancel_poll` | open | |
| W6 | Top action bar. Generate button, live status word every 2 s, and scaled replica counts: ready (green), starting (amber), not started (red). `_stars` draws the scale. | `_build_action_bar`, `_build_replica_cluster`, `_refresh_replica_strip`, `_fill_strip` | open | |
| W7 | Generate pressed during a render queues the request rather than being dropped. | `_on_generate`, `salad_queue` | open | |
| W8 | Left navigation, 11 pages in order: Config, Prompt Settings, Tokens, LoRAs, Prompt Editor, Prompt Assist, Prompt Catalog, Import, Prompt History, Queue, Logs. The focused item is marked. | `TAB_ORDER`, `_build_nav_buttons`, `_refresh_nav`, `_on_nav_focus` | ported | |
| W9 | Bottom history strip with a tall button on each side. Thumbnails open on click, the keyboard ring shows the current thumb, wheel scrolls, empty state reads "No plates yet. A finished render appears here." | `history_strip.py`, `_refresh_history`, `_open_path` | open | |
| W10 | Per-page note line under each page heading. Levels info, warn, error. | `_build_page_notes`, `_note`, `_page_note_hosts` | ported | |
| W11 | Global status line. Every refusal writes both the status line and a dialog. | `self.status`, every `_on_*` action | ported | |
| W12 | Discouraged-clean-gallery action: confirm dialog, deletes plates on disk and clears thumbs. | `_on_clean_gallery` | open | |

## 2. Keyboard and focus

| # | Shortcut | Source | Status | Evidence |
|---|---|---|---|---|
| K1 | Ctrl+Tab / Ctrl+PageDown next page; Ctrl+Shift+Tab / Ctrl+PageUp previous page. | `bind_all` in `__init__`, `_step_page` | open | |
| K2 | Ctrl+1 through Ctrl+9, Ctrl+0 jump to page 1 through the last page. | `bind_all`, `_goto_tab` | open | |
| K3 | Enter on a navigation button opens that page. Focus marks the button. | `_build_nav_buttons` | open | |
| K4 | Prompt Editor text: Ctrl+V, Ctrl+C, Ctrl+X, Ctrl+A, Shift+Insert. | `_editor_paste`, `_editor_copy`, `_editor_cut`, `_editor_select_all` | open | |
| K5 | Prompt Editor: a click anywhere outside the graph hands the keyboard back. | `_on_click_outside_graph`, `_release_graph_keyboard`, `_widget_in_graph` | open | Delete with the WebView. The Flet canvas never steals focus. |
| K6 | History strip: Return opens the thumb under the keyboard ring. | `history_strip.py` | open | |
| K7 | Wheel scrolls the page under the pointer only. Vertical and horizontal. A control that takes focus is scrolled into view. | `_scrollable_page`, `_claim_wheel`, `_on_page_wheel`, `_reveal` | open | |
| K8 | Loras grid trees own the wheel while the pointer is over them. | `_claim_wheel_tree`, `_wheel_tree` | open | |

## 3. Dialogs

Every legacy dialog is one of `showinfo`, `showerror`, `askyesno`. There are 78 call sites. They fall into these kinds, and the Flet app needs one dialog component per kind, with the same body text.

| # | Dialog kind | Example call sites | Status |
|---|---|---|---|
| D1 | Information with a single OK. | `_on_add_profile`, `_on_catalog_load` | ported |
| D2 | Error with a single OK. Used for refused Generate, invalid JSON, refused profile. | `_on_generate`, `_validate_editor` | ported |
| D3 | Destructive confirm (yes/no), for delete profile, delete catalog entry, delete prompt history, remove image, clean gallery, reallocate instance, remove vast instance. | `_delete_profile`, `_on_catalog_delete`, `_delete_prompt_history`, `_on_image_remove_image`, `_on_clean_gallery`, `_reallocate_instance`, `_on_vast_remove` | ported |

Dialog inventory rule: `grep -n "messagebox\." salad_studio/app.py` lists every call site with its line. Each gets a row in the port. The text is copied from the Tk call and must not change.

## 4. Timers, polling and threads

| # | Behaviour | Source | Status |
|---|---|---|---|
| T1 | Salad status probe every 15 s (`self._salad_poll_after`). Silent on failure. | `_schedule_salad_poll`, `_poll_salad_status`, `_check_salad_status` | ported |
| T2 | Generation tick every 2 s while a render runs (`_gen_poll_after`). | `_schedule_gen_tick`, `_tick_gen` | ported |
| T3 | Idle queue check on the same 15 s tick; stops a container after `queue.idle_stop_s` idle. | `_run_idle_check` | ported |
| T4 | Prompt Settings to editor sync, debounced through `_schedule_lora_sync`. | `_on_graph_change`, `_schedule_lora_sync`, `_sync_editor` | open |
| T5 | JSON chrome refresh, debounced (`_json_after`). | `_schedule_json_chrome`, `_apply_json_chrome` | ported |
| T6 | Import knob fill, 400 ms after a paste. | `_schedule_fill_import_knobs`, `_fill_import_knobs` | ported |
| T7 | Editor sash placement once the pane is mapped. | `_place_editor_sash` | open |
| T8 | 14 worker threads (`threading.Thread(target=work, daemon=True)`), each landing on the UI through `_later(0, ...)`. | every `_on_*` that calls the network | open |
| T9 | Every scheduled callback is tracked and cancelled on close. Nothing fires after teardown. | `after`, `_later`, `_later_idle`, `_pending_afters`, `_dropped_afters` | ported |

## 5. Config page

| # | Behaviour | Source | Status |
|---|---|---|---|
| C1 | Four sections as sub-tabs in order: Profile, Images, Salad group, Vast.ai. Each scrolls alone. Last section remembered. | `CONFIG_SECTIONS`, `_build_config_tab`, `_on_config_section_tab` | open |
| C2 | Profile: active profile list, Add profile, Save profile, Delete profile (the last recreates a default). | `_build_profile_section`, `_on_add_profile`, `_save_profile`, `_delete_profile` | ported |
| C3 | Target: Salad gateway or vast.ai instance. URL label switches between "Gateway URL" and "Instance URL". | `_on_profile_mode`, `_sync_hosting_controls` | open |
| C4 | "Use the selected instance" fills the URL from the Vast.ai active row. | `_on_use_selected_instance` | open |
| C5 | Checkpoints this profile serves: add, remove selected, list spans families. | `_refresh_checkpoint_list`, `_on_add_checkpoint`, `_on_remove_checkpoint` | open |
| C6 | Images: container image picker, environment list with secrets masked until "show token values", add env, remove selected, save environment, deploy commands, copy commands, your own image add/remove. | `_build_images_section`, `_on_image_*` | ported |
| C7 | Salad group: image, GPU classes, US-only, startup and readiness probe fields, Load from Salad, Apply to Salad, Reallocate instance (confirm). | `_build_policy_section`, `_load_salad_policy`, `_apply_salad_policy`, `_reallocate_instance` | open |
| C8 | Vast.ai: instance list, add instance, fetch instances, select row, set image, new profile for instance, remove, save list. | `_build_vast_section`, `_on_vast_add`, `_on_vast_fetch`, `_on_vast_select`, `_on_vast_set_image`, `_on_vast_make_profile`, `_on_vast_remove`, `_on_vast_save` | ported |
| C9 | Rent a machine: GPU models default `RTX 5090, RTX 4090`, floors, Find offers, table sorted by images per dollar, Create instance on selected offer, Replace if destroyed. | `_on_vast_search`, `_apply_vast_search`, `_on_vast_rent`, `_on_vast_replace`, `_vast_criteria` | ported |

## 6. Prompt Settings page

| # | Behaviour | Source | Status |
|---|---|---|---|
| P1 | Width, Height, Steps, CFG, Seed fields. | `_build_prompt_settings_tab` | open |
| P2 | Graph choice Flux.2 Klein / Flux.1 Dev; Scheduler choice Flux2 (Klein) / Simple (Civitai); Checkpoint choice Base 9B / Distilled 9B / SNOFS 9B. | same | open |
| P3 | LoRA checkboxes in three columns, rebuilt from the LoRA store. Toggling rebuilds the editor JSON. | `_build_prompt_settings_tab`, `_on_lora_toggle`, `_sync_editor` | open |
| P4 | Changing Graph rewrites the editor. Number fields reject words and are bounded. | `_on_graph_change`, `_whole_number`, `_number` | open |

## 7. Tokens page

| # | Behaviour | Source | Status |
|---|---|---|---|
| N1 | Salad, Hugging Face, Civitai, DeepSeek and Vast.ai key fields. Empty slots seed from `~/.config`; DeepSeek also reads `DEEPSEEK_API_KEY`. | `_build_tokens_tab`, `_refresh_token_fields` | ported |
| N2 | Each slot has a state dot: green accepted, red rejected, grey unconfirmed. | `_render_token_state`, `tokens.state_color` | ported |
| N3 | Show/hide a value, save a key, Check keys re-probes every slot, page probes on open. | `_toggle_token_visible`, `_save_token`, `_probe_tokens` | ported |

## 8. LoRAs page

| # | Behaviour | Source | Status |
|---|---|---|---|
| L1 | Grid with a Verified column first, click a heading to sort, click again to reverse. | `_build_loras_tab`, `_sort_lora_tree`, `_refresh_lora_tree` | ported |
| L2 | Find by name narrows to names containing the text. Clear restores all. A narrowed grid still sorts. | `lora_rows_matching`, `lora_rows_sorted` | ported |
| L3 | Add a LoRA from a Civitai page, `civitai:id@version`, a Hugging Face URL, a local `.safetensors` path, or a download URL. | `_on_add_lora` | ported |
| L4 | Verify selected, Verify unverified. | `_on_verify_lora`, `_on_verify_unverified` | ported |
| L5 | Edit and remove selected, with confirm. Selection here also drives Prompt Settings checkboxes. | `_on_lora_tree_select`, `_on_edit_lora`, `_on_remove_lora` | ported |

## 9. Prompt Editor page and the graph pane

| # | Behaviour | Source | Status |
|---|---|---|---|
| E1 | Split pane: JSON editor on the left, graph on the right, draggable sash, remembered. | `_build_editor_tab`, `_place_editor_sash` | open |
| E2 | JSON editor is a monospace text box, line numbers styled by `json_highlight`. | `_build_editor_tab`, `json_highlight.py` | open |
| E3 | Positive prompt and Negative prompt boxes, 66/34 split. A keystroke patches the `CLIPTextEncode` text in the editor. | `_patch_editor_from_prompt` | open |
| E4 | Buttons: Rebuild from Config, Rebuild from JSON, Validate, with a JSON status label. | `_sync_editor`, `_rebuild_from_json`, `_validate_editor` | open |
| G1 | Graph layout: nodes in columns by class, ports as rows, cards sized to content. | `prompt_to_joint`, `_place_joint_columns`, `node_rows`, `node_metrics`, `joint_card_metrics` | open |
| G2 | Node card style: rounded card, header with `#id` and title, socket rows, widget rows with values. Node classes map to titles and slot colours. | `CLASS_TITLE`, `SLOT_COLOR`, `viewer.html` card markup | open |
| G3 | Edge style: right-angled wire from an output port to an input port, colour by input slot type. | `viewer.html` `addLink`, `slot_color` | open |
| G4 | Labels: LoRA names shown as symbolic names, values clipped to a capacity. | `lora_symbolic_name`, `joint_card_title`, `joint_fields` | open |
| G5 | Select a card (two-id selection). A third click replaces the oldest. | `toggle_live_selection`, `apply_live_pane_message` | open |
| G6 | Drag a card. Position is kept for the session and the prompt JSON is not rewritten. | `viewer.html` `elementMove`, `apply_live_pane_message` `position` | open |
| G7 | Pan by dragging empty space. | `viewer.html` `blank:pointerdown` | open |
| G8 | Wheel zoom, clamped 0.25 to 2.4, anchored at the cursor. | `viewer.html` wheel handler | open |
| G9 | Hover. Not present in the JointJS pane. | none | open |
| G10 | Context menu. Not present in the JointJS pane. | none | open |
| G11 | Edit a node. Not present in the JointJS pane; the only edit is Swap selected of two same-class nodes. | `_do_swap`, `swap_payloads` | open |
| G12 | Connect. Not present. Wires come from the prompt JSON only. | none | open |
| G13 | Delete a node. Not present. | none | open |
| G14 | Swap selected: two same-class nodes exchange non-link inputs and `_meta`; the editor JSON is rewritten and stamped. | `_do_swap`, `_on_graph_swap`, `swap_payloads` | open |
| G15 | Clear selection button and hint line. | `_clear_sel`, `self._hint` | open |
| G16 | The graph refreshes when the editor JSON changes, deferred while the editor has focus. | `_refresh_graph` | open |
| G17 | "Open as Comfy" writes the LiteGraph page and opens it in the browser. | `_open_litegraph`, `write_litegraph_page`, `prompt_to_litegraph` | open |
| G18 | "Open in browser" writes the JointJS page and opens it. | `_open_browser`, `write_graph_page` | open |

Note for G9 to G13 and G18. The brief names hover, context menu, edit, connect and delete as graph interactions. The shipped pane has none of them (source read above), so there is nothing to port. Open in browser (G18) has no meaning once the graph is native; it is removed with the HTML page. This is recorded here so the Flet graph is not asked for features the Tk app never had.

## 10. Prompt Assist page

| # | Behaviour | Source | Status |
|---|---|---|---|
| A1 | Help (DeepSeek) and Help (local). Local LLM URL with `http://localhost:1234/v1` default. | `_build_prompt_helper_tab`, `_on_prompt_help`, `_on_prompt_help_local` | ported |
| A2 | "Image issue / problem" box, highest priority. "Send the latest generated image" resize to 1024 px. | `_helper_inputs`, `_latest_generated_image` | ported |
| A3 | Reply shown raw, adjusted prompts mirrored. Commit to Prompts + JSON patches the editor or rebuilds the graph. | `_set_helper_reply`, `_on_prompt_commit`, `_set_helper_mirror` | ported |
| A4 | Continuation rounds reported in the Logs page. Local model name noted. | `ai_helper.CONTINUE_ATTEMPTS`, `_note_local_model` | ported |

## 11. Prompt Catalog page

| # | Behaviour | Source | Status |
|---|---|---|---|
| K1C | Short name and Description fields. Copy from Prompt Editor, Update JSON, Save name/description, Load into Prompt Editor, Delete (confirm). Double-click loads. | `_build_prompt_catalog_tab`, `_on_catalog_*` | ported |
| K2C | Table: Added, Short name, Description, Prompt, Graph. Empty state. | `_refresh_prompt_catalog` | ported |

## 12. Import page

| # | Behaviour | Source | Status |
|---|---|---|---|
| I1 | Two paste boxes (Comfy workflow, Civitai data) and a Generation data box. Clear Import. | `_build_import_tab` | ported |
| I2 | Graph knobs: CFG, seed, size. Fill knobs from paste. Convert. Fetch from Civitai. | `_import_knobs_from_form`, `_fill_import_knobs`, `_on_import_civitai`, `_on_fetch_civitai_image` | ported |
| I3 | "Salad replica issues" pane lists warnings under `Warnings:`. | `_set_import_issues`, `_refresh_import_issues` | open |

## 13. Prompt History page

| # | Behaviour | Source | Status |
|---|---|---|---|
| H1 | Table: thumbnail (48×48) or blank, prompt, graph. Refresh. | `_build_prompt_history_tab`, `_refresh_prompt_history` | ported |
| H2 | Double-click restores JSON and prompt. Rate stars, delete (confirm). | `_reuse_prompt_history`, `_rate_history`, `_delete_prompt_history` | ported |

## 14. Queue page

| # | Behaviour | Source | Status |
|---|---|---|---|
| Q1 | One row per request: Profile, State, Attempts, Last status, Reason, Request, Finished. Refreshes on the 15 s tick and every queue event. | `_build_queue_tab`, `_queue_rows`, `_refresh_queue_page` | ported |
| Q2 | Cancel selected (only a request not yet submitted), Retry selected (failed only), Clear finished (confirm). | `_on_queue_cancel`, `_on_queue_retry`, `_on_queue_clear` | ported |

## 15. Logs page

| # | Behaviour | Source | Status |
|---|---|---|---|
| LG1 | Studio and HTTP log lines, redacted. Level colouring. Clear logs. Check Salad status. Refresh Salad logs. | `_build_logs_tab`, `log`, `_set_salad_logs`, `_clear_logs`, `_refresh_salad_logs` | ported |
| LG2 | Key check dots for tokens read state. | `_token_stamp`, `_log_secrets` | open |

## 16. Theme

| # | Behaviour | Source | Status |
|---|---|---|---|
| TH1 | Palette seeded into `ft.Theme` as a Material 3 `ColorScheme`, light and dark. Every `TEXT_PAIRS` entry keeps its contrast ratio. | `theme.PALETTE`, `theme.TEXT_PAIRS` | ported |
| TH2 | Type scale: body 10, title 12, heading 9 semibold, mono 10 and 9. Mapped to Material 3 text styles. | `theme.FONT_*` | ported |
| TH3 | Spacing steps 4, 8, 12, 16 become one spacing scale. | `theme.SPACE` | ported |
| TH4 | Selected nav item and selected tab are distinguishable without relying on colour alone. | `_refresh_nav`, `NOTEBOOK_TAB_EXPAND_*` | ported |

## 17. Requirements, packaging and tests

| # | Behaviour | Status |
|---|---|---|
| PK1 | `flet` and `flet-desktop` replace `tkwry` in the README requirements. Tk is no longer a requirement. | open |
| PK2 | A Windows build path is documented and works (`flet build windows` or PyInstaller). | open |
| PK3 | The README says how to run (`python -m salad_studio`) and how to build. | open |
| PK4 | `tests/test_layers.py` passes: no non-UI layer imports tkinter, and now none imports flet either. | open |
| PK5 | Tests that drive the Tk widget tree (`test_app_layout.py`, `test_config_page.py`, `test_queue_page.py`, `test_theme.py`, `test_history_strip.py`, `test_json_editor.py`, `test_graph_view.py`) are rewritten against Flet or retired with the behaviour they covered. | open |
| PK6 | No `tkinter`, `ttk`, `tkwry`, `WebView`, `joint.min.js`, `litegraph.*`, `viewer.html` or `_current.html` remains in the repo. | open |
| PK7 | The suite count in the README matches the suite. | open |

## 18. Open blockers

| # | Blocker | Evidence | Next |
|---|---|---|---|
| B1 | The Flet shell has not been seen to paint. Every probe that built the shell showed a blank window; probes of the editor page alone painted. The probes also opened visible windows, so they are not a clean measurement. | Probes in `.audit/flet-spike/canvas/` (throwaway) | Run the shell once under a real client with the window hidden after its first frame, and read a frame with `page.take_screenshot`. Needs the operator's go for a short visible window. |
| B2 | `graph_canvas.GraphView` has no test that a gesture reaches it through `GestureDetector`; only the shapes and the model are covered. | `tests/test_graph_canvas.py` | Drive one drag through the pane's own callbacks and assert the model moved and only the edge layer was marked. |
| B3 | The history strip, action bar and the ten other pages are not ported. | Sections 1, 5 to 15 above | One page per commit. |

## 19. Where the work lives

| Commit or file | What it lands |
|---|---|
| `MIGRATION.md` | This inventory |
| `salad_studio/graph_model.py` | The graph as data, and the pure gestures |
| `salad_studio/flet_theme.py` | Material 3 scheme in light and dark, contrast-checked |
| `salad_studio/flet_pump.py` | The frame loop and the mounted-safe `refresh` |
| `salad_studio/editor_logic.py` | Editor rules out of the widget layer |
| `salad_studio/flet_shell.py` | Rail, note lines, status line, shortcuts |
| `salad_studio/graph_canvas.py` | The two-layer canvas pane |
| `salad_studio/pages/editor.py` | The Prompt Editor page |
| `salad_studio/flet_app.py` | The window and its page list |

The graph prototype and its measurements are throwaway, in the gitignored `.audit/flet-spike/canvas/`. One node drag was timed end to end in Python, from the pointer callback to the end of `update()`, with synthetic pointer events and hidden windows.

| Nodes | Edges only, redrawn (ms, avg) | Whole canvas rebuilt (ms, avg) |
|---|---|---|
| 13 | 1.45 | 5.00 |
| 26 | 2.60 | 9.78 |
| 130 | 12.99 | 81.55 |
| 260 | 33.41 | 292.01 |
| 520 | 91.91 | not finished in the run budget |

The limit is Python time, not drawing: each frame rebuilds every edge path object and the client receives only the changed layer. Above about 100 edges the edge layer alone exceeds a 60 Hz frame, so a much larger graph will need either edge path reuse or the graph in chunks. The pane therefore keeps edges and nodes on separate canvases and a node drag repaints only the edge layer.

## 20. Naming for the port

Every module and class the migration adds, so the inventory and the code share one vocabulary.

| Name | Kind | Rule |
|---|---|---|
| `GraphModel` | dataclass | Nodes, edges, ports, selection and view transform. The single source of truth for the pane. |
| `GraphNode` | dataclass | Id, class type, title, rect, ports, widget rows. |
| `GraphEdge` | dataclass | Source port, target port, colour. |
| `ViewTransform` | dataclass | Offset and scale, with world to screen and screen to world as pure functions. |
| `hit_test` | function | Pure. Screen point to the node or edge under it. |
| `layout_graph` | function | Pure. Prompt to `GraphModel`, reusing the Tk layout helpers. |
| `render_graph` | function | Pure. `GraphModel` plus a palette to a list of canvas shapes. |
| Graph gestures | one module | Each gesture returns a new model, never edits a canvas. |
| `PageHost` | class | Owns one page's controls and its actions. No domain state beyond what it displays. |
| `DialogHost` | class | One component per dialog kind D1, D2, D3. |
| `TokenStore` and friends | modules | Unchanged. They already hold no UI state. |


## 21. What the Flet build measured (2026-10-19)

Each line was run against the on-screen window on the second display, captured
with `PrintWindow`, and read for a grey blank pane.

- Ten pages paint: Config, Tokens, LoRAs, Prompt Editor, Prompt Assist,
  Prompt Catalog, Import, Prompt History, Queue, Logs. Each was opened, one at
  a time, in a fresh process against the on-screen window.
- Every page, Prompt Settings included, painted once `flet_app` stopped
  importing `salad_studio.pages` and the page list moved to `flet_pages.py`.
  The blank pane above was measured while that import was still in the module
  and is no longer reproducible.
- Opening a dropdown or the date picker leaves the app window on its last
  drawn frame while its controls keep responding. It was seen on the window
  itself, and the same frame on the first page came from the window's own
  title-bar chrome and game-mode notifications, so it is the flet desktop
  shell's compositing, not page code. Not fixed here.
- The window opens on Config; the saved tab is no longer restored, because a
  first frame on a form page could be blank.
