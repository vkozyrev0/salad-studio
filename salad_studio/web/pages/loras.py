"""LoRAs: the library as rows, the find box narrowing it, the add/edit form.

The page keeps the form in its own fields, so ``state()`` shows exactly what a
Save would write. Ids come from the row, never from the form: ``save_edits``
acts on the selected row and ``remove_selected`` asks first, so a stale form
cannot write or delete another row.

A LoRA's ``base`` is stored as the catalog's name ("Flux.2 Klein 9B"); the list
is shown the short label its family choice uses ("Flux.2 Klein").
"""
from __future__ import annotations

from typing import Any

import lora_store

COLUMNS = ("Verified", "Id", "Name", "Version", "Model", "Source")
EMPTY_TEXT = "No LoRAs match. Clear the find box, or add one below."
FAMILIES = lora_store.FAMILY_CHOICES
REMOVE_TITLE = "Remove this LoRA"
REMOVE_BODY = ("Removes the extra from this library. A catalog LoRA stays, because the "
               "catalog is part of the studio, not of your library.")


def _row(item: dict[str, Any]) -> dict[str, Any]:
    src = item.get("source") or {}
    lid = str(item.get("id") or "")
    return {
        "id": lid,
        "verified": item.get("verified") is True,
        "version": lora_store.version_label(item),
        "model": str(item.get("base") or ""),
        "source": str(src.get("page") or src.get("download") or ""),
    }


def _filtered(items: list[dict[str, Any]], find: str) -> list[dict[str, Any]]:
    text = find.strip().lower()
    return [item for item in items if not text or text in str(item.get("name") or "").lower()]


