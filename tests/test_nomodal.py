"""The no-dialog guard's contract, driven the way a caller meets it.

``tests/_nomodal.py`` replaces the Tk dialogs with recorders so no test can
raise a modal. These assert the behavior the module docstring now states: a call
is recorded rather than shown, the question dialogs answer ``True`` and the
notice dialogs ``"ok"``, a destructive confirmation answers ``False`` until the
test sets ``DESTRUCTIVE_ANSWER``, a ``mock.patch.object`` still shadows the recorder and
restores it, and importing the ``tests`` package installs the guard. (T4 in
docs/history/62-salad-studio-audit-2026-10-14.md.)
"""
from __future__ import annotations

import inspect
import textwrap
import unittest
from unittest import mock

from tests import _nomodal

try:
    from tkinter import messagebox
except ImportError:  # pragma: no cover - a run with no Tk at all
    messagebox = None

QUESTIONS = ("askyesno", "askokcancel", "askretrycancel", "askyesnocancel")
NOTICES = ("showinfo", "showwarning", "showerror")
GALLERY = "Delete 3 image(s) from disk and clear the gallery? This cannot be undone."

# The destructive branch, removed, is the old recorder that answered yes.
_DESTRUCTIVE_EDITS = (
    (
        "        if kind in _ANSWERS and _is_destructive(message):\n"
        "            return DESTRUCTIVE_ANSWER\n",
        "",
    ),
)


def _old_form(func, edits):
    source = textwrap.dedent(inspect.getsource(func))
    for new, old in edits:
        assert new in source, f"{func.__name__} no longer holds {new!r}"
        source = source.replace(new, old, 1)
    namespace: dict = {}
    exec(compile(source, f"<old {func.__name__}>", "exec"), func.__globals__, namespace)
    return namespace[func.__name__]


class TheNoModalGuard(unittest.TestCase):
    def setUp(self) -> None:
        if messagebox is None or not _nomodal.install():
            self.skipTest("tkinter is unavailable, so there is no dialog to guard")
        _nomodal.reset()

    def test_a_dialog_call_is_recorded_not_shown(self) -> None:
        answer = messagebox.showinfo("A title", "A body")
        self.assertEqual(_nomodal.CALLS, [("showinfo", "A title", "A body")])
        self.assertEqual(answer, "ok")

    def test_the_question_defaults_are_the_documented_ones(self) -> None:
        for kind in QUESTIONS:
            with self.subTest(kind=kind):
                self.assertIs(getattr(messagebox, kind)("Q", "M"), True)
        for kind in NOTICES:
            with self.subTest(kind=kind):
                self.assertEqual(getattr(messagebox, kind)("Q", "M"), "ok")

    def test_a_patch_shadows_the_guard_and_restores_it(self) -> None:
        guarded = messagebox.askyesno
        with mock.patch.object(messagebox, "askyesno", return_value=False) as ask:
            self.assertIsNot(messagebox.askyesno, guarded)
            self.assertIs(messagebox.askyesno("Q", "M"), False)
            self.assertEqual(ask.call_count, 1)
            self.assertEqual(_nomodal.CALLS, [], "the patched dialog must not record")
        self.assertIs(messagebox.askyesno, guarded, "the recorder must come back")

    def _assert_a_destructive_prompt_is_refused(self) -> None:
        answer = messagebox.askyesno("Salad Studio", GALLERY)
        self.assertIs(answer, False)
        self.assertEqual(_nomodal.CALLS[-1], ("askyesno", "Salad Studio", GALLERY))

    def test_a_destructive_prompt_defaults_to_refusal(self) -> None:
        """A delete confirmation is refused until the test sets the opt-in."""
        self._assert_a_destructive_prompt_is_refused()
        _nomodal.DESTRUCTIVE_ANSWER = True
        try:
            self.assertIs(messagebox.askyesno("Salad Studio", GALLERY), True)
        finally:
            _nomodal.DESTRUCTIVE_ANSWER = False
        self.assertIs(messagebox.askyesno("Q", "M"), True, "a plain question still says yes")

        old = _old_form(_nomodal._recorder, _DESTRUCTIVE_EDITS)("askyesno")
        with mock.patch.object(messagebox, "askyesno", old):
            with self.assertRaises(AssertionError):
                self._assert_a_destructive_prompt_is_refused()
            self.assertIs(
                messagebox.askyesno("Salad Studio", GALLERY),
                True,
                "the old recorder said yes, which is what deleted the gallery",
            )

    def test_importing_the_tests_package_installs_the_guard(self) -> None:
        self.assertTrue(_nomodal._INSTALLED)
        self.assertEqual(messagebox.showinfo.__module__, _nomodal.__name__)


if __name__ == "__main__":
    unittest.main()
