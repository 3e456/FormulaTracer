# Runtime semantic ownership

FormulaTracer distinguishes four execution scopes: `PRODUCTION`,
`DIFFERENTIAL_VALIDATION`, `REFERENCE_ORACLE`, and `TEST_ONLY`. Completion gates
use only production calls. A Python fallback is a failed native route that
executes Python semantics; a direct Python reference call enters a retained
Python semantic owner without attempting native dispatch. Both must be zero.

Counters retain aggregate calls by path, Kernel, owner, operation, and scope even
when detailed event capture is disabled. Owner-boundary accounting counts entry
from another module; recursion, comprehensions, properties, and private helpers
inside the same owner are not separately counted. This prevents implementation
shape from inflating semantic ownership volume.

The first owner-boundary checkpoint used the sealed external-21 workflow. Before retiring
`math_surface`, it measured 2,066 production semantic calls: 417 native and
1,649 direct Python. Native generalization and anti-unification changed the same
workflow to 1,691 calls: 981 native and 710 direct Python, with fallback zero.
Artifacts stayed 21/21, reconstruction stayed 1 resolved / 20 unresolved, and
false acceptance stayed zero.

After serialization, presentation, plain construction, and registry data access
were explicitly separated from semantic decisions, the same workflow measured
1,314 decisions: 981 native and 333 direct Python. This definition is the
current completion metric; earlier checkpoints remain recorded as measurement
evolution rather than being rewritten.

The historical private research-scale corpus 16,769,199-call result used the older all-frame counter
and is retained as evidence, not silently converted to V2. After E: was
reattached, the complete 24-project corpus was rerun with semantic-decision
filtering. It measured 9,476 production semantic decisions, all direct Python,
with zero fallback. Owner and operation totals both equal 9,476. The dominant
owners are the error composition/error IR SCC (6,707 calls, 70.78%) and semantic
debugger (2,185 calls, 23.06%). The corpus remained 24 projects, 23 analyzed,
170+ source files and 40k+ LOC; it was not modified and research-data content
was not read.

After the Error SCC native cutover, a fresh run of the same corpus measured
4,895 production semantic decisions: 2,178 Rust-native and 2,717 direct Python,
with zero fallback. The native total comprises 2,176
`BUILD_ERROR_ANALYSIS` calls and two `PROPAGATE_ERROR_GRAPH` calls. Direct Python
calls through `error_ir` and `error_composition` are zero; the remaining calls
belong to the 22 still-open semantic owners. Corpus cardinality and read-only
guarantees were unchanged.

After the Kernel E provenance/debugger cutover, the corpus was rerun again. It
measured 3,162 production semantic decisions: 2,870 Rust-native and 292 direct
Python, with zero fallback. Kernel E accounts for 692 native calls: 292
`RESOLVE_CONFIGURATION`, 292 `ASSEMBLE_PROVENANCE`, and 108 `DEBUG_PROJECT`.
Direct Python calls through `research_provenance` and `semantic_debugger` are
both zero. The remaining 292 direct calls belong to `cpp_audit.end_to_end`, not
Kernel E. Corpus cardinality, source hashes, and the read-only guarantees were
unchanged.

Machine-readable evidence is under `output/native_migration/`:

- `runtime-owner-profile.json`
- `runtime-scc-profile.json`
- `migration-checkpoints.json`
- `ownership-graph.json`

Runtime volume prioritizes SCC migration; it is never a completion threshold.
Completion still requires zero Python semantic owners, zero production direct
Python calls, zero fallback, and passed native AuditBundle field parity.

## Final ownership measurement

The final full private research-scale corpus run satisfies that completion rule. It recorded 25,354
production decisions, all Rust-native, with zero direct Python semantic calls
and zero fallback. The external-21 run recorded 63 Rust-native decisions with
the same zero Python counts. Static analysis independently found zero reachable
Python semantic symbols and zero unresolved dynamic dispatch from 543 public
production entrypoints.

These final measurements supersede earlier migration checkpoints for completion
status without rewriting their historical values. The earlier mixed-ownership
counts remain useful evidence of the staged cutover.