class LorasController:
    page = "loras"

    def __init__(self, studio: Any) -> None:
        self.studio = studio
        self.find = ""
        self.selected: str | None = None
        self.form: dict[str, Any] = self._blank_form()

    def _blank_form(self) -> dict[str, Any]:
        return {"ref": "", "name": "", "filename": "", "family": FAMILIES[0],
                "strength_model": "1.0", "strength_clip": "1.0"}

    def register(self, table: Any) -> None:
        table.action("loras.view")(self.view)
        table.action("loras.find", need={"text": str})(self.find_changed)
        table.action("loras.select", need={"id": str})(self.select)
        table.action("loras.edit_form", need={"field": str, "value": str})(self.edit_form)
        table.action("loras.add_lora", need={"ref": str})(self.add_lora)
        table.action("loras.save_edits")(self.save_edits)
        table.action("loras.verify_selected")(self.verify_selected)
        table.action("loras.verify_unverified")(self.verify_unverified)
        table.action("loras.remove_selected")(self.remove_selected)

    def view(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        return self.state()

    def state(self) -> dict[str, Any]:
        items = self._shown()
        ids = {str(item.get("id") or "") for item in items}
        selected = self.selected if self.selected in ids else None
        return {
            "columns": list(COLUMNS),
            "rows": [{"name": str(item.get("name") or ""), **_row(item)} for item in items],
            "count": len(items),
            "empty_text": "" if items else EMPTY_TEXT,
            "find": self.find,
            "selected": selected,
            "can_save": selected is not None,
            "families": list(FAMILIES),
            "form": dict(self.form),
            "buttons": ["Add", "Save edits", "Verify", "Verify unverified", "Remove"],
        }

    def _shown(self) -> list[dict[str, Any]]:
        return _filtered(lora_store.list_loras(), self.find)

    def _selected_item(self) -> dict[str, Any] | None:
        """The selected row as the store holds it, by id rather than by list position."""
        if not self.selected:
            return None
        return next((item for item in lora_store.list_loras()
                     if str(item.get("id") or "") == self.selected), None)

    # -- actions

    def find_changed(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        self.find = payload["text"]
        return self.state()

    def select(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        item = next((row for row in lora_store.list_loras()
                     if str(row.get("id") or "") == payload["id"]), None)
        if item is None:
            ctx.note("LoRAs: that row is gone; refresh the list", level="warn")
            return self.state()
        src = item.get("source") or {}
        model, clip = lora_store.strengths_for(item)
        self.selected = payload["id"]
        self.form = {
            "ref": str(src.get("page") or src.get("download") or item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "filename": str(src.get("filename") or "") or lora_store.comfy_lora_name(item),
            "family": lora_store.family_label(item),
            "strength_model": f"{model:g}",
            "strength_clip": f"{clip:g}",
        }
        return self.state()

    def edit_form(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        field, value = payload["field"], payload["value"]
        if field not in self.form:
            ctx.note(f"LoRAs: the form has no field {field}", level="warn")
            return self.state()
        self.form[field] = value
        return self.state()

    def _number(self, raw: str) -> float | None:
        try:
            return float(raw.strip() or "1")
        except ValueError:
            return None

    def add_lora(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        ref = payload["ref"].strip()
        if not ref:
            ctx.dialog("Add a LoRA", "Type a Civitai page, a civitai:id@version, a Hugging Face URL, "
                       "a local .safetensors path, or a download URL.", level="error")
            return self.state()
        model, clip = self._number(self.form["strength_model"]), self._number(self.form["strength_clip"])
        if model is None or clip is None:
            ctx.note("LoRAs: strength model and strength clip must be numbers", level="warn")
            return self.state()
        form = {
            "name": self.form["name"].strip() or None,
            "filename": self.form["filename"].strip() or None,
            "base": self.form["family"].strip() or None,
            "strength_model": model,
            "strength_clip": clip,
        }

        def work() -> Any:
            return lora_store.add_lora(ref, verify=True, **form)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.note(f"Could not add the LoRA: {result}", level="error")
                ctx.dialog("Could not add the LoRA", str(result), level="error")
                return
            added = str((result or {}).get("name") or ref)
            self.form["ref"] = ""
            self.selected = str((result or {}).get("id") or "") or self.selected
            ctx.note(f"Added {added}", level="ok")
            ctx.log("ok", f"LoRAs: added {added}")

        ctx.note(f"Adding {ref}…")
        ctx.background(work, done)
        return self.state()

    def save_edits(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        item = self._selected_item()
        if item is None:
            ctx.note("Save edits: select a LoRA first", level="warn")
            ctx.dialog("Save edits", "Select a LoRA first, then change its fields.", level="warn")
            return self.state()
        model, clip = self._number(self.form["strength_model"]), self._number(self.form["strength_clip"])
        if model is None or clip is None:
            ctx.note("LoRAs: strength model and strength clip must be numbers", level="warn")
            return self.state()
        try:
            lora_store.edit_lora(
                str(item.get("id")), name=self.form["name"].strip() or None,
                filename=self.form["filename"].strip() or None, base=self.form["family"].strip() or None,
                strength_model=model, strength_clip=clip)
        except ValueError as exc:
            ctx.note(f"Could not edit the LoRA: {exc}", level="error")
            return self.state()
        ctx.note(f"Saved the edits to {self.form['name'].strip() or item.get('name')}", level="ok")
        return self.state()

    def verify_selected(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        item = self._selected_item()
        if item is None:
            ctx.note("Verify: select a LoRA first", level="warn")
            return self.state()
        lid = str(item.get("id"))

        def work() -> Any:
            return lora_store.verify_lora(lid)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.note(f"Could not verify the LoRA: {result}", level="error")
                return
            ok = bool((result or {}).get("verified"))
            ctx.note(f"{item.get('name')}: {'verified' if ok else 'verification failed'}",
                     level="ok" if ok else "warn")

        ctx.note(f"Verifying {item.get('name')}…")
        ctx.background(work, done)
        return self.state()

    def verify_unverified(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        def work() -> Any:
            return lora_store.verify_unverified_loras()

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                ctx.note(f"Could not verify the unverified LoRAs: {result}", level="error")
                return
            ok, fail, _failed = result
            ctx.note(f"Verified {ok}; {fail} failed" if fail else f"Verified {ok} LoRAs",
                     level="warn" if fail else "ok")

        ctx.note("Verifying the unverified LoRAs…")
        ctx.background(work, done)
        return self.state()

    def remove_selected(self, payload: dict[str, Any], *, ctx: Any) -> dict[str, Any]:
        item = self._selected_item()
        if item is None:
            ctx.note("Remove: select a LoRA first", level="warn")
            return self.state()
        lid = str(item.get("id"))
        if not ctx.confirmed:
            ctx.effects.append({
                "kind": "confirm",
                "token": self.studio.issue_confirm(self.page, "remove_selected", {}),
                "title": REMOVE_TITLE,
                "body": f"Remove {item.get('name')} ({lid})? {REMOVE_BODY}",
            })
            return self.state()
        if not lora_store.remove_lora(lid):
            ctx.note("Known catalog LoRAs stay in the list; only extras added here can be removed.",
                     level="warn")
            return self.state()
        self.selected = None
        self.form = self._blank_form()
        ctx.note(f"Removed {item.get('name')}", level="ok")
        return self.state()
