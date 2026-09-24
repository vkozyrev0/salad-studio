#!/usr/bin/env python3
"""Salad Studio Windows UI: Config, LoRAs, Prompt Editor + history strip."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from salad_studio import ai_helper, comfy_import, generator, graph_view, json_highlight, lora_store, profiles, prompt_catalog, prompt_history, ref_check, request_json, salad_status, studio_log, theme, tokens, ui_state  # noqa: E402
from salad_studio.history_strip import HistoryStrip  # noqa: E402
from salad_studio.profiles import SaladProfile  # noqa: E402

# The Eldermark art output tree (generated plates). It lives outside this tool's
# repo, so it is a setting, not a relative walk-up: ELDERMARK_ART overrides it.
ART = Path(os.environ.get("ELDERMARK_ART", r"C:\Users\vkozy\repos\lifesim-design\art"))
OUT_DIR = ART / "salad_studio"
PROBE_GLOB = "salad_probe_klein_*.jpg"
TAB_ORDER = (
    "Config",
    "Prompt Settings",
    "Policy",
    "Tokens",
    "LoRAs",
    "Prompt Editor",
    "Prompt Assist",
    "Prompt Catalog",
    "Import",
    "Prompt History",
    "Logs",
)
LORA_CHECK_COLUMNS = 3


class SaladStudio(tk.Tk):
    def __init__(self, *, show: bool | None = None) -> None:
        """``show=False`` (or SALAD_STUDIO_HIDDEN in the environment) builds the
        whole window but never maps it, so a test run cannot flash windows."""
        super().__init__()
        self.withdraw()
        self._show_on_open = bool(show if show is not None else True) and not os.environ.get(
            "SALAD_STUDIO_HIDDEN"
        )
        theme.apply_theme(self)
        self.title("Salad Studio")
        self._opened_size_held = False
        self._opened_width = 0
        self._opened_height = 0
        self.bind("<Map>", self._hold_opened_size, add="+")
        self._busy = False
        self._helper_busy = False
        self._token_probe_busy = False
        self._token_detail: dict[str, str] = {}
        self._lora_vars: dict[str, tk.BooleanVar] = {}
        self._lora_checks: dict[str, ttk.Checkbutton] = {}
        self._pending_selected: list[str] = list(lora_store.DEFAULT_KLEIN_LORA_IDS)
        self._syncing_editor = False
        self._syncing_loras = False
        self._applying_profile = False
        self._json_after: str | None = None
        self._salad_poll_after: str | None = None
        self._salad_check_busy = False
        self._log_secrets_cache: list[str] | None = None
        self._gen_poll_after: str | None = None
        self._gen_t0 = 0.0
        self._gen_last_note = ""
        self._nav_btns: dict[str, tk.Button] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=0)

        self._build_action_bar()

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        nav = ttk.Frame(body, padding=(0, 0, 8, 0))
        nav.grid(row=0, column=0, sticky="nsw")
        self._nav = nav

        self.nb = ttk.Notebook(body, style="Hidden.TNotebook")
        self.nb.grid(row=0, column=1, sticky="nsew")

        self._build_config_tab()
        self._build_prompt_settings_tab()
        self._build_policy_tab()
        self._build_tokens_tab()
        self._build_loras_tab()
        self._build_editor_tab()
        self._build_prompt_helper_tab()
        self._build_prompt_catalog_tab()
        self._build_import_tab()
        self._build_prompt_history_tab()
        self._build_logs_tab()
        self.nb.add(self._config, text="Config")
        self.nb.add(self._settings, text="Prompt Settings")
        self.nb.add(self._policy, text="Policy")
        self.nb.add(self._tokens, text="Tokens")
        self.nb.add(self._loras, text="LoRAs")
        self.nb.add(self._editor, text="Prompt Editor")
        self.nb.add(self._helper, text="Prompt Assist")
        self.nb.add(self._catalog, text="Prompt Catalog")
        self.nb.add(self._import, text="Import")
        self.nb.add(self._prompt_hist, text="Prompt History")
        self.nb.add(self._logs, text="Logs")
        self._build_nav_buttons()

        self.strip = HistoryStrip(self, on_open=self._open_path, thumb_size=(140, 140))
        self.strip.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(
            self, textvariable=self.status, anchor="w", style="Status.TLabel"
        ).grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))

        self._load_profiles_into_ui()
        self._refresh_lora_lists()
        if not self._restore_ui_state():
            self._sync_editor()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._hold_opened_size()
        self.after_idle(self._place_editor_sash)
        self._refresh_history()
        if self._show_on_open:
            self.deiconify()
        self.log("info", "Salad Studio started")
        self.log("info", f"token store {tokens.LOCAL_PATH}")
        self.log("info", f"gateway {self.var_gateway.get().strip() or '(empty)'}")
        self.log(
            "info",
            f"graph {lora_store.graph_id(self.var_graph.get())}  "
            f"{self.var_width.get()}x{self.var_height.get()}  steps {self.var_steps.get()}",
        )
        self.after(500, lambda: self._check_salad_status(silent=True))
        self._schedule_salad_poll()
        self.bind("<Destroy>", self._on_destroy_cancel_poll, add="+")
        self.nb.bind("<<NotebookTabChanged>>", self._on_notebook_tab, add="+")
        self._refresh_nav()

    def _build_action_bar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 8, 8, 6))
        bar.grid(row=0, column=0, sticky="ew")
        self._action_bar = bar
        self.gen_btn = ttk.Button(
            bar, text="Generate", command=self._on_generate, style="Accent.TButton"
        )
        self.gen_btn.pack(side="left")
        self.gen_editor_btn = self.gen_btn
        ttk.Button(bar, text="Clean gallery", command=self._on_clean_gallery).pack(
            side="left", padx=(12, 0)
        )
        self.var_gen_state = tk.StringVar(value="Idle")
        self.gen_state_lbl = ttk.Label(bar, textvariable=self.var_gen_state)
        self.gen_state_lbl.pack(side="left", padx=(12, 0))
        self._build_replica_cluster(bar)

    def _build_replica_cluster(self, bar) -> None:
        """Dual replica badges and the Salad probe, right-aligned in the action bar."""
        holder = ttk.Frame(bar)
        holder.pack(side="right")
        self._replica_holder = holder
        self._replica_vars: dict[str, tuple[tk.StringVar, tk.StringVar, tk.Label]] = {}
        for i, (pid, title) in enumerate(
            (("klein", "klein (4090/3090)"), ("klein5090", "klein5090 (5090)"))
        ):
            ttk.Label(holder, text=title).grid(row=i, column=0, sticky="w", padx=(0, 6))
            word = tk.StringVar(value="…")
            detail = tk.StringVar(value="")
            lbl = tk.Label(
                holder,
                textvariable=word,
                font=("Segoe UI Semibold", 10),
                bg=theme.PALETTE["bg"],
                fg=theme.PALETTE["fg_muted"],
            )
            lbl.grid(row=i, column=1, sticky="w", padx=(0, 8))
            ttk.Label(holder, textvariable=detail, wraplength=420).grid(
                row=i, column=2, sticky="w"
            )
            self._replica_vars[pid] = (word, detail, lbl)
        right = ttk.Frame(holder)
        right.grid(row=0, column=3, rowspan=2, sticky="e", padx=(10, 0))
        ttk.Button(
            right, text="Check Salad status", command=self._check_salad_status
        ).pack(side="left")
        self.var_salad_status = tk.StringVar(value="…")
        self.salad_status_lbl = tk.Label(
            right,
            textvariable=self.var_salad_status,
            font=("Segoe UI Semibold", 11),
            bg=theme.PALETTE["bg"],
            fg=theme.PALETTE["fg_muted"],
        )
        self.salad_status_lbl.pack(side="left", padx=(8, 0))

    def _build_nav_buttons(self) -> None:
        for child in self._nav.winfo_children():
            child.destroy()
        self._nav_btns = {}
        p = theme.PALETTE
        for name in TAB_ORDER:
            btn = tk.Button(
                self._nav,
                text=name,
                anchor="w",
                command=lambda n=name: self._goto_tab(n),
                width=16,
                font=("Segoe UI", 10),
                bd=0,
                highlightthickness=0,
                padx=12,
                pady=6,
                cursor="hand2",
                background=p["surface"],
                foreground=p["fg"],
                activebackground=p["accent"],
                activeforeground=p["accent_fg"],
                disabledforeground=p["fg_muted"],
                relief="flat",
            )
            btn.pack(fill="x", pady=(0, 2))
            self._nav_btns[name] = btn

    def _goto_tab(self, name: str) -> None:
        for i, label in enumerate(TAB_ORDER):
            if label == name:
                try:
                    self.nb.select(i)
                except tk.TclError:
                    return
                break
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        current = ""
        try:
            current = str(self.nb.tab(self.nb.select(), "text") or "")
        except tk.TclError:
            pass
        p = theme.PALETTE
        for name, btn in self._nav_btns.items():
            on = name == current
            try:
                btn.configure(
                    background=p["accent"] if on else p["surface"],
                    foreground=p["accent_fg"] if on else p["fg"],
                    font=("Segoe UI Semibold", 10) if on else ("Segoe UI", 10),
                )
            except tk.TclError:
                pass

    def _build_config_tab(self) -> None:
        """Profile and gateway only; the prompt knobs live on Prompt Settings."""
        self._config = ttk.Frame(self.nb, padding=10)
        self._config.columnconfigure(1, weight=1)
        self.var_name = tk.StringVar()
        self.var_gateway = tk.StringVar()

        ttk.Label(self._config, text="Active profile").grid(row=0, column=0, sticky="w")
        self.profile_combo = ttk.Combobox(
            self._config, textvariable=self.var_name, state="normal"
        )
        self.profile_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_select_profile())
        btns = ttk.Frame(self._config)
        btns.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Button(btns, text="Save profile", command=self._save_profile).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(btns, text="Delete profile", command=self._delete_profile).pack(
            side="left"
        )
        ttk.Label(self._config, text="Gateway URL").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(self._config, textvariable=self.var_gateway).grid(
            row=2, column=1, sticky="ew", padx=6, pady=3
        )
        ttk.Label(
            self._config,
            text="Replica status and the Salad probe are in the top bar; size, steps, "
            "CFG, seed, graph, scheduler, checkpoint and LoRA selection are on Prompt Settings.",
            wraplength=760,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _build_prompt_settings_tab(self) -> None:
        """The prompt-shaping knobs split off Config, under the same attribute names."""
        self._settings = ttk.Frame(self.nb, padding=10)
        self._settings.columnconfigure(1, weight=1)
        self._settings.rowconfigure(20, weight=1)
        self.var_graph = tk.StringVar(value=lora_store.graph_label("klein"))
        self.var_width = tk.StringVar(value="1024")
        self.var_height = tk.StringVar(value="1024")
        self.var_steps = tk.StringVar(value="20")
        self.var_cfg = tk.StringVar(value="5")
        self.var_seed = tk.StringVar(value="1")
        r = 0
        for label, var in (
            ("Width", self.var_width),
            ("Height", self.var_height),
            ("Steps", self.var_steps),
            ("CFG", self.var_cfg),
            ("Seed", self.var_seed),
        ):
            ttk.Label(self._settings, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(self._settings, textvariable=var).grid(
                row=r, column=1, sticky="ew", padx=6, pady=3
            )
            r += 1
        ttk.Label(self._settings, text="Graph").grid(row=r, column=0, sticky="w")
        self.graph_combo = ttk.Combobox(
            self._settings,
            textvariable=self.var_graph,
            values=lora_store.GRAPH_CHOICES,
            state="readonly",
        )
        self.graph_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(self._settings, text="Scheduler").grid(row=r, column=0, sticky="w")
        self.var_scheduler = tk.StringVar(value="Flux2 (Klein)")
        self.sched_combo = ttk.Combobox(
            self._settings,
            textvariable=self.var_scheduler,
            values=("Flux2 (Klein)", "Simple (Civitai)"),
            state="readonly",
            width=22,
        )
        self.sched_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(self._settings, text="Checkpoint").grid(row=r, column=0, sticky="w")
        self.var_unet = tk.StringVar(value="Base 9B")
        self.unet_combo = ttk.Combobox(
            self._settings,
            textvariable=self.var_unet,
            values=request_json.UNET_LABELS,
            state="readonly",
            width=22,
        )
        self.unet_combo.grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(self._settings, text="LoRAs").grid(row=r, column=0, sticky="nw", pady=(8, 0))
        self._lora_inner = ttk.Frame(self._settings)
        self._lora_inner.grid(row=r, column=1, sticky="nsew", padx=6, pady=(8, 0))
        for c in range(LORA_CHECK_COLUMNS):
            self._lora_inner.columnconfigure(c, weight=1)
        for var in (
            self.var_width,
            self.var_height,
            self.var_steps,
            self.var_cfg,
            self.var_seed,
        ):
            var.trace_add("write", lambda *_a: self._sync_editor())
        self.var_graph.trace_add("write", lambda *_a: self._on_graph_change())
        self.var_scheduler.trace_add("write", lambda *_a: self._sync_editor())
        self.var_unet.trace_add("write", lambda *_a: self._sync_editor())

    def _schedule_salad_poll(self) -> None:
        if self._salad_poll_after is not None:
            try:
                self.after_cancel(self._salad_poll_after)
            except Exception:
                pass
        self._salad_poll_after = self.after(15_000, self._poll_salad_status)

    def _poll_salad_status(self) -> None:
        self._salad_poll_after = None
        self._check_salad_status(silent=True)
        self._schedule_salad_poll()

    def _on_destroy_cancel_poll(self, e=None) -> None:
        # Child Destroy events bubble to the Tk root via bindtags. Ignore
        # them or LoRA/tab rebuilds cancel the 15s Salad poll forever.
        if e is not None:
            w = getattr(e, "widget", None)
            if w is not None and w is not self and str(w) != str(self):
                return
        if self._salad_poll_after is not None:
            try:
                self.after_cancel(self._salad_poll_after)
            except Exception:
                pass
            self._salad_poll_after = None
        self._cancel_gen_tick()

    def _cancel_gen_tick(self) -> None:
        if self._gen_poll_after is not None:
            try:
                self.after_cancel(self._gen_poll_after)
            except Exception:
                pass
            self._gen_poll_after = None

    def _schedule_gen_tick(self) -> None:
        self._cancel_gen_tick()
        self._gen_poll_after = self.after(2000, self._tick_gen)

    def _tick_gen(self) -> None:
        self._gen_poll_after = None
        if not self._busy:
            return
        elapsed = max(0, int(time.monotonic() - self._gen_t0))
        note = (self._gen_last_note or "").strip()
        if len(note) > 80:
            note = note[:77] + "…"
        line = f"Generating… {elapsed}s"
        if note:
            line = f"{line}  {note}"
        self.var_gen_state.set(line)
        self._schedule_gen_tick()

    def _set_salad_word(self, word: str) -> None:
        self.var_salad_status.set(word)
        color = salad_status.color_for_status(word)
        try:
            self.salad_status_lbl.configure(fg=color)
        except tk.TclError:
            pass
        self._apply_generate_gate(word)

    def _apply_generate_gate(self, word: str) -> None:
        ready = (word or "").split()[:1] == ["Ready"]
        state = "normal" if ready and not self._busy else "disabled"
        for btn in (self.gen_btn, self.gen_editor_btn):
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass

    def _status_targets(self) -> list[tuple[str, str]]:
        """(profile_id, gateway) for dual badges; always klein + klein5090."""
        allp = profiles.load_all()
        out: list[tuple[str, str]] = []
        for pid, fallback in (
            ("klein", profiles.KLEIN_GATEWAY),
            ("klein5090", profiles.KLEIN_5090_GATEWAY),
        ):
            gw = fallback
            if pid in allp and (allp[pid].gateway or "").strip():
                gw = allp[pid].gateway.strip()
            out.append((pid, gw))
        return out

    def _check_salad_status(self, silent: bool = False) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            # Empty Config gateway: mark the active word Down, then fall through
            # on purpose — the probe below still fills the dual replica badges
            # from the profile gateways (see _status_targets).
            self._set_salad_word("Down")
        if self._salad_check_busy:
            return
        self._salad_check_busy = True
        targets = self._status_targets()
        active_gw = gw

        def work() -> None:
            snaps: dict[str, dict] = {}
            try:
                key = self._salad_api_key()
                for pid, gwx in targets:
                    snaps[pid] = salad_status.snapshot_gateway(gwx, key)
            except Exception:
                snaps = {}

            def done() -> None:
                self._salad_check_busy = False
                active_word = "Unknown"
                for pid, (word_var, detail_var, lbl) in getattr(
                    self, "_replica_vars", {}
                ).items():
                    info = snaps.get(pid) or {}
                    word = str(info.get("word") or "Down")
                    detail = str(info.get("detail") or info.get("error") or "")
                    word_var.set(word)
                    detail_var.set(detail)
                    try:
                        lbl.configure(fg=salad_status.color_for_status(word))
                    except tk.TclError:
                        pass
                    tgt_gw = dict(targets).get(pid, "")
                    if active_gw and tgt_gw and active_gw.rstrip("/") == tgt_gw.rstrip("/"):
                        active_word = word
                    if pid == "klein" and not active_gw:
                        active_word = word
                if active_gw:
                    for pid, gwx in targets:
                        if gwx.rstrip("/") == active_gw.rstrip("/") and pid in snaps:
                            active_word = str(snaps[pid].get("word") or active_word)
                            lines = snaps[pid].get("log_lines") or []
                            if lines:
                                self._set_salad_logs("\n".join(lines))
                            break
                self._set_salad_word(active_word)
                if not silent and snaps:
                    self.log("debug", f"Salad {active_word}")

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _on_notebook_tab(self, _e=None) -> None:
        try:
            tab = self.nb.tab(self.nb.select(), "text")
        except tk.TclError:
            return
        self._refresh_nav()
        if tab == "Policy" and not self._applying_profile:
            self._load_salad_policy()
        if tab == "Tokens":
            self._probe_tokens()
        if tab == "Prompt Assist":
            self._refresh_prompt_helper()
        if tab == "Prompt Catalog":
            self._refresh_prompt_catalog()
        if tab == "Logs":
            self._refresh_salad_logs()

    def _build_policy_tab(self) -> None:
        self._policy = ttk.Frame(self.nb, padding=10)
        self._policy.columnconfigure(1, weight=1)
        ttk.Label(
            self._policy,
            text="Salad group probes for the Config gateway. Load reads the live group (including portal edits). Apply PATCHes Salad — not the Docker image.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.var_pol_group = tk.StringVar(value="")
        ttk.Label(self._policy, text="Group").grid(row=1, column=0, sticky="w")
        ttk.Label(self._policy, textvariable=self.var_pol_group).grid(
            row=1, column=1, sticky="w", padx=6
        )
        bar = ttk.Frame(self._policy)
        bar.grid(row=2, column=0, columnspan=4, sticky="w", pady=6)
        ttk.Button(bar, text="Load from Salad", command=self._load_salad_policy).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Apply to Salad", command=self._apply_salad_policy).pack(
            side="left"
        )
        self._pol_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._pol_explain: dict[str, tk.StringVar] = {}
        r = 3
        for kind, title in (("startup", "Startup probe"), ("readiness", "Readiness probe")):
            box = ttk.LabelFrame(self._policy, text=title, padding=8)
            box.grid(row=r, column=0, columnspan=4, sticky="ew", pady=6)
            box.columnconfigure(1, weight=0)
            box.columnconfigure(2, weight=1)
            fields = {}
            for i, (key, label) in enumerate(
                (
                    ("path", "Path"),
                    ("port", "Port"),
                    ("initial_delay_seconds", "Initial delay (s)"),
                    ("period_seconds", "Period (s)"),
                    ("timeout_seconds", "Timeout (s)"),
                    ("failure_threshold", "Failure threshold (1–20)"),
                )
            ):
                ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=2)
                var = tk.StringVar()
                ttk.Entry(box, textvariable=var, width=24).grid(
                    row=i, column=1, sticky="w", padx=6, pady=2
                )
                var.trace_add(
                    "write", lambda *_a, k=kind: self._refresh_probe_explain(k)
                )
                fields[key] = var
            self._pol_vars[kind] = fields
            explain = tk.StringVar()
            self._pol_explain[kind] = explain
            ttk.Label(
                box,
                textvariable=explain,
                wraplength=520,
                justify="left",
            ).grid(row=0, column=2, rowspan=6, sticky="nw", padx=(16, 0))
            self._refresh_probe_explain(kind)
            r += 1
        extra = ttk.LabelFrame(self._policy, text="Placement / image", padding=8)
        extra.grid(row=r, column=0, columnspan=4, sticky="ew", pady=6)
        extra.columnconfigure(1, weight=1)
        ttk.Label(extra, text="Image").grid(row=0, column=0, sticky="w")
        self.var_pol_image = tk.StringVar()
        ttk.Entry(extra, textvariable=self.var_pol_image).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        self.var_pol_us = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            extra, text="US-only (country_codes=['us'])", variable=self.var_pol_us
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(extra, text="GPU classes").grid(row=2, column=0, sticky="nw")
        self._pol_gpu_frame = ttk.Frame(extra)
        self._pol_gpu_frame.grid(row=2, column=1, sticky="w", padx=6)
        self._pol_gpu_vars: dict[str, tk.BooleanVar] = {}
        self._pol_gpu_names: dict[str, str] = {}
        ttk.Button(
            extra,
            text="Reallocate instance (new node)…",
            command=self._reallocate_instance,
        ).grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))
        r += 1

    def _refresh_probe_explain(self, kind: str) -> None:
        var = self._pol_explain.get(kind)
        fields = self._pol_vars.get(kind)
        if var is None or fields is None:
            return
        raw = {k: v.get().strip() for k, v in fields.items()}
        var.set(salad_status.explain_probe(kind, raw))

    def _policy_from_form(self) -> dict:
        out = {"startup": {}, "readiness": {}}
        for kind, fields in self._pol_vars.items():
            out[kind] = {k: v.get().strip() for k, v in fields.items()}
        out["image"] = self.var_pol_image.get().strip()
        out["country_codes"] = ["us"] if self.var_pol_us.get() else []
        if self._pol_gpu_vars:
            out["gpu_classes"] = [
                gid for gid, var in self._pol_gpu_vars.items() if var.get()
            ]
        return out

    def _policy_to_form(self, policy: dict) -> None:
        self.var_pol_group.set(
            f"{policy.get('group_name') or ''}  v{policy.get('version') or '?'}"
        )
        for kind in ("startup", "readiness"):
            src = policy.get(kind) or {}
            for k, var in self._pol_vars[kind].items():
                var.set(str(src.get(k, "")))
        self.var_pol_image.set(str(policy.get("image") or ""))
        codes = [str(c).lower() for c in (policy.get("country_codes") or [])]
        self.var_pol_us.set("us" in codes)
        selected = set(str(x) for x in (policy.get("gpu_classes") or []))
        for gid, var in self._pol_gpu_vars.items():
            var.set(gid in selected)

    def _fill_gpu_checkboxes(self, classes: list[dict], selected: list[str]) -> None:
        frame = self._pol_gpu_frame
        for child in frame.winfo_children():
            child.destroy()
        self._pol_gpu_vars = {}
        self._pol_gpu_names = {}
        want = ("4090", "3090", "5090")
        shown = []
        for it in classes:
            name = str(it.get("name") or "")
            gid = str(it.get("id") or "")
            if not gid or not any(w in name for w in want):
                continue
            shown.append((gid, name))
        sel = set(str(x) for x in selected)
        for i, (gid, name) in enumerate(shown):
            var = tk.BooleanVar(value=gid in sel)
            ttk.Checkbutton(frame, text=name, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 12)
            )
            self._pol_gpu_vars[gid] = var
            self._pol_gpu_names[gid] = name

    def _load_salad_policy(self) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            self.status.set("Gateway URL is empty.")
            return

        def work() -> None:
            err = ""
            pol = None
            gpus: list[dict] = []
            try:
                key = self._salad_api_key()
                pol, err = salad_status.load_policy(gw, key)
                try:
                    gpus = salad_status.list_gpu_classes(key)
                except Exception:
                    gpus = []
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err or pol is None:
                    self.status.set(err or "Load policy failed")
                    self.log("error", f"Policy load: {err}")
                    return
                self._fill_gpu_checkboxes(gpus, list(pol.get("gpu_classes") or []))
                self._policy_to_form(pol)
                self.status.set(f"Loaded policy {pol.get('group_name')} v{pol.get('version')}")
                self.log(
                    "ok",
                    f"Policy loaded {pol.get('group_name')} v{pol.get('version')} "
                    f"startup delay={pol['startup'].get('initial_delay_seconds')}s "
                    f"fail={pol['startup'].get('failure_threshold')}",
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _apply_salad_policy(self) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            messagebox.showerror("Salad Studio", "Gateway URL is empty.")
            return
        policy = self._policy_from_form()

        def work() -> None:
            err = ""
            code = 0
            try:
                key = self._salad_api_key()
                code, data = salad_status.apply_policy(gw, key, policy)
                if code >= 400 or (isinstance(data, dict) and data.get("error")):
                    err = str(
                        (data or {}).get("title")
                        or (data or {}).get("error")
                        or data
                        or f"HTTP {code}"
                    )
                    if isinstance(data, dict) and data.get("errors"):
                        err = json.dumps(data.get("errors"))
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    self.status.set("Policy apply failed")
                    self.log("error", f"Policy apply: {err}")
                    messagebox.showerror("Salad Studio", err)
                    return
                self.status.set("Policy applied to Salad")
                self.log("ok", f"Policy applied HTTP {code}")
                self._load_salad_policy()

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _reallocate_instance(self) -> None:
        gw = self.var_gateway.get().strip()
        if not gw:
            messagebox.showerror("Salad Studio", "Gateway URL is empty.")
            return
        if not messagebox.askyesno(
            "Salad Studio",
            "Reallocate this group's instance onto a different Salad node?\n\n"
            "This dumps any in-flight Docker/HF download on the current machine.",
        ):
            return

        def work() -> None:
            err = ""
            code = 0
            try:
                key = self._salad_api_key()
                code, data = salad_status.reallocate_instance(gw, key)
                if code >= 400 or (isinstance(data, dict) and data.get("error")):
                    err = str(
                        (data or {}).get("error")
                        or (data or {}).get("title")
                        or data
                        or f"HTTP {code}"
                    )
            except Exception as e:
                err = str(e)

            def done() -> None:
                if err:
                    self.log("error", f"Reallocate: {err}")
                    messagebox.showerror("Salad Studio", err)
                    return
                self.log("ok", f"Reallocate HTTP {code}")
                self.status.set("Reallocate requested")
                self._check_salad_status(silent=True)

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _build_tokens_tab(self) -> None:
        self._tokens = ttk.Frame(self.nb, padding=10)
        self._tokens.columnconfigure(1, weight=1)
        ttk.Label(
            self._tokens,
            text="Secrets live in studio-tokens.json next to Salad Studio (not git). Empty slots are copied from ~/.config, or read from the provider's environment variable where one is configured. Generate sends the Salad key as Salad-Api-Key.",
            wraplength=760,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._token_entry: dict[str, tk.StringVar] = {}
        self._token_widgets: dict[str, ttk.Entry] = {}
        self._token_show: dict[str, tk.BooleanVar] = {}
        self._token_valid_dot: dict[str, tk.Label] = {}
        self._token_valid_word: dict[str, tk.StringVar] = {}
        self._token_state: dict[str, str] = {}
        r = 1
        for kind, label, _rel in tokens.TOKEN_SPECS:
            box = ttk.LabelFrame(self._tokens, text=label, padding=8)
            box.grid(row=r, column=0, columnspan=5, sticky="ew", pady=4)
            box.columnconfigure(1, weight=1)
            ttk.Label(box, text="Local file").grid(row=0, column=0, sticky="w")
            ttk.Label(box, text=str(tokens.LOCAL_PATH)).grid(
                row=0, column=1, columnspan=4, sticky="w", padx=6
            )
            ttk.Label(box, text="Default").grid(row=1, column=0, sticky="w")
            ttk.Label(box, text=tokens.default_label(kind)).grid(
                row=1, column=1, columnspan=4, sticky="w", padx=6
            )
            ttk.Label(box, text="Value").grid(row=2, column=0, sticky="w")
            entry_var = tk.StringVar()
            self._token_entry[kind] = entry_var
            entry = ttk.Entry(box, textvariable=entry_var, show="*")
            entry.grid(row=2, column=1, sticky="ew", padx=6, pady=2)
            self._token_widgets[kind] = entry
            show_var = tk.BooleanVar(value=False)
            self._token_show[kind] = show_var
            ttk.Checkbutton(
                box,
                text="Show",
                variable=show_var,
                command=lambda k=kind: self._toggle_token_visible(k),
            ).grid(row=2, column=2, padx=6)
            ttk.Button(
                box, text="Save", command=lambda k=kind: self._save_token(k)
            ).grid(row=2, column=3, padx=6)
            # Validity indicator: a real provider probe decides the dot colour.
            self._token_state[kind] = "unchecked"
            word = tk.StringVar(value="unchecked")
            self._token_valid_word[kind] = word
            dot = tk.Label(
                box,
                text="●",
                font=("Segoe UI Semibold", 12),
                bg=theme.PALETTE["bg"],
                fg=theme.PALETTE["unknown"],
            )
            dot.grid(row=2, column=4, sticky="w", padx=(6, 0))
            self._token_valid_dot[kind] = dot
            ttk.Label(box, textvariable=word).grid(row=2, column=5, sticky="w", padx=(4, 0))
            r += 1
        bar = ttk.Frame(self._tokens)
        bar.grid(row=r, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Check keys", command=self._probe_tokens).pack(side="left")
        ttk.Label(
            bar,
            text="green = the provider accepted the key; red = rejected; grey = not confirmed",
        ).pack(side="left", padx=(10, 0))
        self._refresh_token_fields()

    def _render_token_state(self, kind: str) -> None:
        state = self._token_state.get(kind, "unchecked")
        word = self._token_valid_word.get(kind)
        if word is not None:
            detail = self._token_detail.get(kind, "")
            word.set(f"{state} ({detail})" if detail else state)
        dot = self._token_valid_dot.get(kind)
        if dot is not None:
            try:
                dot.configure(fg=theme.PALETTE[tokens.state_color(state)])
            except (tk.TclError, KeyError):
                pass

    def _probe_tokens(self, kinds: list[str] | None = None) -> None:
        """Check keys against their providers in the background."""
        if self._token_probe_busy:
            return
        wanted = list(kinds or tokens.PROBE_SPECS.keys())
        self._token_probe_busy = True
        for kind in wanted:
            self._token_state[kind] = "checking"
            self._render_token_state(kind)

        def work() -> None:
            results = {kind: tokens.probe_token(kind) for kind in wanted}

            def done() -> None:
                self._token_probe_busy = False
                for kind, result in results.items():
                    self._token_state[kind] = str(result.get("state") or "unknown")
                    self._token_detail[kind] = str(result.get("detail") or "")
                    self._render_token_state(kind)
                self.log(
                    "debug",
                    "key check: "
                    + ", ".join(
                        f"{k}={results[k].get('state')}" for k in results
                    ),
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_token_visible(self, kind: str) -> None:
        show = "" if self._token_show[kind].get() else "*"
        self._token_widgets[kind].configure(show=show)

    def _refresh_token_fields(self) -> None:
        for kind, var in self._token_entry.items():
            var.set(tokens.read_token(kind))
            if kind in self._token_show:
                self._token_show[kind].set(False)
                self._toggle_token_visible(kind)

    def _save_token(self, kind: str) -> None:
        raw = self._token_entry[kind].get().strip()
        if not raw:
            messagebox.showinfo("Salad Studio", "Value is empty.")
            return
        try:
            path = tokens.write_token(kind, raw)
        except OSError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._log_secrets_cache = None
        self._token_entry[kind].set(raw)
        self.status.set(f"Saved {tokens.token_label(kind)} to {path}")
        self.log("ok", f"saved token {kind} ({len(raw)} chars) -> {path}")
        # A freshly saved key is unverified until its provider says otherwise.
        self._token_state[kind] = "unchecked"
        self._token_detail[kind] = ""
        self._render_token_state(kind)
        self._probe_tokens([kind])

    def _salad_api_key(self) -> str:
        return tokens.resolve_salad_key()

    def _build_loras_tab(self) -> None:
        self._loras = ttk.Frame(self.nb, padding=10)
        self._loras.columnconfigure(0, weight=1)
        self._loras.rowconfigure(0, weight=1)
        cols = ("id", "name", "version", "model", "source", "filename", "verified")
        self.lora_tree = ttk.Treeview(self._loras, columns=cols, show="headings", height=12)
        for col, heading, width in (
            ("id", "Id", 200),
            ("name", "Name", 160),
            ("version", "Version", 120),
            ("model", "Model", 110),
            ("source", "Source", 100),
            ("filename", "Comfy name", 180),
            ("verified", "Verified", 70),
        ):
            self.lora_tree.heading(col, text=heading)
            self.lora_tree.column(col, width=width)
        self.lora_tree.grid(row=0, column=0, sticky="nsew")
        self.lora_tree.bind("<<TreeviewSelect>>", self._on_lora_tree_select)
        add = ttk.LabelFrame(self._loras, text="Add / edit LoRA", padding=8)
        add.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        add.columnconfigure(1, weight=1)
        ttk.Label(add, text="Civitai / HF URL / civitai:id@version / local path").grid(
            row=0, column=0, sticky="w"
        )
        self.var_lora_ref = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_ref).grid(
            row=0, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Name (optional)").grid(row=1, column=0, sticky="w")
        self.var_lora_name = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_name).grid(
            row=1, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Filename (optional)").grid(row=2, column=0, sticky="w")
        self.var_lora_file = tk.StringVar()
        ttk.Entry(add, textvariable=self.var_lora_file).grid(
            row=2, column=1, sticky="ew", padx=6, pady=2
        )
        ttk.Label(add, text="Works with").grid(row=3, column=0, sticky="w")
        self.var_lora_family = tk.StringVar(value="Flux.2 Klein")
        family_box = ttk.Combobox(
            add,
            textvariable=self.var_lora_family,
            values=lora_store.FAMILY_CHOICES,
            state="readonly",
        )
        family_box.grid(row=3, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(add, text="Strength model").grid(row=4, column=0, sticky="w")
        self.var_lora_sm = tk.StringVar(value="1.0")
        ttk.Entry(add, textvariable=self.var_lora_sm, width=10).grid(
            row=4, column=1, sticky="w", padx=6, pady=2
        )
        ttk.Label(add, text="Strength clip").grid(row=5, column=0, sticky="w")
        self.var_lora_sc = tk.StringVar(value="1.0")
        ttk.Entry(add, textvariable=self.var_lora_sc, width=10).grid(
            row=5, column=1, sticky="w", padx=6, pady=2
        )
        row = ttk.Frame(add)
        row.grid(row=6, column=1, sticky="w", pady=6)
        ttk.Button(row, text="Add", command=self._on_add_lora).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Save edits", command=self._on_edit_lora).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Verify", command=self._on_verify_lora).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Verify unverified", command=self._on_verify_unverified).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(row, text="Remove extra", command=self._on_remove_lora).pack(side="left")

    def _build_editor_tab(self) -> None:
        self._editor = ttk.Frame(self.nb, padding=10)
        self._editor.columnconfigure(0, weight=1)
        self._editor.rowconfigure(0, weight=1)
        pane = ttk.Panedwindow(self._editor, orient=tk.HORIZONTAL)
        self._editor_pane = pane
        self._editor_sash_set = False
        pane.grid(row=0, column=0, sticky="nsew")
        pane.bind("<Map>", self._place_editor_sash)
        left = ttk.Frame(pane)
        self._editor_box = left
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.editor_text = tk.Text(left, wrap="none", height=16, font=("Consolas", 10))
        theme.style_text(self.editor_text)
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.editor_text.yview)
        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.editor_text.xview)
        self.editor_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.editor_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        self.editor_text.configure(state="normal")
        self._graph_stale = False
        self.editor_text.bind("<KeyRelease>", lambda _e: self._on_editor_edited())
        self.editor_text.bind("<FocusIn>", self._on_editor_focus_in)
        self.editor_text.bind("<Button-1>", self._on_editor_focus_in)
        left.bind("<Button-1>", self._on_editor_focus_in)
        self.editor_text.bind("<FocusOut>", self._on_editor_focus_out)
        self.editor_text.bind("<Control-v>", self._editor_paste)
        self.editor_text.bind("<Control-V>", self._editor_paste)
        self.editor_text.bind("<Shift-Insert>", self._editor_paste)
        self.editor_text.bind("<Control-c>", self._editor_copy)
        self.editor_text.bind("<Control-C>", self._editor_copy)
        self.editor_text.bind("<Control-x>", self._editor_cut)
        self.editor_text.bind("<Control-X>", self._editor_cut)
        for seq in ("<Control-a>", "<Control-A>", "<Control-Key-a>", "<<SelectAll>>"):
            self.editor_text.bind(seq, self._editor_select_all)
        self.bind_all("<Button-1>", self._on_click_outside_graph, add="+")
        right = ttk.Frame(pane)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.graph_pane = graph_view.GraphPane(right, on_swap=self._on_graph_swap)
        self.graph_pane.grid(row=0, column=0, sticky="nsew")
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        prompts = ttk.Frame(self._editor)
        self._editor_prompts = prompts
        prompts.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        # Positive on the left, negative on the right; the positive box is the
        # wider one because prompt text is longer than the negative list.
        prompts.columnconfigure(0, weight=66)
        prompts.columnconfigure(1, weight=34)
        prompts.rowconfigure(0, weight=1)
        pos_box = ttk.LabelFrame(prompts, text="Positive prompt", padding=8)
        pos_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        pos_box.columnconfigure(0, weight=1)
        pos_box.rowconfigure(0, weight=1)
        self.prompt_text = tk.Text(pos_box, wrap="word", height=5)
        theme.style_text(self.prompt_text)
        self.prompt_text.grid(row=0, column=0, sticky="nsew")
        self.prompt_text.insert(
            "1.0",
            "ArsMJStyle, Impressionism, cream paper, no signature, no watermark\n",
        )
        self.prompt_text.bind("<KeyRelease>", lambda _e: self._patch_editor_from_prompt())
        neg_box = ttk.LabelFrame(prompts, text="Negative prompt", padding=8)
        neg_box.grid(row=0, column=1, sticky="nsew")
        neg_box.columnconfigure(0, weight=1)
        neg_box.rowconfigure(0, weight=1)
        self.negative_text = tk.Text(neg_box, wrap="word", height=5)
        theme.style_text(self.negative_text)
        self.negative_text.grid(row=0, column=0, sticky="nsew")
        self.negative_text.bind("<KeyRelease>", lambda _e: self._patch_editor_from_prompt())
        bar = ttk.Frame(self._editor)
        self._editor_bar = bar
        bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Rebuild from Config", command=self._sync_editor).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Rebuild from JSON", command=self._rebuild_from_json).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Validate", command=self._validate_editor).pack(
            side="left", padx=(0, 6)
        )
        self.json_status = tk.StringVar(value="")
        self.json_status_lbl = ttk.Label(bar, textvariable=self.json_status)
        self.json_status_lbl.pack(side="left", padx=(12, 0))

    def _build_prompt_helper_tab(self) -> None:
        """Mirror the editor's prompts, edit an adjusted pair, ask DeepSeek for help."""
        self._helper = ttk.Frame(self.nb, padding=10)
        self._helper.columnconfigure(0, weight=1)
        self._helper.rowconfigure(1, weight=1)
        mirror = ttk.LabelFrame(
            self._helper, text="Current prompts (from the Prompt Editor)", padding=8
        )
        mirror.grid(row=0, column=0, sticky="ew")
        mirror.columnconfigure(0, weight=1)
        mirror.columnconfigure(1, weight=1)
        ttk.Label(mirror, text="Positive").grid(row=0, column=0, sticky="w")
        ttk.Label(mirror, text="Negative").grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.helper_editor_pos = tk.Text(mirror, wrap="word", height=4, state="disabled")
        theme.style_text(self.helper_editor_pos)
        self.helper_editor_pos.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(2, 0))
        self.helper_editor_neg = tk.Text(mirror, wrap="word", height=4, state="disabled")
        theme.style_text(self.helper_editor_neg)
        self.helper_editor_neg.grid(row=1, column=1, sticky="nsew", pady=(2, 0))

        adjusted = ttk.LabelFrame(
            self._helper, text="Adjusted prompts (edit these; Help rewrites them)", padding=8
        )
        adjusted.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        adjusted.columnconfigure(0, weight=1)
        adjusted.columnconfigure(1, weight=1)
        adjusted.rowconfigure(1, weight=1)
        ttk.Label(adjusted, text="Adjusted positive").grid(row=0, column=0, sticky="w")
        ttk.Label(adjusted, text="Adjusted negative").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        self.helper_adj_pos = tk.Text(adjusted, wrap="word", height=8)
        theme.style_text(self.helper_adj_pos)
        self.helper_adj_pos.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(2, 0))
        self.helper_adj_neg = tk.Text(adjusted, wrap="word", height=8)
        theme.style_text(self.helper_adj_neg)
        self.helper_adj_neg.grid(row=1, column=1, sticky="nsew", pady=(2, 0))

        issue_box = ttk.LabelFrame(
            self._helper,
            text="Image issue / problem (highest priority — the AI must fix this first)",
            padding=8,
        )
        issue_box.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        issue_box.columnconfigure(0, weight=1)
        self.helper_issue = tk.Text(issue_box, wrap="word", height=3)
        theme.style_text(self.helper_issue)
        self.helper_issue.grid(row=0, column=0, sticky="ew")
        image_row = ttk.Frame(issue_box)
        image_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.var_helper_image = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            image_row,
            text="Send the latest generated image",
            variable=self.var_helper_image,
            command=self._refresh_helper_image_label,
        ).pack(side="left")
        self.helper_image_lbl = ttk.Label(image_row, text="")
        self.helper_image_lbl.pack(side="left", padx=(10, 0))

        bar = ttk.Frame(self._helper)
        bar.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            bar, text="Refresh from Prompt Editor", command=self._refresh_prompt_helper
        ).pack(side="left", padx=(0, 6))
        self.helper_btn = ttk.Button(
            bar, text="Help (DeepSeek)", command=self._on_prompt_help
        )
        self.helper_btn.pack(side="left", padx=(0, 6))
        self.helper_local_btn = ttk.Button(
            bar, text="Help (local)", command=self._on_prompt_help_local
        )
        self.helper_local_btn.pack(side="left", padx=(0, 6))
        self.helper_commit_btn = ttk.Button(
            bar, text="Commit to Prompts + JSON", command=self._on_prompt_commit
        )
        self.helper_commit_btn.pack(side="left")
        self.helper_state = tk.StringVar(value="Idle")
        ttk.Label(bar, textvariable=self.helper_state).pack(side="left", padx=(12, 0))

        local_row = ttk.Frame(self._helper)
        local_row.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(local_row, text="Local LLM URL (LM Studio)").pack(side="left")
        self.var_helper_local_url = tk.StringVar(value=ai_helper.LOCAL_BASE_URL)
        ttk.Entry(local_row, textvariable=self.var_helper_local_url, width=38).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            local_row,
            text="OpenAI-compatible base, e.g. http://localhost:1234/v1",
        ).pack(side="left", padx=(8, 0))

        reply_box = ttk.LabelFrame(
            self._helper, text="DeepSeek reply (raw)", padding=8
        )
        reply_box.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        reply_box.columnconfigure(0, weight=1)
        reply_box.rowconfigure(0, weight=1)
        self.helper_reply = tk.Text(reply_box, wrap="word", height=7, state="disabled")
        theme.style_text(self.helper_reply)
        self.helper_reply.grid(row=0, column=0, sticky="nsew")
        self._set_helper_reply("")
        self._refresh_helper_image_label()

    def _latest_generated_image(self) -> Path | None:
        """The newest plate Salad Studio wrote (the one the artist just saw)."""
        plates = generator.list_history(OUT_DIR)
        if plates:
            return plates[0]
        return None

    def _refresh_helper_image_label(self) -> None:
        latest = self._latest_generated_image()
        if not self.var_helper_image.get():
            text = "off — no image is sent to DeepSeek"
        elif latest is None:
            text = "no generated image yet — nothing will be attached"
        else:
            text = f"attaching {latest.name}"
        try:
            self.helper_image_lbl.configure(text=text)
        except tk.TclError:
            pass

    def _set_helper_reply(self, text: str) -> None:
        widget = self.helper_reply
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _set_helper_mirror(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text or "")
        widget.configure(state="disabled")

    def _refresh_prompt_helper(self) -> None:
        """Copy the Prompt Editor's current prompts into the read-only mirror."""
        self._set_helper_mirror(
            self.helper_editor_pos, self.prompt_text.get("1.0", "end-1c")
        )
        self._set_helper_mirror(
            self.helper_editor_neg, self.negative_text.get("1.0", "end-1c")
        )
        self._refresh_helper_image_label()

    def _helper_inputs(self) -> dict[str, str]:
        """The context inputs, straight from the live widgets."""
        return {
            "editor_positive": self.prompt_text.get("1.0", "end-1c").strip(),
            "editor_negative": self.negative_text.get("1.0", "end-1c").strip(),
            "adjusted_positive": self.helper_adj_pos.get("1.0", "end-1c").strip(),
            "adjusted_negative": self.helper_adj_neg.get("1.0", "end-1c").strip(),
            "request_json": self.editor_text.get("1.0", "end-1c").strip(),
            "issue": self.helper_issue.get("1.0", "end-1c").strip(),
        }

    def _helper_findings(self, inputs: dict[str, str]) -> tuple[str, list[dict]]:
        """Resolve the request's weights for the AI (local first, then online)."""
        try:
            payload = generator.parse_request_json(inputs["request_json"])
        except (ValueError, json.JSONDecodeError) as e:
            self.log("warn", f"Prompt Assist: request JSON is invalid ({e})")
            return f"(the Prompt Editor JSON could not be parsed: {e})", []
        findings = ref_check.resolve_refs(payload)
        return ref_check.format_findings(findings), findings

    def _on_prompt_help(self) -> None:
        """Help from DeepSeek (needs the key on the Tokens tab)."""
        self._start_helper_call("deepseek")

    def _on_prompt_help_local(self) -> None:
        """Help from the LLM served by the local LM Studio URL."""
        self._start_helper_call("local")

    def _start_helper_call(self, backend: str) -> None:
        if self._helper_busy:
            return
        inputs = self._helper_inputs()
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        key = ""
        if backend == "deepseek":
            key = tokens.read_token("deepseek")
            if not key:
                self.helper_state.set("No DeepSeek key — save one on the Tokens tab")
                self._set_helper_reply(
                    "No DeepSeek key is saved. Add it on the Tokens tab, then press "
                    "Help again."
                )
                self.log("error", "Prompt Assist: DeepSeek key is empty")
                return
        # Read the URL here: the worker thread must not touch Tk widgets.
        local_url = self.var_helper_local_url.get()
        self._helper_busy = True
        for btn in (self.helper_btn, self.helper_local_btn):
            try:
                btn.configure(state="disabled")
            except tk.TclError:
                pass
        self.helper_state.set(f"Asking {label}…")
        self.status.set(f"Prompt Assist: asking {label}…")
        image = self._latest_generated_image() if self.var_helper_image.get() else None
        if image is not None:
            self.log("info", f"Prompt Assist: attaching {image.name}")
        elif self.var_helper_image.get():
            self.log("warn", "Prompt Assist: no generated image to attach")
        self.log("info", f"Prompt Assist: {label} help requested")

        def work() -> None:
            findings_text = ""
            try:
                findings_text, findings = self._helper_findings(inputs)
                unresolved = ref_check.unresolved(findings)
                if unresolved:
                    self.log(
                        "warn",
                        "Prompt Assist: unresolved weights "
                        + ", ".join(str(f.get("name")) for f in unresolved),
                    )
                if backend == "deepseek":
                    out = ai_helper.help_with_prompts(
                        key, findings=findings_text, image_path=image, **inputs
                    )
                else:
                    out = ai_helper.help_with_prompts_local(
                        url=local_url, findings=findings_text, image_path=image, **inputs
                    )
                self.after(0, lambda: self._helper_done(out, None, backend))
            except ai_helper.ReplyError as e:
                self.after(0, lambda err=e: self._helper_done(None, err, backend))
            except Exception as e:  # noqa: BLE001 - surface every failure in the page
                self.after(0, lambda err=e: self._helper_done(None, err, backend))

        threading.Thread(target=work, daemon=True).start()

    def _on_prompt_commit(self) -> None:
        """Write the adjusted prompts into the editor's prompt boxes and its JSON."""
        positive = self.helper_adj_pos.get("1.0", "end-1c").strip()
        negative = self.helper_adj_neg.get("1.0", "end-1c").strip()
        if not positive and not negative:
            messagebox.showinfo(
                "Salad Studio",
                "The adjusted prompts are empty — ask DeepSeek for help first.",
            )
            return
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            generator.parse_request_json(raw)
            patchable = True
        except (ValueError, json.JSONDecodeError):
            patchable = False
        # The prompt boxes are the live source the JSON is patched from, so
        # writing them and re-running the shipped patch does both in one step.
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", positive)
        self.negative_text.delete("1.0", "end")
        self.negative_text.insert("1.0", negative)
        self._patch_editor_from_prompt()
        self._refresh_prompt_helper()
        if patchable:
            self.status.set("Prompt Assist: committed to the prompts and the JSON")
            self.log("ok", "Prompt Assist: adjusted prompts committed to the editor JSON")
        else:
            # _patch_editor_from_prompt rebuilds the graph from Prompt Settings
            # when the editor JSON cannot take the text, so say that out loud.
            self.status.set("Prompt Assist: committed (the JSON was rebuilt)")
            self.log(
                "warn",
                "Prompt Assist: the editor JSON was rebuilt from Prompt Settings "
                "because it could not be patched",
            )

    def _helper_done(
        self, out: dict | None, err: Exception | None, backend: str = "deepseek"
    ) -> None:
        self._helper_busy = False
        label = "DeepSeek" if backend == "deepseek" else "the local model"
        for btn in (self.helper_btn, self.helper_local_btn):
            try:
                btn.configure(state="normal")
            except tk.TclError:
                pass
        if isinstance(err, ai_helper.ReplyError):
            # Never blank the boxes: show the model's raw words instead.
            self._set_helper_reply(err.raw or str(err))
            self.helper_state.set("Reply was not usable — raw text shown below")
            self.status.set("Prompt Assist: reply could not be parsed")
            self.log("warn", f"Prompt Assist: unparsable reply from {label} ({err})")
            return
        if err is not None:
            self._set_helper_reply(f"{type(err).__name__}: {err}")
            self.helper_state.set(f"{label} failed: {err}")
            self.status.set(f"Prompt Assist: {label} call failed")
            self.log("error", f"Prompt Assist ({label}): {err}")
            return
        assert out is not None
        # A reply that is missing one of the two prompts — a reasoning model
        # that restarted its JSON can leave one empty — must not wipe what the
        # artist typed in that box.
        blank: list[str] = []
        for widget, value, name in (
            (self.helper_adj_pos, out.get("positive") or "", "positive"),
            (self.helper_adj_neg, out.get("negative") or "", "negative"),
        ):
            if str(value).strip():
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
            else:
                blank.append(name)
        if blank:
            self.log(
                "warn",
                f"Prompt Assist: the {label} reply carried no "
                f"{' or '.join(blank)} prompt — what you had there is kept",
            )
        self._set_helper_reply(str(out.get("raw") or ""))
        found = str(out.get("issue") or "").strip()
        if found:
            self.helper_state.set(f"Adjusted prompts updated — image issue: {found[:140]}")
            self.log("info", f"Prompt Assist: {label} saw — {found}")
        else:
            self.helper_state.set(f"Adjusted prompts updated from {label}")
        self.status.set("Prompt Assist: adjusted prompts updated")
        model = str(out.get("model") or ai_helper.MODEL)
        self.log("ok", f"Prompt Assist: {label} updated the adjusted prompts ({model})")
        continued = int(out.get("continued") or 0)
        if continued:
            # The API cut the answer at the token limit and the rest was asked
            # for, so the boxes hold the whole reply rather than its first part.
            self.log(
                "warn",
                f"Prompt Assist: the {label} reply hit the token limit and was "
                f"completed in {continued} continuation(s)",
            )

    def _build_prompt_catalog_tab(self) -> None:
        self._catalog = ttk.Frame(self.nb, padding=10)
        self._catalog.columnconfigure(0, weight=1)
        self._catalog.rowconfigure(1, weight=1)
        form = ttk.Frame(self._catalog)
        form.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=2)
        ttk.Label(form, text="Short name").grid(row=0, column=0, sticky="w")
        self.var_cat_name = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_cat_name).grid(
            row=0, column=1, sticky="ew", padx=(6, 12)
        )
        ttk.Label(form, text="Description").grid(row=0, column=2, sticky="w")
        self.var_cat_desc = tk.StringVar()
        ttk.Entry(form, textvariable=self.var_cat_desc).grid(
            row=0, column=3, sticky="ew", padx=(6, 0)
        )
        cols = ("when", "name", "description", "preview", "stats")
        self.catalog_tree = ttk.Treeview(
            self._catalog, columns=cols, show="headings", height=16
        )
        for col, heading, width, stretch in (
            ("when", "Added", 130, False),
            ("name", "Short name", 180, False),
            ("description", "Description", 260, True),
            ("preview", "Prompt", 380, True),
            ("stats", "Graph", 300, True),
        ):
            self.catalog_tree.heading(col, text=heading)
            self.catalog_tree.column(col, width=width, stretch=stretch)
        self.catalog_tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(
            self._catalog, orient="vertical", command=self.catalog_tree.yview
        )
        self.catalog_tree.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.catalog_tree.bind("<<TreeviewSelect>>", lambda _e: self._fill_catalog_form())
        self.catalog_tree.bind("<Double-1>", lambda _e: self._on_catalog_load())
        bar = ttk.Frame(self._catalog)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            bar, text="Copy from Prompt Editor", command=self._on_catalog_add
        ).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Update JSON", command=self._on_catalog_update_json).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(
            bar, text="Save name / description", command=self._on_catalog_save_meta
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            bar, text="Load into Prompt Editor", command=self._on_catalog_load
        ).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Delete", command=self._on_catalog_delete).pack(side="left")
        self.catalog_status = tk.StringVar(value="")
        ttk.Label(self._catalog, textvariable=self.catalog_status).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        self._refresh_prompt_catalog()

    def _selected_catalog_id(self) -> str | None:
        sel = self.catalog_tree.selection()
        return str(sel[0]) if sel else None

    def _fill_catalog_form(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            return
        self.var_cat_name.set(str(entry.get("name") or ""))
        self.var_cat_desc.set(str(entry.get("description") or ""))

    def _editor_payload_for_catalog(self) -> dict | None:
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            return generator.parse_request_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            messagebox.showerror("Salad Studio", f"Prompt Editor JSON is invalid: {e}")
            return None

    def _refresh_prompt_catalog(self) -> None:
        tree = self.catalog_tree
        keep = self._selected_catalog_id()
        for child in tree.get_children():
            tree.delete(child)
        for entry in prompt_catalog.list_entries():
            req = entry.get("request") if isinstance(entry.get("request"), dict) else None
            tree.insert(
                "",
                "end",
                iid=str(entry.get("id") or ""),
                values=(
                    time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(int(entry.get("ts") or 0))
                    ),
                    str(entry.get("name") or ""),
                    str(entry.get("description") or ""),
                    prompt_history.preview(prompt_history.prompt_text_of(req)),
                    prompt_catalog.entry_stats(entry),
                ),
            )
        if keep and keep in tree.get_children():
            tree.selection_set(keep)

    def _on_catalog_add(self) -> None:
        name = self.var_cat_name.get().strip()
        if not name:
            messagebox.showinfo("Salad Studio", "Give the prompt a short name first.")
            return
        payload = self._editor_payload_for_catalog()
        if payload is None:
            return
        try:
            entry = prompt_catalog.add_entry(name, self.var_cat_desc.get(), payload)
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_tree.selection_set(str(entry["id"]))
        self.catalog_status.set(f"Copied '{entry['name']}' from the Prompt Editor")
        self.status.set(f"Catalog: added {entry['name']}")
        self.log("ok", f"catalog + {entry['name']}  {prompt_catalog.entry_stats(entry)}")

    def _on_catalog_update_json(self) -> None:
        entry_id = self._selected_catalog_id()
        if not entry_id:
            messagebox.showinfo("Salad Studio", "Select a catalog entry first.")
            return
        payload = self._editor_payload_for_catalog()
        if payload is None:
            return
        try:
            entry = prompt_catalog.update_entry(entry_id, request=payload)
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Updated the JSON of '{entry['name']}'")
        self.status.set(f"Catalog: updated {entry['name']}")
        self.log("ok", f"catalog json <- editor  {entry['name']}")

    def _on_catalog_save_meta(self) -> None:
        entry_id = self._selected_catalog_id()
        if not entry_id:
            messagebox.showinfo("Salad Studio", "Select a catalog entry first.")
            return
        try:
            entry = prompt_catalog.update_entry(
                entry_id, name=self.var_cat_name.get(), description=self.var_cat_desc.get()
            )
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Saved '{entry['name']}'")
        self.status.set(f"Catalog: saved {entry['name']}")
        self.log("ok", f"catalog name/description saved  {entry['name']}")

    def _on_catalog_load(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            messagebox.showinfo("Salad Studio", "Select a catalog entry to load.")
            return
        self._set_editor_payload(entry["request"], remember=False)
        self.catalog_status.set(f"Loaded '{entry['name']}' into the Prompt Editor")
        self.status.set(f"Catalog: loaded {entry['name']}")
        self.log(
            "ok",
            f"catalog -> editor  {entry['name']}  {prompt_catalog.entry_stats(entry)}",
        )

    def _on_catalog_delete(self) -> None:
        entry = prompt_catalog.get_entry(self._selected_catalog_id() or "")
        if entry is None:
            messagebox.showinfo("Salad Studio", "Select a catalog entry to delete.")
            return
        if not messagebox.askyesno(
            "Salad Studio", f"Delete the catalog entry '{entry['name']}'?"
        ):
            return
        prompt_catalog.remove_entry(str(entry["id"]))
        self._refresh_prompt_catalog()
        self.catalog_status.set(f"Deleted '{entry['name']}'")
        self.status.set(f"Catalog: deleted {entry['name']}")
        self.log("warn", f"catalog - {entry['name']}")

    def _build_import_tab(self) -> None:
        self._import = ttk.Frame(self.nb, padding=10)
        self._import.columnconfigure(0, weight=1)
        self._import.rowconfigure(1, weight=1)
        self._import.rowconfigure(2, weight=2)
        url_box = ttk.LabelFrame(
            self._import,
            text="Civitai image URL (Copy All + Comfy nodes when the post has them)",
            padding=8,
        )
        url_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        url_box.columnconfigure(1, weight=1)
        ttk.Label(url_box, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.var_imp_image_url = tk.StringVar(value="")
        ttk.Entry(url_box, textvariable=self.var_imp_image_url).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            url_box, text="Fetch from Civitai", command=self._on_fetch_civitai_image
        ).grid(row=0, column=2, sticky="e")
        meta_box = ttk.LabelFrame(
            self._import,
            text="Civitai generation data (prompt + Steps / CFG, or Sampler / Seed / Model)",
            padding=8,
        )
        meta_box.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        meta_box.columnconfigure(0, weight=1)
        meta_box.rowconfigure(0, weight=1)
        self.import_meta = tk.Text(meta_box, wrap="word", height=8, font=("Segoe UI", 10))
        theme.style_text(self.import_meta)
        self.import_meta.grid(row=0, column=0, sticky="nsew")
        wf_box = ttk.LabelFrame(
            self._import,
            text="Comfy workflow JSON (paste is held in memory — Clear Import if the UI crawls)",
            padding=8,
        )
        wf_box.grid(row=2, column=0, sticky="nsew")
        wf_box.columnconfigure(0, weight=1)
        wf_box.rowconfigure(0, weight=1)
        self._import_workflow_stash = ""
        self.import_workflow = tk.Text(
            wf_box, wrap="word", height=12, font=("Consolas", 9), undo=False
        )
        theme.style_text(self.import_workflow)
        yscroll = ttk.Scrollbar(
            wf_box, orient="vertical", command=self.import_workflow.yview
        )
        self.import_workflow.configure(yscrollcommand=yscroll.set)
        self.import_workflow.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        knobs = ttk.LabelFrame(
            self._import,
            text="Graph knobs (applied on Convert — empty = from paste; set to override)",
            padding=8,
        )
        knobs.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.var_imp_cfg = tk.StringVar(value="")
        self.var_imp_seed = tk.StringVar(value="")
        self.var_imp_steps = tk.StringVar(value="")
        self.var_imp_width = tk.StringVar(value="")
        self.var_imp_height = tk.StringVar(value="")
        self.var_imp_sched = tk.StringVar(value="Flux2 (Klein)")
        self.var_imp_unet = tk.StringVar(value="")
        fields = (
            ("CFG", self.var_imp_cfg),
            ("Seed", self.var_imp_seed),
            ("Steps", self.var_imp_steps),
            ("Width", self.var_imp_width),
            ("Height", self.var_imp_height),
        )
        for i, (lab, var) in enumerate(fields):
            ttk.Label(knobs, text=lab).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            ttk.Entry(knobs, textvariable=var, width=14).grid(
                row=0, column=i * 2 + 1, sticky="w", padx=(0, 12)
            )
        ttk.Label(knobs, text="Scheduler").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            knobs,
            textvariable=self.var_imp_sched,
            values=("Flux2 (Klein)", "Simple (Civitai)"),
            state="readonly",
            width=20,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(knobs, text="Checkpoint").grid(row=1, column=4, sticky="w", pady=(6, 0), padx=(12, 4))
        ttk.Combobox(
            knobs,
            textvariable=self.var_imp_unet,
            values=("",) + request_json.UNET_LABELS,
            state="readonly",
            width=16,
        ).grid(row=1, column=5, sticky="w", pady=(6, 0))
        iss_box = ttk.LabelFrame(
            self._import,
            text="Salad replica issues",
            padding=8,
        )
        iss_box.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        iss_box.columnconfigure(0, weight=1)
        iss_box.rowconfigure(0, weight=1)
        self.import_issues = tk.Text(
            iss_box, wrap="word", height=8, font=("Segoe UI", 10), undo=False
        )
        theme.style_text(self.import_issues)
        self.import_issues.grid(row=0, column=0, sticky="nsew")
        self.import_issues.configure(state="disabled")
        bar = ttk.Frame(self._import)
        bar.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Fill knobs from paste", command=self._fill_import_knobs).pack(
            side="left"
        )
        ttk.Button(
            bar, text="Convert to Prompt Editor", command=self._on_import_civitai
        ).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Clear Import", command=self._clear_import).pack(
            side="left", padx=(8, 0)
        )
        self.import_meta.bind("<KeyRelease>", lambda _e: self._schedule_fill_import_knobs())
        # Huge Comfy JSON in a Text widget crawls the whole Tk app. Keep it
        # in memory and show a short summary; do not parse on every keystroke.
        self.import_workflow.bind("<<Paste>>", self._on_import_workflow_paste)

    def _set_editor_payload(self, payload: dict, *, remember: bool) -> None:
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._rebuild_from_json(remember=remember)
        self._refresh_graph()
        self.nb.select(self._editor)

    def _cancel_fill_import_knobs(self) -> None:
        if getattr(self, "_imp_fill_after", None):
            try:
                self.after_cancel(self._imp_fill_after)
            except Exception:
                pass
            self._imp_fill_after = None

    def _schedule_fill_import_knobs(self) -> None:
        self._cancel_fill_import_knobs()
        self._imp_fill_after = self.after(400, lambda: self._fill_import_knobs(only_empty=True, quiet=True))

    def _on_import_workflow_paste(self, _event=None):
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            return None
        raw = (clip or "").strip()
        if not raw:
            return None
        self._stash_import_workflow(raw)
        self._schedule_fill_import_knobs()
        return "break"

    def _stash_import_workflow(self, raw: str) -> None:
        text = (raw or "").strip()
        self._import_workflow_stash = text
        n = len(text)
        self.import_workflow.delete("1.0", "end")
        if not text:
            return
        self.import_workflow.insert(
            "1.0",
            f"[Comfy workflow JSON in memory — {n:,} characters]\n"
            "Not shown in this box so the UI stays fast. Convert uses this paste.\n"
            "Clear Import to drop it.",
        )

    def _import_workflow_text(self) -> str:
        stashed = (self._import_workflow_stash or "").strip()
        if stashed:
            return stashed
        text = self.import_workflow.get("1.0", "end").strip()
        if text.startswith("[Comfy workflow JSON in memory"):
            return ""
        return text

    def _set_import_issues(
        self, issues: list[str] | None, notes: list[str] | None = None
    ) -> None:
        widget = self.import_issues
        notes = notes or []
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if issues:
            lines = ["This graph cannot run on the Salad Klein replica:", ""]
            lines.extend(f"• {item}" for item in issues)
            if notes:
                lines.append("")
                lines.extend(f"• {item}" for item in notes)
            widget.insert("1.0", "\n".join(lines))
            widget.configure(foreground=theme.PALETTE["accent"])
        elif notes:
            widget.insert(
                "1.0",
                "Warnings:\n\n" + "\n".join(f"• {item}" for item in notes),
            )
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        elif issues is None:
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        else:
            widget.insert("1.0", "No replica issues.")
            widget.configure(foreground=theme.PALETTE["fg_muted"])
        widget.configure(state="disabled")

    def _refresh_import_issues(self) -> list[str]:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        if not wf and not meta:
            self._set_import_issues(None)
            return []
        try:
            blocking, notes = comfy_import.inspect_pastes(meta, wf)
        except Exception as e:
            blocking, notes = [f"Could not inspect paste: {e}"], []
        self._set_import_issues(blocking, notes)
        return blocking

    def _clear_import(self) -> None:
        self._cancel_fill_import_knobs()
        self._import_workflow_stash = ""
        self.import_meta.delete("1.0", "end")
        self.import_workflow.delete("1.0", "end")
        self.var_imp_image_url.set("")
        self.var_imp_cfg.set("")
        self.var_imp_seed.set("")
        self.var_imp_steps.set("")
        self.var_imp_width.set("")
        self.var_imp_height.set("")
        self.var_imp_sched.set("Flux2 (Klein)")
        self.var_imp_unet.set("")
        self._set_import_issues(None)
        self.status.set("Import paste cleared")

    def _on_fetch_civitai_image(self) -> None:
        raw = (self.var_imp_image_url.get() or "").strip()
        if not raw:
            raw = self.import_meta.get("1.0", "end").strip()
        iid = comfy_import.ls.civitai_image_id(raw)
        if not iid and raw.isdigit():
            iid = raw
        if not iid:
            messagebox.showerror(
                "Salad Studio",
                "Paste a Civitai image URL like https://civitai.com/images/130704876",
            )
            return
        self.status.set(f"Fetching Civitai image {iid}…")
        self.update_idletasks()
        try:
            pastes = comfy_import.fetch_civitai_image_pastes(iid)
        except Exception as e:
            self.status.set("Civitai fetch failed")
            self.log("error", f"fetch image {iid}: {e}")
            messagebox.showerror("Salad Studio", str(e))
            return
        self.var_imp_image_url.set(f"https://civitai.com/images/{iid}")
        self.import_meta.delete("1.0", "end")
        self.import_meta.insert("1.0", pastes["metadata"])
        wf = str(pastes.get("workflow") or "").strip()
        tool = str(pastes.get("tool") or "").strip()
        if wf:
            self._stash_import_workflow(wf)
        else:
            self._import_workflow_stash = ""
            self.import_workflow.delete("1.0", "end")
        self._fill_import_knobs(only_empty=False, quiet=True)
        self._set_import_issues([])
        if "draw things" in tool.lower():
            self.status.set(f"Fetched {iid} (Draw Things)")
        elif wf:
            self.status.set(f"Fetched {iid} (Comfy)")
        else:
            self.status.set(f"Fetched {iid}")
        self.log("ok", f"fetched civitai image {iid} tool={tool or '-'}")

    def _fill_import_knobs(self, *, only_empty: bool = False, quiet: bool = False) -> None:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        if not wf and not meta:
            self._set_import_issues(None)
            return
        try:
            knobs = comfy_import.knobs_from_sources(meta, wf)
        except Exception as e:
            self._set_import_issues([f"Could not parse paste: {e}"])
            if not quiet:
                messagebox.showerror("Salad Studio", f"Could not parse paste: {e}")
            return
        extra_notes: list[str] = []
        try:
            blocking, notes = comfy_import.inspect_pastes(meta, wf)
        except Exception as e:
            blocking, notes = [f"Could not inspect paste: {e}"], []
        self._set_import_issues(blocking, notes + extra_notes)

        def _set(var, value) -> None:
            if value in (None, ""):
                return
            if only_empty and var.get().strip():
                return
            var.set(str(value))

        _set(self.var_imp_cfg, knobs.get("cfg"))
        _set(self.var_imp_seed, knobs.get("seed"))
        _set(self.var_imp_steps, knobs.get("steps"))
        _set(self.var_imp_width, knobs.get("width"))
        _set(self.var_imp_height, knobs.get("height"))
        if knobs.get("scheduler") and (
            not only_empty
            or self.var_imp_sched.get().strip() in ("", "Flux2 (Klein)")
        ):
            self.var_imp_sched.set(self._scheduler_label(str(knobs.get("scheduler"))))
        if knobs.get("unet") and (not only_empty or not self.var_imp_unet.get().strip()):
            self.var_imp_unet.set(request_json.unet_label(str(knobs.get("unet"))))
        if not quiet:
            self.status.set("Import knobs filled from paste")

    def _import_knobs_from_form(self) -> dict:
        def _int(var, default=None):
            raw = var.get().strip()
            if not raw:
                return default
            try:
                return int(float(raw))
            except ValueError:
                return default

        def _num(var, default=None):
            raw = var.get().strip()
            if not raw:
                return default
            try:
                v = float(raw)
                return int(v) if v == int(v) else v
            except ValueError:
                return default

        return {
            "cfg": _num(self.var_imp_cfg, None),
            "seed": _int(self.var_imp_seed, None),
            "steps": _int(self.var_imp_steps, None),
            "width": _int(self.var_imp_width, None),
            "height": _int(self.var_imp_height, None),
            "scheduler": self._scheduler_id_from_label(self.var_imp_sched.get()),
            "unet": (
                request_json.normalize_unet(self.var_imp_unet.get())
                if self.var_imp_unet.get().strip()
                else None
            ),
        }

    def _scheduler_id_from_label(self, raw: str) -> str:
        return "simple" if "simple" in (raw or "").lower() else "flux2"

    def _on_import_civitai(self) -> None:
        wf = self._import_workflow_text()
        meta = self.import_meta.get("1.0", "end").strip()
        url = (self.var_imp_image_url.get() or "").strip()
        if url and comfy_import.ls.civitai_image_id(url) and not comfy_import.ls.civitai_image_id(meta):
            meta = url + "\n" + meta
        try:
            self._fill_import_knobs(only_empty=True, quiet=True)
            payload = comfy_import.import_to_request(
                workflow_text=wf,
                metadata_text=meta,
                knobs=self._import_knobs_from_form(),
            )
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            self.log("error", f"Import failed: {e}")
            messagebox.showerror("Salad Studio", f"Cannot convert Civitai paste: {e}")
            return
        self._stash_import_workflow("")
        census = comfy_import.comfy_convert_census_note(wf, payload)
        warn = ([census] if census else []) + list(comfy_import.replica_issues(payload))
        self._set_import_issues([], warn)
        self._set_editor_payload(payload, remember=True)
        stats = prompt_history.request_stats(payload)
        self.status.set(census or "Imported Civitai workflow to Prompt Editor")
        self.log("ok", f"imported Civitai paste  {stats}" + (f"  {census}" if census else ""))

    def _build_prompt_history_tab(self) -> None:
        self._prompt_hist = ttk.Frame(self.nb, padding=10)
        self._prompt_hist.columnconfigure(0, weight=1)
        self._prompt_hist.rowconfigure(0, weight=1)
        cols = ("when", "profile", "preview", "stats")
        style = ttk.Style(self)
        style.configure("Hist.Treeview", rowheight=52)
        self.prompt_hist_tree = ttk.Treeview(
            self._prompt_hist,
            columns=cols,
            show="tree headings",
            height=16,
            style="Hist.Treeview",
        )
        self.prompt_hist_tree.heading("#0", text="")
        self.prompt_hist_tree.column("#0", width=56, minwidth=52, stretch=False, anchor="center")
        self.prompt_hist_tree.heading("when", text="When")
        self.prompt_hist_tree.heading("profile", text="Profile")
        self.prompt_hist_tree.heading("preview", text="Prompt")
        self.prompt_hist_tree.heading("stats", text="Graph")
        self.prompt_hist_tree.column("when", width=140, stretch=False)
        self.prompt_hist_tree.column("profile", width=100, stretch=False)
        self.prompt_hist_tree.column("preview", width=480, stretch=True)
        self.prompt_hist_tree.column("stats", width=380, stretch=True)
        self._hist_photos: list = []
        yscroll = ttk.Scrollbar(
            self._prompt_hist, orient="vertical", command=self.prompt_hist_tree.yview
        )
        self.prompt_hist_tree.configure(yscrollcommand=yscroll.set)
        self.prompt_hist_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.prompt_hist_tree.bind("<Double-1>", lambda _e: self._reuse_prompt_history())
        bar = ttk.Frame(self._prompt_hist)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(bar, text="Reuse", command=self._reuse_prompt_history).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(bar, text="Delete", command=self._delete_prompt_history).pack(
            side="left"
        )
        self._refresh_prompt_history()

    def _refresh_prompt_history(self) -> None:
        tree = self.prompt_hist_tree
        for child in tree.get_children():
            tree.delete(child)
        self._hist_photos = []
        try:
            from PIL import Image, ImageTk
        except ImportError:
            Image = ImageTk = None  # type: ignore[misc, assignment]
        for i, row in enumerate(prompt_history.list_prompts()):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(row.get("ts") or 0)))
            req = row.get("request") if isinstance(row.get("request"), dict) else None
            stats = prompt_history.request_stats(req) if req else ""
            photo = None
            raw = str(row.get("image") or "").strip()
            if raw and Image is not None and Path(raw).is_file():
                try:
                    im = Image.open(raw)
                    photo = ImageTk.PhotoImage(im)
                    self._hist_photos.append(photo)
                except OSError:
                    photo = None
            tree.insert(
                "",
                "end",
                iid=str(i),
                image=photo or "",
                values=(
                    when,
                    str(row.get("profile") or ""),
                    prompt_history.preview(str(row.get("text") or "")),
                    stats,
                ),
            )

    def _selected_history_index(self) -> int | None:
        sel = self.prompt_hist_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _reuse_prompt_history(self) -> None:
        idx = self._selected_history_index()
        rows = prompt_history.list_prompts()
        if idx is None or idx < 0 or idx >= len(rows):
            messagebox.showinfo("Salad Studio", "Select a prompt to reuse.")
            return
        row = rows[idx]
        req = row.get("request") if isinstance(row.get("request"), dict) else None
        if req is not None:
            self._set_editor_payload(req, remember=False)
            self.status.set("Reused request JSON from history")
            self.log(
                "ok",
                f"reused prompt history #{idx}  {prompt_history.request_stats(req)}",
            )
            return
        text = str(row.get("text") or "")
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", text)
        self._sync_editor()
        self.nb.select(self._editor)
        self.status.set("Reused prompt from history")
        self.log("ok", f"reused prompt history #{idx} ({len(text)} chars)")

    def _delete_prompt_history(self) -> None:
        idx = self._selected_history_index()
        if idx is None:
            messagebox.showinfo("Salad Studio", "Select a prompt to delete.")
            return
        prompt_history.remove_at(idx)
        self._refresh_prompt_history()
        self.log("info", f"deleted prompt history #{idx}")

    def _remember_request(self, payload: dict | None = None) -> None:
        body = payload
        if body is None:
            raw = self.editor_text.get("1.0", "end").strip()
            try:
                body = generator.parse_request_json(raw)
            except (ValueError, json.JSONDecodeError, TypeError):
                body = None
        if isinstance(body, dict) and prompt_history.add_request(
            body,
            profile=self.var_name.get().strip(),
            gateway=self.var_gateway.get().strip(),
        ):
            self._refresh_prompt_history()
            return
        text = self.prompt_text.get("1.0", "end").strip()
        if prompt_history.add_prompt(text):
            self._refresh_prompt_history()

    def _build_logs_tab(self) -> None:
        self._logs = ttk.Frame(self.nb, padding=10)
        self._logs.columnconfigure(0, weight=1)
        self._logs.rowconfigure(0, weight=1)
        paned = ttk.Panedwindow(self._logs, orient="vertical")
        paned.grid(row=0, column=0, sticky="nsew")
        salad_box = ttk.LabelFrame(paned, text="Salad container logs (active gateway)", padding=4)
        salad_box.columnconfigure(0, weight=1)
        salad_box.rowconfigure(0, weight=1)
        self.salad_log_text = tk.Text(salad_box, wrap="word", height=10, state="disabled")
        theme.style_text(self.salad_log_text)
        sscroll = ttk.Scrollbar(
            salad_box, orient="vertical", command=self.salad_log_text.yview
        )
        self.salad_log_text.configure(yscrollcommand=sscroll.set)
        self.salad_log_text.grid(row=0, column=0, sticky="nsew")
        sscroll.grid(row=0, column=1, sticky="ns")
        ttk.Button(
            salad_box, text="Refresh Salad logs", command=self._refresh_salad_logs
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        paned.add(salad_box, weight=1)
        studio_box = ttk.LabelFrame(paned, text="Studio / HTTP", padding=4)
        studio_box.columnconfigure(0, weight=1)
        studio_box.rowconfigure(0, weight=1)
        self.log_text = tk.Text(studio_box, wrap="word", height=10, state="disabled")
        theme.style_text(self.log_text)
        yscroll = ttk.Scrollbar(studio_box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        for level, color in studio_log.LEVEL_COLORS.items():
            self.log_text.tag_configure(f"log_{level}", foreground=color)
        bar = ttk.Frame(studio_box)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(bar, text="Clear Studio logs", command=self._clear_logs).pack(
            side="left"
        )
        paned.add(studio_box, weight=1)

    def _set_salad_logs(self, text: str) -> None:
        widget = self.salad_log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _refresh_salad_logs(self) -> None:
        self._check_salad_status(silent=True)

    def _log_secrets(self) -> list[str]:
        """Values to redact from log lines, cached until a token is saved.

        ``tokens.read_token`` re-seeds from ``~/.config`` and can write on every
        call, so this must not run once per log line.
        """
        if self._log_secrets_cache is None:
            self._log_secrets_cache = self._read_log_secrets()
        return self._log_secrets_cache

    def _read_log_secrets(self) -> list[str]:
        out: list[str] = []
        for kind, _label, _rel in tokens.TOKEN_SPECS:
            val = tokens.read_token(kind)
            if val:
                out.append(val)
        try:
            out.append(self._salad_api_key())
        except Exception:
            pass
        return out

    def log(self, level: str, message: str) -> None:
        cleaned = studio_log.redact(message, self._log_secrets())
        line = studio_log.format_line(level, cleaned)

        def append() -> None:
            widget = self.log_text
            widget.configure(state="normal")
            widget.insert("end", line + "\n", (f"log_{level}",))
            widget.see("end")
            widget.configure(state="disabled")
            if self._busy:
                self._gen_last_note = cleaned.strip()

        try:
            if threading.current_thread() is threading.main_thread():
                append()
            else:
                self.after(0, append)
        except Exception:
            append()

    def _clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.log("info", "Logs cleared")

    def _selected_lora_ids(self) -> list[str]:
        return list(self._pending_selected)

    def _set_selected_lora_ids(self, ids: list[str]) -> None:
        self._pending_selected = list(ids)
        want = set(ids)
        self._syncing_loras = True
        try:
            for lid, var in self._lora_vars.items():
                var.set(lid in want)
        finally:
            self._syncing_loras = False

    def _refresh_lora_lists(self) -> None:
        selected = set(self._pending_selected)
        graph = lora_store.graph_id(self.var_graph.get())
        rows = lora_store.list_loras()
        self._syncing_loras = True
        try:
            for child in self._lora_inner.winfo_children():
                child.destroy()
            self._lora_vars = {}
            self._lora_checks = {}
            col = 0
            row_i = 0
            for item in rows:
                lid = str(item.get("id") or "")
                if not lid:
                    continue
                ok = lora_store.compatible_with_graph(item, graph)
                var = tk.BooleanVar(value=ok and lid in selected)
                self._lora_vars[lid] = var
                cb = ttk.Checkbutton(
                    self._lora_inner,
                    text=lora_store.config_label(item),
                    variable=var,
                    command=self._schedule_lora_sync,
                    state=("normal" if ok else "disabled"),
                )
                cb.grid(row=row_i, column=col, sticky="nw", padx=(0, 10), pady=1)
                self._lora_checks[lid] = cb
                var.trace_add("write", lambda *_a: self._schedule_lora_sync())
                cb.bind("<ButtonRelease-1>", lambda _e: self.after_idle(self._on_lora_toggle))
                col += 1
                if col >= LORA_CHECK_COLUMNS:
                    col = 0
                    row_i += 1
        finally:
            self._syncing_loras = False
        for child in self.lora_tree.get_children():
            self.lora_tree.delete(child)
        for item in rows:
            src = item.get("source") or {}
            self.lora_tree.insert(
                "",
                "end",
                iid=str(item.get("id") or ""),
                values=(
                    item.get("id") or "",
                    item.get("name") or "",
                    lora_store.version_label(item),
                    lora_store.family_label(item),
                    src.get("host") or "",
                    lora_store.comfy_lora_name(item),
                    "yes" if item.get("verified") else "no",
                ),
            )

    def _fill_lora_form(self, item: dict) -> None:
        """Copy a library row into the add/edit entries (LoRAs-tab selection)."""
        src = item.get("source") or {}
        self.var_lora_name.set(str(item.get("name") or ""))
        fname = str(src.get("filename") or "") or lora_store.comfy_lora_name(item)
        self.var_lora_file.set(fname)
        self.var_lora_family.set(lora_store.family_label(item))
        sm, sc = lora_store.strengths_for(item)
        self.var_lora_sm.set(str(sm))
        self.var_lora_sc.set(str(sc))
        self.var_lora_ref.set(str(src.get("page") or src.get("download") or item.get("id") or ""))

    def _on_graph_change(self, *_a) -> None:
        if self._applying_profile:
            return
        gid = lora_store.graph_id(self.var_graph.get())
        self.log("info", f"graph -> {gid} ({lora_store.graph_label(gid)})")
        self._refresh_lora_lists()
        self._sync_editor()

    def _schedule_lora_sync(self, *_a) -> None:
        if self._syncing_loras or self._applying_profile:
            return
        self._on_lora_toggle()
        self.after_idle(self._on_lora_toggle)

    def _on_lora_toggle(self) -> None:
        if self._syncing_loras or self._applying_profile:
            return
        graph = lora_store.graph_id(self.var_graph.get())
        by_id = {str(it.get("id") or ""): it for it in lora_store.list_loras()}
        shown: list[str] = []
        for lid in self._lora_vars:
            item = by_id.get(lid)
            if item is not None and lora_store.compatible_with_graph(item, graph):
                shown.append(lid)
        shown_set = set(shown)
        kept = [lid for lid in self._pending_selected if lid not in shown_set]
        for lid in shown:
            if self._lora_vars[lid].get() and lid not in kept:
                kept.append(lid)
        self._pending_selected = kept
        self.log("info", f"LoRA selection {kept}")
        self._sync_editor()

    def _on_add_lora(self) -> None:
        ref = self.var_lora_ref.get().strip()
        if not ref:
            messagebox.showinfo("Salad Studio", "Paste a Civitai/HF URL, civitai:id@version, or a local path.")
            return
        try:
            item = lora_store.add_lora(
                ref,
                name=self.var_lora_name.get().strip() or None,
                filename=self.var_lora_file.get().strip() or None,
                strength_model=self._parse_strength(self.var_lora_sm.get(), 1.0),
                strength_clip=self._parse_strength(self.var_lora_sc.get(), 1.0),
                base=self.var_lora_family.get(),
            )
        except (Exception, SystemExit) as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        lid = str(item.get("id") or "")
        if lid and lid not in self._pending_selected:
            self._pending_selected.append(lid)
        self._refresh_lora_lists()
        self.var_lora_ref.set("")
        self.status.set(f"Added LoRA {lid}")
        self.log("ok", f"added LoRA {lid}")
        self._sync_editor()

    def _on_verify_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a LoRA in the list to verify.")
            return
        ok_n = 0
        fail: list[str] = []
        for lid in sel:
            try:
                item = lora_store.verify_lora(lid)
            except Exception as e:
                fail.append(f"{lid}: {e}")
                self.log("error", f"verify LoRA {lid}: {e}")
                continue
            if item.get("verified"):
                ok_n += 1
                self.log("ok", f"verified LoRA {lid}")
            else:
                fail.append(lid)
                self.log("warn", f"LoRA {lid} did not verify")
        self._refresh_lora_lists()
        self._sync_editor()
        if fail:
            msg = f"Verified {ok_n}; failed: " + ", ".join(fail)
            self.status.set(msg)
            messagebox.showerror("Salad Studio", msg)
            return
        self.status.set(f"Verified {ok_n} LoRA(s)")

    def _on_verify_unverified(self) -> None:
        try:
            ok_n, fail_n, failed = lora_store.verify_unverified_loras()
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_lora_lists()
        self._sync_editor()
        if fail_n:
            msg = f"Verified {ok_n}; {fail_n} still unverified: " + ", ".join(failed[:8])
            self.status.set(msg)
            self.log("warn", msg)
            messagebox.showerror("Salad Studio", msg)
            return
        msg = f"Verified {ok_n} LoRA(s)" if ok_n else "Nothing unverified"
        self.status.set(msg)
        self.log("ok", msg)

    def _on_remove_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a user extra in the list.")
            return
        lid = sel[0]
        if not lora_store.remove_lora(lid):
            messagebox.showinfo(
                "Salad Studio",
                "Known catalog LoRAs stay in the list; only extras added here can be removed.",
            )
            return
        self._refresh_lora_lists()
        self.status.set(f"Removed {lid}")
        self.log("ok", f"removed extra LoRA {lid}")
        self._sync_editor()

    def _parse_strength(self, raw: str, default: float) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _on_lora_tree_select(self, _e=None) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            return
        item = lora_store.find_lora(sel[0])
        if item is None:
            return
        self._fill_lora_form(item)

    def _on_edit_lora(self) -> None:
        sel = self.lora_tree.selection()
        if not sel:
            messagebox.showinfo("Salad Studio", "Select a LoRA in the list to edit.")
            return
        lid = sel[0]
        try:
            lora_store.edit_lora(
                lid,
                name=self.var_lora_name.get().strip() or None,
                filename=self.var_lora_file.get().strip() or None,
                strength_model=self._parse_strength(self.var_lora_sm.get(), 1.0),
                strength_clip=self._parse_strength(self.var_lora_sc.get(), 1.0),
                base=self.var_lora_family.get(),
            )
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        self._refresh_lora_lists()
        if lid in self.lora_tree.get_children():
            self.lora_tree.selection_set(lid)
        self.status.set(f"Saved LoRA {lid}")
        self.log("ok", f"saved LoRA edits {lid}")
        self._sync_editor()

    def _on_close(self) -> None:
        try:
            self._save_ui_state()
        except Exception as e:
            self.log("warn", f"Could not save window state: {e}")
        self.destroy()

    def _capture_ui_state(self) -> dict:
        tab = ""
        try:
            tab = str(self.nb.tab(self.nb.select(), "text"))
        except tk.TclError:
            pass
        probes = {
            kind: {key: var.get() for key, var in fields.items()}
            for kind, fields in self._pol_vars.items()
        }
        return {
            "tab": tab,
            "profile": self.var_name.get(),
            "gateway": self.var_gateway.get(),
            "graph": self.var_graph.get(),
            "width": self.var_width.get(),
            "height": self.var_height.get(),
            "steps": self.var_steps.get(),
            "cfg": self.var_cfg.get(),
            "seed": self.var_seed.get(),
            "scheduler": self.var_scheduler.get(),
            "unet": self.var_unet.get(),
            "selected_loras": self._selected_lora_ids(),
            "prompt": self.prompt_text.get("1.0", "end-1c"),
            "negative": self.negative_text.get("1.0", "end-1c"),
            "editor": self.editor_text.get("1.0", "end-1c"),
            "helper_issue": self.helper_issue.get("1.0", "end-1c"),
            "helper_local_url": self.var_helper_local_url.get(),
            "helper_image": bool(self.var_helper_image.get()),
            "lora_ref": self.var_lora_ref.get(),
            "lora_name": self.var_lora_name.get(),
            "lora_file": self.var_lora_file.get(),
            "lora_family": self.var_lora_family.get(),
            "lora_sm": self.var_lora_sm.get(),
            "lora_sc": self.var_lora_sc.get(),
            "import_url": self.var_imp_image_url.get(),
            "import_cfg": self.var_imp_cfg.get(),
            "import_seed": self.var_imp_seed.get(),
            "import_steps": self.var_imp_steps.get(),
            "import_width": self.var_imp_width.get(),
            "import_height": self.var_imp_height.get(),
            "import_sched": self.var_imp_sched.get(),
            "import_unet": self.var_imp_unet.get(),
            "import_workflow": self._import_workflow_stash or "",
            "policy_image": self.var_pol_image.get(),
            "policy_us": bool(self.var_pol_us.get()),
            "policy_gpus": [gid for gid, var in self._pol_gpu_vars.items() if var.get()],
            "policy_probes": probes,
        }

    def _save_ui_state(self) -> None:
        ui_state.save_state(self._capture_ui_state())

    def _restore_ui_state(self) -> bool:
        isolated = profiles.PROFILES_PATH != (
            Path.home() / ".config" / "salad" / "studio-profiles.json"
        )
        default_ui = Path.home() / ".config" / "salad" / "studio-ui.json"
        if isolated and ui_state.STATE_PATH == default_ui:
            return False
        state = ui_state.load_state()
        if not state:
            return False
        self._applying_profile = True
        try:
            if state.get("profile"):
                self.var_name.set(str(state["profile"]))
            if "gateway" in state:
                self.var_gateway.set(str(state.get("gateway") or ""))
            if state.get("graph"):
                self.var_graph.set(str(state["graph"]))
            for attr, key in (
                ("var_width", "width"),
                ("var_height", "height"),
                ("var_steps", "steps"),
                ("var_cfg", "cfg"),
                ("var_seed", "seed"),
                ("var_scheduler", "scheduler"),
                ("var_unet", "unet"),
            ):
                if key in state:
                    getattr(self, attr).set(str(state.get(key) or ""))
            ids = state.get("selected_loras")
            if isinstance(ids, list):
                self._set_selected_lora_ids([str(x) for x in ids])
            self.prompt_text.delete("1.0", "end")
            self.prompt_text.insert("1.0", str(state.get("prompt") or ""))
            self.negative_text.delete("1.0", "end")
            self.negative_text.insert("1.0", str(state.get("negative") or ""))
            editor = state.get("editor")
            has_editor = isinstance(editor, str) and editor.strip()
            if has_editor:
                self.editor_text.delete("1.0", "end")
                self.editor_text.insert("1.0", editor)
            if "helper_issue" in state:
                self.helper_issue.delete("1.0", "end")
                self.helper_issue.insert("1.0", str(state.get("helper_issue") or ""))
            if state.get("helper_local_url"):
                self.var_helper_local_url.set(str(state["helper_local_url"]))
            if "helper_image" in state:
                self.var_helper_image.set(bool(state.get("helper_image")))
                self._refresh_helper_image_label()
            for attr, key in (
                ("var_lora_ref", "lora_ref"),
                ("var_lora_name", "lora_name"),
                ("var_lora_file", "lora_file"),
                ("var_lora_family", "lora_family"),
                ("var_lora_sm", "lora_sm"),
                ("var_lora_sc", "lora_sc"),
                ("var_imp_image_url", "import_url"),
                ("var_imp_cfg", "import_cfg"),
                ("var_imp_seed", "import_seed"),
                ("var_imp_steps", "import_steps"),
                ("var_imp_width", "import_width"),
                ("var_imp_height", "import_height"),
                ("var_imp_sched", "import_sched"),
                ("var_imp_unet", "import_unet"),
                ("var_pol_image", "policy_image"),
            ):
                if key in state:
                    getattr(self, attr).set(str(state.get(key) or ""))
            if "policy_us" in state:
                self.var_pol_us.set(bool(state.get("policy_us")))
            probes = state.get("policy_probes")
            if isinstance(probes, dict):
                for kind, fields in probes.items():
                    live = self._pol_vars.get(kind) or {}
                    if isinstance(fields, dict):
                        for key, val in fields.items():
                            if key in live:
                                live[key].set(str(val))
            gpus = state.get("policy_gpus")
            if isinstance(gpus, list):
                self._restored_gpu_ids = [str(x) for x in gpus]
                for gid, var in self._pol_gpu_vars.items():
                    var.set(gid in self._restored_gpu_ids)
            stash = str(state.get("import_workflow") or "")
            if stash:
                self._stash_import_workflow(stash)
            tab = str(state.get("tab") or "")
            if tab == "Prompt":
                tab = "Prompt Editor"
            if tab:
                self._goto_tab(tab)
        finally:
            self._applying_profile = False
        if isinstance(state.get("editor"), str) and str(state.get("editor")).strip():
            self._apply_json_chrome()
            return True
        return False

    def _patch_editor_from_prompt(self) -> None:
        """Keep the loaded graph. Only the positive and negative CLIP text change."""
        if self._syncing_editor or self._applying_profile:
            return
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._sync_editor()
            return
        if not isinstance(payload, dict):
            self._sync_editor()
            return
        text = self.prompt_text.get("1.0", "end").strip()
        neg = self.negative_text.get("1.0", "end").strip()
        if not request_json.apply_prompt_texts(payload, text, neg):
            self._sync_editor()
            return
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._apply_json_chrome()

    def _sync_editor(self) -> None:
        if self._syncing_editor or self._applying_profile:
            return
        self._syncing_editor = True
        try:
            try:
                width = int(self.var_width.get() or 1024)
                height = int(self.var_height.get() or 1024)
                steps = int(self.var_steps.get() or 20)
                cfg = float(self.var_cfg.get() or 5)
                seed = int(float(self.var_seed.get() or 1))
            except ValueError:
                return
            text = self.prompt_text.get("1.0", "end").strip()
            neg = self.negative_text.get("1.0", "end").strip()
            body = request_json.build_request(
                prompt_text=text,
                negative_text=neg,
                graph=lora_store.graph_id(self.var_graph.get()),
                width=width,
                height=height,
                steps=steps,
                seed=seed,
                cfg=cfg,
                unet=request_json.normalize_unet(self.var_unet.get()),
                selected_ids=self._selected_lora_ids(),
            )
            request_json.apply_scheduler(body, self._scheduler_id())
            dumped = json.dumps(body, indent=2)
            self.editor_text.configure(state="normal")
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
            self._apply_json_chrome()
            self._refresh_graph()
            self.log(
                "debug",
                f"rebuilt editor from Config  graph={lora_store.graph_id(self.var_graph.get())}  "
                f"{width}x{height}  steps={steps}  loras={self._selected_lora_ids()}",
            )
        except Exception as e:
            self.status.set(f"JSON build failed: {e}")
            self.log("error", f"JSON build failed: {e}")
        finally:
            self._syncing_editor = False

    def _rebuild_from_json(self, *, remember: bool = True) -> None:
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = generator.parse_request_json(raw)
            cfg = request_json.config_from_payload(payload)
        except (ValueError, json.JSONDecodeError, TypeError) as e:
            self.log("error", f"Rebuild from JSON failed: {e}")
            messagebox.showerror("Salad Studio", f"Cannot parse Prompt Editor JSON: {e}")
            return
        ids = list(cfg.get("selected_ids") or [])
        for spec in cfg.get("unmatched_loras") or []:
            name = str(spec.get("lora_name") or "")
            if not name:
                continue
            try:
                item = lora_store.add_lora(
                    name,
                    strength_model=float(spec.get("strength_model") or 1),
                    strength_clip=float(spec.get("strength_clip") or 1),
                    base=lora_store.graph_label(str(cfg.get("graph") or "klein")),
                )
            except (Exception, SystemExit) as e:
                self.log("warn", f"Could not add LoRA {name}: {e}")
                messagebox.showerror("Salad Studio", f"Could not add LoRA {name}: {e}")
                continue
            lid = str(item.get("id") or "")
            if lid and lid not in ids:
                ids.append(lid)
        self._applying_profile = True
        try:
            self._set_selected_lora_ids(ids)
            self.var_graph.set(lora_store.graph_label(str(cfg.get("graph") or "klein")))
            self.var_width.set(str(int(cfg.get("width") or 1024)))
            self.var_height.set(str(int(cfg.get("height") or 1024)))
            self.var_steps.set(str(int(cfg.get("steps") or 20)))
            if hasattr(self, "var_cfg") and cfg.get("cfg") not in (None, ""):
                v = cfg.get("cfg")
                self.var_cfg.set(str(int(v) if float(v) == int(float(v)) else v))
            seed = None
            for node in (payload.get("prompt") or {}).values():
                if isinstance(node, dict) and node.get("class_type") == "RandomNoise":
                    seed = (node.get("inputs") or {}).get("noise_seed")
                    break
            if hasattr(self, "var_seed") and seed is not None:
                self.var_seed.set(str(seed))
            if hasattr(self, "var_scheduler"):
                self.var_scheduler.set(
                    self._scheduler_label(str(cfg.get("scheduler") or "flux2"))
                )
            if hasattr(self, "var_unet"):
                self.var_unet.set(request_json.unet_label(str(cfg.get("unet") or "")))
            text = str(cfg.get("prompt_text") or "")
            self.prompt_text.delete("1.0", "end")
            if text:
                self.prompt_text.insert("1.0", text)
            self.negative_text.delete("1.0", "end")
            neg = str(cfg.get("negative_text") or "")
            if neg:
                self.negative_text.insert("1.0", neg)
            self._refresh_lora_lists()
        finally:
            self._applying_profile = False
        self._apply_json_chrome()
        if remember:
            self._remember_request(payload)
        self.status.set("Config updated from Prompt Editor JSON")
        self.log(
            "ok",
            f"rebuilt Config from JSON  graph={cfg.get('graph')}  "
            f"{cfg.get('width')}x{cfg.get('height')}  steps={cfg.get('steps')}  "
            f"loras={ids}",
        )

    def _hold_opened_size(self, event=None) -> None:
        """Open at the layout size, then refuse a later startup growth.

        The diagram host finishes a second or two after the window appears and
        would otherwise stretch the toplevel. Position is left unset so
        Windows places the window. The size is not written to studio-ui.json.
        """
        if event is not None and getattr(event, "widget", None) not in (None, self):
            return
        if self._opened_size_held:
            self._reapply_opened_size()
            return
        try:
            self.update_idletasks()
            width = max(int(self.winfo_reqwidth()), 1)
            height = max(int(self.winfo_reqheight()), 1)
        except tk.TclError:
            return
        self._opened_width = width
        self._opened_height = height
        self._opened_size_held = True
        self.geometry(f"{width}x{height}")
        for delay in (100, 400, 900, 1600, 2200):
            try:
                self.after(delay, self._reapply_opened_size)
            except tk.TclError:
                return

    def _reapply_opened_size(self) -> None:
        if not self._opened_size_held:
            self._hold_opened_size()
            return
        try:
            width = int(self.winfo_width())
            height = int(self.winfo_height())
        except tk.TclError:
            return
        if width <= 1 or height <= 1:
            return
        if width > self._opened_width + 48 or height > self._opened_height + 48:
            self.geometry(f"{self._opened_width}x{self._opened_height}")

    def _place_editor_sash(self, _e=None) -> None:
        """Open the Prompt Editor with the JSON box at 25% and the diagram at 75%."""
        if self._editor_sash_set:
            return
        self._hold_opened_size()
        pane = self._editor_pane
        try:
            pane.update_idletasks()
            width = int(pane.winfo_width())
        except tk.TclError:
            return
        if width <= 1:
            return
        try:
            pane.sashpos(0, max(1, int(width * 0.25)))
        except tk.TclError:
            return
        self._editor_sash_set = True

    def _on_editor_edited(self, _e=None) -> None:
        if self._syncing_editor:
            return
        self.editor_text.configure(state="normal")
        self._graph_stale = True
        self._schedule_json_chrome(refresh_graph=False)

    def _editor_copy(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        try:
            text = widget.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        return "break"

    def _editor_paste(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        widget.insert("insert", text)
        widget.focus_set()
        self._on_editor_edited()
        return "break"

    def _editor_cut(self, _e=None):
        self._editor_copy()
        widget = self.editor_text
        try:
            widget.delete("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self._on_editor_edited()
        return "break"

    def _editor_select_all(self, _e=None):
        widget = self.editor_text
        widget.configure(state="normal")
        widget.focus_set()
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.tag_raise("sel")
        widget.see("insert")
        return "break"

    def _lift_editor_over_webview(self) -> None:
        """Keep the JSON box above the graph's native window.

        WebView2 is raised after every diagram update and otherwise covers
        the editor, so the next click never reaches the text.
        """
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return
        try:
            widget.configure(state="normal")
        except tk.TclError:
            return
        if sys.platform != "win32":
            try:
                widget.lift()
            except tk.TclError:
                pass
            return
        import ctypes
        from ctypes import wintypes

        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        user32 = ctypes.windll.user32
        for target in (widget, getattr(self, "_editor_box", None)):
            if target is None:
                continue
            try:
                hwnd = int(target.winfo_id())
            except (tk.TclError, ValueError):
                continue
            user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(0), 0, 0, 0, 0, flags)

    def _lift_editor_soon(self) -> None:
        self._lift_editor_over_webview()
        try:
            self.after_idle(self._lift_editor_over_webview)
            self.after(50, self._lift_editor_over_webview)
            self.after(200, self._lift_editor_over_webview)
        except tk.TclError:
            pass

    def _widget_in_graph(self, widget) -> bool:
        pane = getattr(self, "graph_pane", None)
        if pane is None or widget is None:
            return False
        host = getattr(pane, "_host", None)
        current = widget
        while current is not None:
            if current is pane or current is host:
                return True
            current = getattr(current, "master", None)
        return False

    def _release_graph_keyboard(self) -> None:
        """Hand the keyboard back to Tk after the graph's WebView2 held it."""
        pane = getattr(self, "graph_pane", None)
        web = getattr(pane, "_web", None) if pane is not None else None
        if web is not None:
            try:
                web.focus_parent()
            except Exception:
                pass
        self._lift_editor_soon()

    def _on_click_outside_graph(self, event) -> None:
        if self._widget_in_graph(getattr(event, "widget", None)):
            return
        self._release_graph_keyboard()
        widget = getattr(event, "widget", None)
        if widget is None:
            return
        try:
            widget.focus_set()
        except tk.TclError:
            pass

    def _on_editor_focus_in(self, _e=None) -> None:
        self._release_graph_keyboard()

    def _on_editor_focus_out(self, _e=None) -> None:
        if not getattr(self, "_graph_stale", False):
            return
        self._graph_stale = False
        self._refresh_graph(force=True)

    def _schedule_json_chrome(self, *, refresh_graph: bool = True) -> None:
        if self._json_after is not None:
            try:
                self.after_cancel(self._json_after)
            except Exception:
                pass
        self._json_after = self.after(
            60, lambda: self._apply_json_chrome(refresh_graph=refresh_graph)
        )

    def _apply_json_chrome(self, *, refresh_graph: bool = True) -> None:
        """Color-code the Prompt Editor and verify with parse_request_json."""
        self._json_after = None
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return
        json_highlight.apply_to_text(widget)
        raw = widget.get("1.0", "end-1c").strip()
        ok, msg = json_highlight.verify_request_json(raw)
        self.json_status.set(msg)
        style_name = "JsonOk.TLabel" if ok else "JsonBad.TLabel"
        try:
            st = ttk.Style(self)
            st.configure(
                "JsonOk.TLabel",
                background=theme.PALETTE["bg"],
                foreground="#8FBF9A",
            )
            st.configure(
                "JsonBad.TLabel",
                background=theme.PALETTE["bg"],
                foreground=theme.PALETTE["accent"],
            )
            self.json_status_lbl.configure(style=style_name)
        except tk.TclError:
            pass
        if refresh_graph:
            self._refresh_graph()

    def _refresh_graph(self, *, force: bool = False) -> None:
        pane = getattr(self, "graph_pane", None)
        if pane is None:
            return
        # A graph refresh moves keyboard focus into the WebView. While the
        # JSON editor is focused, defer it so copy and paste keep working.
        if not force:
            try:
                if self.focus_get() is self.editor_text:
                    self._graph_stale = True
                    return
            except tk.TclError:
                pass
        raw = self.editor_text.get("1.0", "end-1c").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if isinstance(prompt, dict):
            pane.set_prompt(prompt)
            self._lift_editor_soon()

    def _on_graph_swap(self, prompt: dict) -> None:
        raw = self.editor_text.get("1.0", "end-1c").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"prompt": {}, "convert_output": dict(comfy_import.CONVERT_OUTPUT)}
        if not isinstance(payload, dict):
            payload = {}
        payload["prompt"] = prompt
        request_json.stamp_weight_refs(payload)
        dumped = json.dumps(payload, indent=2)
        self._syncing_editor = True
        try:
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", dumped)
        finally:
            self._syncing_editor = False
        self._apply_json_chrome()
        self.status.set("Swapped nodes in Prompt Editor JSON")
        self.log("ok", "swapped graph nodes")

    def _validate_editor(self, *, popup: bool = True) -> bool:
        """Run parse_request_json plus graph checks. Same gate Generate uses."""
        self._apply_json_chrome()
        widget = getattr(self, "editor_text", None)
        if widget is None:
            return False
        raw = widget.get("1.0", "end-1c").strip()
        ok, msg = json_highlight.verify_request_json(raw)
        extra: list[str] = []
        if ok:
            payload = generator.parse_request_json(raw)
            extra.append(studio_log.summarize_payload(payload))
            extra.append(f"POST {studio_log.prompt_url(self.var_gateway.get())}")
            unverified = lora_store.unverified_payload_refs(payload)
            if unverified:
                extra.append("unverified: " + ", ".join(unverified[:6]))
                ok = False
                msg = "JSON valid, but weight URL is not verified"
            if request_json.payload_has_civitai_download(payload):
                if tokens.read_token("civitai"):
                    extra.append("Civitai LoRA URLs: token will be attached on Generate")
                else:
                    extra.append("Civitai LoRA URLs: no token on Tokens tab (Generate would 401)")
                    ok = False
                    msg = "JSON valid, but Civitai token is missing"
        line = msg
        if extra:
            line = msg + " — " + "; ".join(extra)
        self.json_status.set(msg if ok else line)
        self.log("ok" if ok else "error", f"Validate: {line}")
        if popup and not ok:
            messagebox.showerror("Salad Studio", line)
        return ok

    def _scheduler_id(self) -> str:
        raw = (self.var_scheduler.get() if hasattr(self, "var_scheduler") else "") or ""
        return "simple" if "simple" in raw.lower() or "civitai" in raw.lower() else "flux2"

    def _scheduler_label(self, kind: str) -> str:
        return "Simple (Civitai)" if str(kind).lower() == "simple" else "Flux2 (Klein)"

    def _profile_from_form(self) -> SaladProfile:
        name = (self.var_name.get() or "klein").strip()
        selected = self._selected_lora_ids()
        return SaladProfile(
            name=name,
            gateway=self.var_gateway.get().strip(),
            key_path=profiles.DEFAULT_KEY_PATH,
            graph=lora_store.graph_id(self.var_graph.get()),
            width=int(self.var_width.get() or 1024),
            height=int(self.var_height.get() or 1024),
            steps=int(self.var_steps.get() or 20),
            cfg=float(self.var_cfg.get() or 5),
            seed=int(float(self.var_seed.get() or 1)),
            scheduler=self._scheduler_id(),
            unet=request_json.normalize_unet(self.var_unet.get()),
            use_loras=bool(selected),
            selected_loras=selected,
        )

    def _apply_profile(self, p: SaladProfile) -> None:
        self._applying_profile = True
        try:
            self._set_selected_lora_ids(list(p.selected_loras))
            self.var_name.set(p.name)
            self.var_gateway.set(p.gateway)
            self.var_width.set(str(p.width))
            self.var_height.set(str(p.height))
            self.var_steps.set(str(p.steps))
            if hasattr(self, "var_cfg"):
                self.var_cfg.set(str(getattr(p, "cfg", 5)))
            if hasattr(self, "var_seed"):
                self.var_seed.set(str(getattr(p, "seed", 1)))
            self.var_graph.set(lora_store.graph_label(p.graph))
            if hasattr(self, "var_scheduler"):
                self.var_scheduler.set(self._scheduler_label(getattr(p, "scheduler", "flux2")))
            if hasattr(self, "var_unet"):
                self.var_unet.set(request_json.unet_label(getattr(p, "unet", "")))
        finally:
            self._applying_profile = False
        if getattr(self, "_lora_inner", None) is not None:
            self._refresh_lora_lists()
        self._sync_editor()
        self.log(
            "info",
            f"loaded profile {p.name}  gateway={p.gateway}  graph={p.graph}  "
            f"{p.width}x{p.height}  steps={p.steps}",
        )

    def _load_profiles_into_ui(self) -> None:
        allp = profiles.ensure_builtin_profiles()
        if not allp:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            allp = {p.name: p}
        names = sorted(allp)
        self.profile_combo["values"] = names
        active = profiles.get_active()
        if active not in allp:
            active = names[0]
        self._apply_profile(allp[active])

    def _on_select_profile(self) -> None:
        name = self.var_name.get().strip()
        allp = profiles.load_all()
        if name in allp:
            self._apply_profile(allp[name])
            profiles.set_active(name)

    def _save_profile(self) -> None:
        try:
            p = self._profile_from_form()
        except ValueError as e:
            messagebox.showerror("Salad Studio", f"Invalid size/steps: {e}")
            return
        profiles.upsert(p)
        profiles.set_active(p.name)
        self.profile_combo["values"] = sorted(profiles.load_all())
        self.status.set(f"Saved profile {p.name}")
        self.log("ok", f"saved profile {p.name}  gateway={p.gateway}  graph={p.graph}")

    def _delete_profile(self) -> None:
        name = self.var_name.get().strip()
        if not name:
            return
        profiles.delete(name)
        remaining = profiles.load_all()
        if remaining:
            nxt = next(iter(remaining))
            profiles.set_active(nxt)
            self._apply_profile(remaining[nxt])
        else:
            p = profiles.default_profile("klein")
            profiles.upsert(p)
            profiles.set_active(p.name)
            self._apply_profile(p)
        self.profile_combo["values"] = sorted(profiles.load_all())
        self.status.set(f"Deleted {name}")
        self.log("warn", f"deleted profile {name}")

    def _history_paths(self) -> list[Path]:
        studio = generator.list_history(OUT_DIR)
        probes = []
        if ART.is_dir():
            probes = sorted(
                ART.glob(PROBE_GLOB),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        seen: set[str] = set()
        out: list[Path] = []
        for p in studio + probes:
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def _refresh_history(self) -> None:
        self.strip.set_paths(self._history_paths())

    def _on_clean_gallery(self) -> None:
        paths = self._history_paths()
        if not paths:
            messagebox.showinfo("Salad Studio", "Gallery is already empty.")
            return
        n = len(paths)
        if not messagebox.askyesno(
            "Salad Studio",
            f"Delete {n} image(s) from disk and clear the gallery? This cannot be undone.",
        ):
            return
        deleted = 0
        for path in paths:
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                self.log("warn", f"could not delete {path}: {e}")
        thumbs = prompt_history.clear_thumbs()
        self._refresh_history()
        self._refresh_prompt_history()
        self.status.set(f"Deleted {deleted} gallery image(s)")
        self.log("ok", f"cleaned gallery ({deleted} plates, {thumbs} thumbs)")

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as e:
            messagebox.showerror("Salad Studio", str(e))

    def _on_generate(self) -> None:
        if self._busy:
            return
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            payload = generator.parse_request_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            self.log("error", f"Generate aborted: invalid JSON: {e}")
            messagebox.showerror("Salad Studio", f"Prompt Editor JSON is invalid: {e}")
            return
        try:
            p = self._profile_from_form()
        except ValueError as e:
            messagebox.showerror("Salad Studio", str(e))
            return
        # Route by the unet the graph loads. One container group serves one unet
        # family: a second ~9 GB unet cannot fit in VRAM beside the 8.66 GB text
        # encoder, so Comfy streams weights from host memory and a seconds-long
        # render becomes minutes — which the gateway then cuts off with a 524.
        #
        # The comparison is against the group the form's GATEWAY points at, not
        # against the form's unet. Loading a JSON into the editor rewrites
        # var_unet from the graph (_rebuild_from_json), so comparing the graph's
        # family to the form's unet compares the graph with itself and can never
        # fire — which is how a SNOFS graph reached the klein group. (2026-09-22)
        loaded = profiles.payload_unets(payload)
        want = profiles.unet_family(loaded[0]) if loaded else ""
        if want:
            try:
                allp = profiles.load_all()
            except Exception:
                allp = {}
            here = profiles.profile_for_gateway(p.gateway, allp)
            serving = profiles.serving_family(here) if here else ""
            if serving and serving != want:
                target = profiles.route_payload(payload, allp)
                if target is None:
                    reason = profiles.routing_conflict(payload, p)
                    self.log("error", f"Generate blocked: no profile serves the {want} unet family")
                    messagebox.showerror("Salad Studio", reason)
                    return
                name, routed = target
                self.log(
                    "info",
                    f"Routed to profile {name!r} (gateway {routed.gateway}) — this graph loads "
                    f"{loaded[0]}, so it belongs on the {want} group.",
                )
                p = routed
        try:
            key = self._salad_api_key()
        except (OSError, FileNotFoundError) as e:
            messagebox.showerror("Salad Studio", f"Cannot read Salad API key: {e}")
            return
        if not p.gateway:
            self.log("error", "Generate aborted: gateway URL is empty")
            messagebox.showerror("Salad Studio", "Gateway URL is empty.")
            return
        word = (self.var_salad_status.get() or "").strip()
        if (word or "").split()[:1] != ["Ready"]:
            try:
                info = salad_status.snapshot_gateway(p.gateway, key)
                reason = info.get("block") or salad_status.generate_block_reason(info)
            except Exception:
                reason = f"Replica is not Ready ({word or 'unknown'})."
            self.log("warn", f"Generate blocked: {reason}")
            messagebox.showinfo("Salad Studio", reason or "Replica is not Ready.")
            return
        self._busy = True
        self.gen_btn.configure(state="disabled")
        self._gen_t0 = time.monotonic()
        self._gen_last_note = "queued"
        self.var_gen_state.set("Starting…")
        self.status.set("Generating…")
        self._schedule_gen_tick()
        self._remember_request(payload)
        self.log("info", f"Generate  gateway={p.gateway}  graph={p.graph}")
        self.log("debug", studio_log.summarize_payload(payload))

        def work() -> None:
            err = ""
            out: Path | None = None
            try:
                out = generator.generate_from_payload(
                    gateway=p.gateway,
                    key=key,
                    payload=payload,
                    out_dir=OUT_DIR,
                    on_log=self.log,
                )
            except Exception as e:
                err = str(e)
                self.log("error", err)

            def done() -> None:
                self._busy = False
                self._cancel_gen_tick()
                elapsed = max(0, int(time.monotonic() - self._gen_t0))
                self.gen_btn.configure(state="normal")
                if err:
                    # Probe rather than re-apply the cached word. A failed render
                    # usually means the replica went away mid-job, and the cache
                    # still says Ready from before it did — which is how the app
                    # kept reporting a container that had already restarted as up.
                    self._check_salad_status(silent=True)
                    self.var_gen_state.set(f"Failed after {elapsed}s")
                    self.status.set("Failed — see Logs")
                    messagebox.showerror("Salad Studio", err)
                    return
                self._apply_generate_gate(self.var_salad_status.get())
                self.var_gen_state.set(f"Done in {elapsed}s")
                self.status.set(f"Wrote {out}")
                self.log("ok", f"Generate finished  {out}")
                if out:
                    try:
                        prompt_history.attach_image(Path(out))
                    except Exception as e:
                        self.log("warn", f"history thumb skipped: {e}")
                    self._refresh_prompt_history()
                self._refresh_history()

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    app = SaladStudio()
    app.mainloop()


if __name__ == "__main__":
    main()
