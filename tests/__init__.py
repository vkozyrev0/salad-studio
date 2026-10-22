"""The suite. Run it from the repo root:

    python -m unittest discover -s tests -p "test_*.py"

A server test builds a whole studio over temporary stores (`tests/_studio.py`),
so importing this package has nothing to guard: the studio under test serves no
window and reaches no network unless a test stubs the call that would.
"""
