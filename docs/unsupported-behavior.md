# Unsupported behavior

The initial frontend rejects compiler extensions, unresolved calls, unknown
effects, unregistered standard APIs, `std::reduce` where ordered reduction is
required, implicit `double`-to-`float` accumulation, unprovable aliasing, invalid
ranges, and unsupported C++ outside the documented weighted-sum subset.

Concurrency, atomics, execution policies, I/O, clocks, random sources,
filesystem state, arbitrary templates, pointer arithmetic, reallocation and
iterator invalidation have no complete semantics in this release.

