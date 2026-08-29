# Status・Relation・Evidenceリファレンス

実装から抽出した完全な値一覧は
`output/public_function_reference/{status,relation,evidence}-reference.json`にあります。

## Verification status

- `EXACT_EQUALITY`: canonicalまたはkernel-backedなexact equality。
- `CERTIFIED_WITHIN_ERROR_BOUND`: 適用可能なcertified boundが存在。
- `CERTIFIED_INTERVAL_OVERLAP`: certified enclosureが重なる。equalityではない。
- `EMPIRICALLY_WITHIN_TOLERANCE`: runtime observationのみ。
- `OUTSIDE_CERTIFIED_BOUND`: 観測結果が適用bound外。
- `BOUND_NOT_AVAILABLE`: relationは分かってもcertified boundがない。
- `UNRESOLVED`: type/domain/effect/contract/proof情報が不足。

## Relation

exactなのは`EXACT_EQUALITY`と`EXACT_UNDER_ASSUMPTIONS`だけです。
`APPROXIMATION_OF`、`DISCRETIZATION_OF`、`TRUNCATED_TO`、`SAMPLED_AS`、
`ALGORITHMICALLY_REALIZED_BY`はRelation Graph edgeでありexact e-classへmergeしません。

## Evidence

`KERNEL_VERIFIED`はLean固有の最強classです。`FORMALLY_DERIVED`、
`REFERENCE_CONTRACT`、provider-backed、runtime、structural、`USER_DECLARED`は
別々の保証境界です。`UNRESOLVED`をverified扱いせず、仮定・contract・opaque nodeを確認します。

