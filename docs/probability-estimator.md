# Simplified probability, estimators, and Monte Carlo

FormulaTracer maps known random APIs to reference-contract distributions and
accepts explicit user distributions without guessing the law of a custom
sampler.

```python
distribution = UserDefinedDistribution(pdf="6*x*(1-x)", support=(0, 1))
audit = result.audit_probability(distribution=distribution, samples=samples)
```

Definition validation and sampler conformance are separate. PDF/PMF validation
checks support, nonnegativity, and numerical normalization and is labelled
`NUMERICALLY_CHECKED`. Empirical validation uses empirical-CDF distance plus a
Wasserstein-style CDF discrepancy and sample-size progression. It never becomes
a formal proof. Serial lag correlations report support, inconsistency, or
inconclusive independence separately; a CLT trend is only supporting evidence.

The estimator recognizer currently identifies sample means expressed as a mean
reduction or a finite sum divided by sample size. An `EstimatorTarget` must come
from the user or a reference contract. For IID samples with finite bounded
support, the Monte Carlo layer instantiates a Hoeffding reference-theorem bound
and emits `P(|estimate-target| <= epsilon) >= 1-alpha` under explicit
assumptions. Unknown support, IID, or sampling semantics remain unresolved.

Parallel randomness retains shared/separate RNG state, stream policy,
independence status, and reproducibility. FormulaTracer does not inspect PRNG
internals, prove physical randomness, or treat a single p-value as validation.
MCMC and general Bayesian inference remain out of scope.
