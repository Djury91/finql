---
name: eval-check
description: Measure whether a change to a prompt, the model, few-shot examples or retrieval made FinQL better or worse, using the eval harness. Use before claiming that such a change is an improvement.
argument-hint: "[what changed]"
---

# Eval check: $ARGUMENTS

"It looks better on three questions I tried" is not a result. FinQL measures **execution
accuracy** (ADR-007): a golden question passes if the generated SQL returns the same result as the
hand-written SQL. This skill keeps the measurement honest and the spending visible.

## 1. Prepare (free)

- **Prompt change:** add a new version file in `src/finql/llm/prompts/` (e.g.
  `text_to_sql.v2.md`) and switch the `PROMPT_VERSION` constant. Do not edit `v1`: every stored
  eval run records its prompt version, and the comparison needs the old one to stay meaningful.
- Run `uv run poe eval-oracle`. It runs the golden SQL itself through the harness and must be
  100%; if not, the harness or the data is broken, and a model run would measure noise.
- For retrieval changes, `uv run poe eval-retrieval` is free (recall@5, MRR, leak count) and may
  be all you need.

## 2. Ask before the paid run

Tell the developer what you will run, roughly how many model calls it makes (golden 50 +
adversarial 20 questions, each 1–3 calls with self-repair), and wait for a yes. The commands:

```bash
uv run finql eval run --label "<baseline>"                # if no comparable earlier run exists
uv run finql eval run --label "<what changed>"            # the change
uv run finql eval compare <run_a> <run_b>                 # improved and regressed questions
```

Use the same dataset, scale (`small`), model and `--few-shot` value for both runs; change one
thing at a time.

## 3. Read the result honestly

- Look at **which questions changed**, not only the total. Read the generated SQL of every
  regressed question.
- **One run is one sample.** The model is not deterministic: a difference of 1–2 questions out of
  50 is within noise (the published few-shot comparison was 49 vs 48, and is reported as such).
  Do not call it an improvement; rerun the changed questions with `--only <id>` if it matters.
- Adversarial must stay **20/20**. Any regression there blocks the change, whatever the accuracy.
- If a golden question fails because the golden SQL or the question is ambiguous, fix the dataset
  in a separate commit and say so; do not hide it in the same change.

## 4. Report

Run ids, the two headline numbers for each run, the list of improved and regressed questions
with one sentence each, and your verdict: better / no measurable difference / worse. Only if the
developer asks: copy the report from `eval/reports/` to `eval/reports/published/` and update the
Results section of `README.md` and `README.hu.md`.
