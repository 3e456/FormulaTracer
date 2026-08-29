# User-defined semantics

user declarationはFormulaTracer既存のMathematical IRとevidence modelへ入る冗長経路であり、
第二のsemantic engineではありません。

```python
import cpp_audit as audit

@audit.theory(output="y", expression="y = x * scale")
def proprietary_transform(x, scale):
    return vendor_kernel(x, scale)
```

declarationは`USER_DECLARED`として記録されます。コード復元が可能なら独立比較し、
`MATCH` / `MISMATCH` / `NOT_EVALUABLE`を返します。一致だけでは
`IMPLEMENTATION_VERIFIED`、`REFERENCE_VERIFIED`、`LEAN_KERNEL_VERIFIED`になりません。

callbackではvalue semantics、shape/dtype/units/frame metadata、effectを分離します。
未指定項目はunknownで、userがPUREと宣言しただけでは実装由来effect proofにしません。
