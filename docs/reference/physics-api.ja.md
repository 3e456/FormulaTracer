# Physics Foundationリファレンス

検索可能なcanonical entryは`registry/scientific_foundations/physics-v1.json`から
`output/public_function_reference/physics-reference.json`へ生成します。

packはvector calculus定義（`gradient`、`jacobian`、`hessian`、`divergence`、
`curl_r3`、`laplacian`）、integral/action/conservation、rotation/frame/quaternion、
transform relation、条件付きtheorem、数値/provider realizationを含みます。

各entryはdefinition、assumptions、relation、formalization level、Lean theorem、
implementation realization、obligations、error evidenceを分離します。
`DEFINED`、`THEOREM_REGISTERED`、`LEAN_KERNEL_VERIFIED`、`REALIZATION_AVAILABLE`は
同じ意味ではありません。Gauss、Stokes、Noether、frame、regularity、orientation、
convergenceの仮定を明示します。

例はvector-calculus定義、quaternion/rotation realization、Fourier/Laplace restrictionを
含みます。数学定義が登録済みでもdiscretizationやprovider algorithmはnon-exact relationです。

