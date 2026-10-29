---
name: queue-submission-safety
description: Formally check the Salad queue's promise that an accepted request is never POSTed twice and never retried. Use when changing salad_queue's attempt, retry, accept, or terminal-state logic, `SaladQueue.deliver` or `ensure_container`, the Retry button, or the duplicate-press guard, or when a change could make the app send a plate to a container that already took it.
---

# Queue submission safety

**Property.** Once a container accepts a request, the queue never POSTs that request again, and the job is never retryable.

**Harm if broken.** A second POST is a second render: several minutes of GPU time, a second charge, and a plate the user did not ask for. The app has no way to cancel a render the container already took.

**Check.** From the repo root:

```powershell
python .claude/skills/queue-submission-safety/check.py
```

Takes under a second. Exit 0 means every bounded sequence held. Exit 1 prints the failing outcome sequences.

## What is covered

| Checked | File | Symbols |
| --- | --- | --- |
| No POST after an accepted POST | `salad_studio/salad_queue.py` | `Attempt`, `classify`, `next_action`, `SaladQueue._run` |
| An accepted job is never retryable | `salad_studio/salad_queue.py` | `Job.retryable`, `SaladQueue.retry`, `SaladQueue.deliver` |

**Sync commit:** `dd793737c8894af39739d89a1044e2e239c2fc15`. The check was last confirmed against the code at that commit.

Rerun it when a change touches `SaladQueue.deliver` (the submit path the check drives), `ensure_container` (the refusal before a submit, which `deliver` calls) or `_forget` (it drops a line's container record after an idle stop or a gone gateway). `check.py` exercises `deliver`, so it covers the first two and only reads the third.

To tell whether a change touches the queue:

```powershell
git diff --stat dd79373 -- salad_studio/salad_queue.py
git diff dd79373 -- salad_studio/salad_queue.py
```

Any edit to the symbols in the table above means rerun the check. Edits elsewhere in `salad_queue.py` (the ledger, idle stop, finished history) do not invalidate this check; they need their own target.

## Bounds and assumptions

- **Outcome sequences up to 4 POSTs**, for `max_attempts` 1, 2, and 3. Each of the 8 outcome kinds appears at each step, so every ordering of accepted, busy, rejected, and transport-error answers within that bound is exercised.
- **One job, one line, one thread.** The run is `deliver` once, then one Retry press. Jobs on different lines and the enqueue/run interleaving are out of scope.
- **The transport is scripted.** Every POST returns the next scripted outcome. A real transport that hides a retry inside one call is not modelled, because `request_json.py` builds payloads and does not retry.
- **The code is driven, not modelled.** `check.py` imports the shipped `salad_queue` and injects `sleep`, `now`, and `retry_sleep_s`. There is no separate state machine to drift from the implementation.

Not covered: thread interleavings (for example `idle_check` deciding to stop a container while another thread enqueues on that line), the head-only duplicate-press contract in `duplicate_of_head`, ledger persistence, and the generator's request building.

## Reading a failure

The printed sequence is the transport's answers in order, and the message names the rule that broke:

- `POST after an accepted POST` — `classify` or `_run` retried after the container had the job. Look for a change that lets an accepted attempt classify as busy, or that continues the loop after acceptance.
- `an accepted job reported retryable` — `Job.retryable` lost its `not self.accepted` guard.
- `retry() POSTed an accepted job` — `SaladQueue.retry` re-ran work for an accepted job, usually because the guard above is gone or `retry` stopped consulting it.

A failure is the shipped code's behavior, not a modelling error: the check runs the real queue. The one exception is an intentional policy change, such as deciding that accepted jobs may be retried. That requires updating this skill and the expected property in `check.py`, and saying why in the commit.

## Keeping the check honest

The check can fail. Two patches at `d300b9e` were each caught, then reverted:

- Remove `and not self.accepted` from `Job.retryable`: 4,548 of 14,040 sequences fail with `an accepted job reported retryable`.
- Return `BUSY` instead of `FAILED` for an accepted non-200 in `classify`: 2,778 sequences fail with `POST after an accepted POST`.

If you change the check, rerun one of these patches to confirm it still catches the break.

## Updating after a change

1. Rerun the check. A pass means the promise still holds for the covered code.
2. If the covered functions changed but the promise did not, update the sync commit here to the commit where you confirmed the check, after reading the diff to confirm the check still describes the code.
3. If the promise changed on purpose, update the property, the table, and `check.py`, and record the decision in the commit message.
4. If a new POST path appears outside the queue (a second submission route in `generator.py`), this check does not see it. Add that path to the check or create a separate target.

## Second target, not yet verified

`SaladQueue.idle_check` promises that a container this app did not start is never stopped, including after a restart. That promise guards the user's own running container and has a richer state machine (ownership, `started_by_app`, idle clock, busy lines). It deserves its own check; do not stretch this one to cover it.
