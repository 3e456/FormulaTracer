# Physics foundationの保証境界

FormulaTracerは多変数・vector calculus、gradient/Jacobian/Hessian、divergence/curl/Laplacian、
geometric integral relation、dimension/unit、frame、SO(3)、quaternion、Fourier/Laplace ROC、
ODE/PDE relation、SciPy callback、variational/Noether relationをversioned packで表現します。

各項目は`DEFINED`、`THEOREM_REGISTERED`、`LEAN_KERNEL_VERIFIED`、
`REALIZATION_AVAILABLE`、`CONDITIONAL`、`PARTIAL`を区別します。非exact realizationは
Exact E-Graphへmergeされません。

FormulaTracerはphysical lawがempirically trueであることを証明しません。一般形Noether、
Gauss/Stokes、SE(3)、finite-volume error、full AD proofは必要な仮定・証明義務が未解決なら
conditionalまたはpartialのままです。
