"""Minimal clean-wheel smoke test; intentionally has no test-framework dependency."""

import formulatracer


assert formulatracer.native_available()
context = formulatracer.NativeContext()
formula = context.formula_from_json({"op": "Constant", "value": 42})
result = formula.verify()
assert result.value.status == "UNRESOLVED"  # theory-free inspection never guesses success
print("LINUX_WHEEL_SMOKE_PASS")
result.close()
formula.close()
context.close()
