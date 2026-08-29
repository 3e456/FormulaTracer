# Synthetic operational audit

This example is entirely synthetic. It was independently authored to exercise
FormulaTracer and is not an anonymized or renamed case study.

It demonstrates three outcomes:

1. an exact weighted reduction reconstructed from Python source;
2. a derivative related to a central finite difference by
   `DISCRETIZATION_OF`, with the remaining error obligation preserved; and
3. an unsupported external calibration that remains `UNRESOLVED`.

Run from the repository root:

```powershell
$env:PYTHONPATH = "python"
.venv\Scripts\python examples\operational_audit\run_example.py
```

The script writes no files. Expected public-safe summaries are recorded in
`expected-reconstruction.json` and `expected-audit.json`.

Private research inputs, formulas, provenance, and outputs are not distributed
with FormulaTracer.
