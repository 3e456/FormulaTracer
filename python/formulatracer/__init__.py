"""Public FormulaTracer project-audit API."""

from cpp_audit.project import (ArtifactOutput, AuditOutputResult, AuditRootResult,
                               CallEdge, CppFrontend, CrossLanguageCallEdge, DatasetOutput, DefinitionEdge,
                               DependencyEdge, DependencyResolver,
                               ExpressionTarget, ExternalSymbol, FFIBoundary, FormulaTracer, IOProvenance,
                               ImportEdge, IncludeEdge, LanguageFrontend, ModuleNode, OutputSink, OutputTarget,
                               OutputTargetKind, ProjectAnalyzer, ProjectAuditResult,
                               ProjectDependencyGraph, ProjectStatus,
                               PythonDependencyResolver, PythonFrontend, ReExportEdge,
                               LanguageBoundary, NativeExtension, RuntimeEvidence, RustFrontend, SerializationBoundary, SharedDependencyKind,
                               SymbolNode, ValueDependencyEdge, VariableTarget)
from cpp_audit.rust_project import (CargoCrate, CargoDependency, CargoDependencyKind,
                                    CargoPackage, CargoWorkspace, FFIResolutionStatus,
                                    RustDependencyResolver, RustProjectAnalyzer)
from cpp_audit.rust_contracts import RustLibraryContract, RustLibraryContractRegistry
from cpp_audit.cpp_project import (CppCompilationEnvironment, CppCompileCommand,
                                   CppDependencyResolver, CppEnvironmentResolver,
                                   CppProjectAnalyzer, CppSource, parse_cpp_source)
from cpp_audit.interval import (AffineForm, BranchStatus, DependencyAwareRange,
                                ErrorInterval, InputRange, Interval, IntervalEngine,
                                IntervalEvidence, IntervalObligation, IntervalProofStatus,
                                IntervalPropagation, OutputRangeConstraint, RangeEnclosure,
                                RangeSpecification, RangeStatus, SymbolicBound, ValueInterval,
                                analyze_project_ranges)
from cpp_audit.end_to_end import (ArtifactEnclosure, EnclosureEvidence, EndToEndEnclosure,
                                  EndToEndProofChain, EndToEndStatus, EndToEndVerificationClaim,
                                  ErrorCompletenessStatus, LayerVerification, VerificationLayer,
                                  build_end_to_end_claims)
from cpp_audit.semantic_debugger import (AffectedOutput, AuditDebugger, AuditDebugResult,
    CounterexampleCandidate, CounterexampleSearchResult, DebugFinding, DebugLocalizationLevel,
    DebugLocalizationMetrics, DebugTrace, DivergenceType, MinimalReproducer,
    ErrorAmplificationPoint, ErrorContribution, FailureRegion, FirstSemanticDivergence,
    MinimalDivergentSubgraph, RootCauseCandidate, RootCauseConfidence, SemanticDivergence,
    aggregate_localization_metrics, debug_project, search_counterexamples)
from cpp_audit.probability import (CLTValidation, Covariance, DistributionKind, DistributionValidation,
    EmpiricalDistributionValidation, EmpiricalEstimator, Estimator, EstimatorTarget, Expectation,
    IndependenceValidation, KnownDistribution, MonteCarloEstimate, ParallelRandomness,
    ProbabilityAuditResult, ProbabilisticEnclosure, SamplingError, UserDefinedDistribution, Variance,
    audit_probability, classify_random_source, extract_estimator, monte_carlo_estimate, validate_clt,
    validate_distribution, validate_empirical_distribution, validate_independence)
from cpp_audit.synthesis import (AlgorithmIR, CodeSynthesisResult, CrossLanguageSynthesisResult,
    ExpectedImplementationIR, GeneratedImplementation, ImplementationConstraints, RepairCandidate,
    RepairVerificationResult, RoundTripVerification, SynthesisDivergence, TheorySpecification,
    propose_repair, synthesize, synthesize_cross_language, verify_repair, verify_round_trip)
from cpp_audit.major_ecosystem import (ContractImpact, EcosystemContract, EcosystemCoverage,
    LibraryVersionDiff, MajorEcosystemReport, diff_library_versions, harvest_major_ecosystem_contracts)
from cpp_audit.library_coverage import (LibraryBackend, LibraryCapability, LibraryLoweringRule,
    classify_apis, library_backends, real_world_gap_analysis, run_self_generation_smoke)
from cpp_audit.assurance_release import (AssuranceMetrics, AssuranceReport, AuditBundle, AuditDiff,
    MutationOutcome, RealWorldValidationSummary, audit_diff, create_audit_bundle,
    localized_certificate, run_assurance_suite, summarize_real_world, verify_audit_bundle)
from cpp_audit.research_provenance import (AcceptedAuditBaseline, AuditCacheKey, AuditProfile,
    CacheLookupResult, ConfigurationParameter, ConfigurationSource, DataLineage, DatasetSchema,
    DatasetTransformation, DependencyProvenance, DomainPack, EnvironmentSnapshot, ExtensionPackManifest,
    FieldSchema, GitSourceProvenance, IncrementalAuditCache, IncrementalAuditPlan, InputArtifact,
    IncrementalAuditResult,
    MissingEvidence, ParameterResolutionStep, ParameterResolutionTrace, ProvenanceEdge,
    ProvenanceEdgeKind, ProvenanceNode, ProvenanceNodeKind, ResearchProvenanceGraph,
    KnowledgePack, ProviderPack, ResolutionSuggestion, SchemaChangeKind, SensitivityFinding, TestCaseCandidate,
    augment_project_provenance, build_cache_key, build_data_lineage, capture_environment,
    capture_git_provenance, compare_dataset_schemas, explain_result, explain_unresolved, load_extension_pack,
    current_source_hashes, generate_test_candidates, plan_incremental_audit, profile_acceptance,
    provenance_coverage, resolve_configuration, run_incremental_audit, sensitivity_report)
from cpp_audit.execution_sandbox import (SandboxExecutionEvidence, SandboxPolicy, run_sandboxed)
from cpp_audit.provenance_assurance import (ProvenanceAssuranceCase, ProvenanceAssuranceReport,
                                             run_provenance_assurance)
from cpp_audit.self_audit import (DEFAULT_SEED, GENERATOR_VERSION, TheoryCase,
                                  backend_capabilities, generate_theory_corpus,
                                  run_large_scale_self_audit)
from cpp_audit.generation_planning import (CandidateMatch, GeneratedMathematicalImplementation,
    GenerationDecision, GenerationPlan, MathematicalFormula, MathematicalPatternIndex, ProviderContract, SearchBudget, default_provider_registry,
    function, mathematical_features, plan_generation)
from cpp_audit.math_surface import (AntiUnificationResult, CanonicalSymbolRegistry, MathBuilder, MathSurfaceAST,
    MathematicalSubstitution, NotationResolutionError, SymbolDeclaration, TypedPattern, UnificationResult, anti_unify, canonical_equal,
    generalize, instantiate, parse_tex, to_dsl, to_json, to_markdown, to_tex, to_unicode, typed_unify)
from cpp_audit.math_semantics import (CertifiedRange, ConvergenceResult, Domain, EvidenceStatus,
    FourierSeries, FunctionProperties, InfiniteProcess, MathematicalDebugLocation, MathematicalRelation, OriginSet, PowerSeries, Sequence, SourceOrigin,
    TaylorSeries,
    TransformSemantics, TruncationRequirement, TruncationRequirementSolver, TruncationSolution,
    analyze_convergence, convolution, discrete_transform_layers, function_properties, integral_transform,
    inverse_mapping, localize_mathematical_node, propagate_properties, range_condition_status, series_evaluation_candidates)
from cpp_audit.transformations import (BoundedRewriteResult, RewriteRuleDescriptor, RewriteState,
    bounded_rewrite_search, load_rewrite_catalog)
from cpp_audit.equality_saturation import (EClass, EGraphMatchResult, ENode, EqualityTraceStep,
    ExactEqualitySaturator, FactConflict, MathematicalFact, MathematicalFactEngine,
    MathematicalRelationGraph, RelationEdge, RelationKind, RewritePack, SaturationBudget,
    SaturationResult, SaturationStatus, TypedEGraph, load_rewrite_packs,
    replay_equality_trace, saturate_and_match, select_rewrite_packs)
from cpp_audit.bitvector import (BitAssuranceResult, BitEncoding, BitRepresentation, NumeralRepresentation,
    OverflowSemantics as BitOverflowSemantics, ShiftSemantics, Signedness, bit_field_extract,
    bit_field_insert, bit_ir, decode_bits, encode_bits, evaluate_bit_operation,
    recognize_bit_field_extract, representation_for_dtype, representation_from_dict,
    run_exhaustive_bit_assurance)
from cpp_audit.logic_semantics import (BranchDomain, PiecewiseDomainAnalysis, analyze_piecewise_domains,
    canonicalize_logic, indicator, piecewise, predicate, select)
from cpp_audit.mathematical_knowledge import (KnowledgeEvidenceKind, KnowledgeRelationKind,
    MathematicalKnowledgeEntry, MathematicalKnowledgeRegistry)
from cpp_audit.mathematical_primitives import (MathematicalPrimitive, mathematical_primitive_registry,
                                                primitive_categories)
from cpp_audit.algebraic_domains import (AlgebraicStructure, DomainSemantics, NumericDomain,
    domain_facts, structure_closure, structure_fact)
from cpp_audit.units import (LENGTH, MASS, TEMPERATURE, TIME, PhysicalDimension, Quantity, Unit)
from cpp_audit.knowledge_assurance import (KnowledgeAssuranceCase, KnowledgeAssuranceReport,
                                           run_knowledge_assurance)
from cpp_audit.math_assurance import (AdversarialOutcome, MathematicalAssuranceReport,
    RetrievalOutcome, run_mathematical_assurance)
from .native import (NativeCallError, NativeContext, NativeFormula, NativeFunctionalValue, NativeLibrary, NativeMathematicalFunction, NativeRangeValue,
                     NativeEvidence, NativeRelation, NativeResult, NativeResultValue,
                     NativeSemanticObjectValue, NativeUnavailableError,
                     compare_ir, execute_native_kernel, native_available)
from .runtime_paths import (observe_python_semantic_runtime, record_semantic_path,
                            semantic_execution_scope,
                            reset_semantic_runtime_metrics,
                            semantic_runtime_events, semantic_runtime_snapshot,
                            write_semantic_runtime_snapshot)
from .structural import (QuotientNormalizationResult, StructuralIsomorphismResult,
                         quotient_normalize, structural_isomorphism)
from .reconstruction import ReconstructionResult, reconstruct

__all__ = ["FormulaTracer", "ProjectAnalyzer", "LanguageFrontend", "PythonFrontend",
           "RustFrontend", "CppFrontend", "DependencyResolver", "PythonDependencyResolver",
           "ProjectDependencyGraph", "ModuleNode", "SymbolNode", "DependencyEdge", "ImportEdge", "IncludeEdge",
           "CallEdge", "ValueDependencyEdge", "DefinitionEdge", "ReExportEdge",
           "CrossLanguageCallEdge", "ExternalSymbol", "LanguageBoundary", "FFIBoundary", "NativeExtension", "RuntimeEvidence",
           "ProjectAuditResult", "AuditRootResult", "AuditOutputResult",
           "OutputTarget", "VariableTarget", "ExpressionTarget", "OutputTargetKind",
           "OutputSink", "ArtifactOutput", "DatasetOutput", "SerializationBoundary",
           "IOProvenance", "ProjectStatus", "SharedDependencyKind",
           "RustDependencyResolver", "RustProjectAnalyzer", "CargoWorkspace", "CargoPackage",
           "CargoCrate", "CargoDependency", "CargoDependencyKind", "FFIResolutionStatus",
           "RustLibraryContract", "RustLibraryContractRegistry",
           "CppDependencyResolver", "CppEnvironmentResolver", "CppProjectAnalyzer",
           "CppCompilationEnvironment", "CppCompileCommand", "CppSource", "parse_cpp_source"]
__all__ += ["Interval", "ValueInterval", "ErrorInterval", "RangeEnclosure",
            "IntervalEvidence", "IntervalPropagation", "IntervalObligation",
            "RangeStatus", "IntervalProofStatus", "BranchStatus", "SymbolicBound",
            "AffineForm", "DependencyAwareRange", "InputRange", "OutputRangeConstraint",
            "RangeSpecification", "IntervalEngine", "analyze_project_ranges"]
__all__ += ["EndToEndEnclosure", "EndToEndVerificationClaim", "EndToEndProofChain",
            "VerificationLayer", "EndToEndStatus", "ErrorCompletenessStatus",
            "ArtifactEnclosure", "EnclosureEvidence", "LayerVerification",
            "build_end_to_end_claims"]
__all__ += ["AffectedOutput", "AuditDebugger", "AuditDebugResult", "CounterexampleCandidate",
            "CounterexampleSearchResult", "DebugFinding", "DebugLocalizationLevel", "DebugLocalizationMetrics",
            "DebugTrace", "DivergenceType", "MinimalReproducer",
            "ErrorAmplificationPoint", "ErrorContribution", "FailureRegion", "FirstSemanticDivergence",
            "MinimalDivergentSubgraph", "RootCauseCandidate", "RootCauseConfidence",
            "SemanticDivergence", "aggregate_localization_metrics", "debug_project", "search_counterexamples"]
__all__ += ["CLTValidation", "Covariance", "DistributionKind", "DistributionValidation",
            "EmpiricalDistributionValidation", "EmpiricalEstimator", "Estimator", "EstimatorTarget",
            "Expectation", "IndependenceValidation", "KnownDistribution", "MonteCarloEstimate",
            "ParallelRandomness", "ProbabilityAuditResult", "ProbabilisticEnclosure", "SamplingError",
            "UserDefinedDistribution", "Variance", "audit_probability", "classify_random_source",
            "extract_estimator", "monte_carlo_estimate", "validate_clt", "validate_distribution",
            "validate_empirical_distribution", "validate_independence"]
__all__ += ["AlgorithmIR", "CodeSynthesisResult", "CrossLanguageSynthesisResult",
            "ExpectedImplementationIR", "GeneratedImplementation", "ImplementationConstraints",
            "RepairCandidate", "RepairVerificationResult", "RoundTripVerification",
            "SynthesisDivergence", "TheorySpecification", "propose_repair", "synthesize",
            "synthesize_cross_language", "verify_repair", "verify_round_trip"]
__all__ += ["ContractImpact", "EcosystemContract", "EcosystemCoverage", "LibraryVersionDiff",
            "MajorEcosystemReport", "diff_library_versions", "harvest_major_ecosystem_contracts"]
__all__ += ["LibraryBackend", "LibraryCapability", "LibraryLoweringRule", "classify_apis",
            "library_backends", "real_world_gap_analysis", "run_self_generation_smoke"]
__all__ += ["AssuranceMetrics", "AssuranceReport", "AuditBundle", "AuditDiff", "MutationOutcome",
            "RealWorldValidationSummary", "audit_diff", "create_audit_bundle",
            "localized_certificate", "run_assurance_suite", "summarize_real_world", "verify_audit_bundle"]
__all__ += ["AcceptedAuditBaseline", "AuditCacheKey", "AuditProfile", "CacheLookupResult",
            "ConfigurationParameter", "ConfigurationSource", "DataLineage", "DatasetSchema",
            "DatasetTransformation", "DependencyProvenance", "EnvironmentSnapshot",
            "DomainPack", "ExtensionPackManifest", "FieldSchema", "GitSourceProvenance", "IncrementalAuditCache",
            "IncrementalAuditPlan", "IncrementalAuditResult", "InputArtifact", "MissingEvidence", "ParameterResolutionStep",
            "ParameterResolutionTrace", "ProvenanceEdge", "ProvenanceEdgeKind", "ProvenanceNode",
            "ProvenanceNodeKind", "ResearchProvenanceGraph", "ResolutionSuggestion",
            "KnowledgePack", "ProviderPack", "SchemaChangeKind", "SensitivityFinding", "TestCaseCandidate",
            "augment_project_provenance", "build_cache_key", "build_data_lineage",
            "capture_environment", "capture_git_provenance", "compare_dataset_schemas",
            "current_source_hashes", "explain_result", "explain_unresolved", "generate_test_candidates", "load_extension_pack",
            "plan_incremental_audit", "profile_acceptance", "provenance_coverage",
            "resolve_configuration", "run_incremental_audit", "sensitivity_report"]
__all__ += ["SandboxExecutionEvidence", "SandboxPolicy", "run_sandboxed"]
__all__ += ["ProvenanceAssuranceCase", "ProvenanceAssuranceReport", "run_provenance_assurance"]
__all__ += ["DEFAULT_SEED", "GENERATOR_VERSION", "TheoryCase", "backend_capabilities",
            "generate_theory_corpus", "run_large_scale_self_audit"]
__all__ += ["CandidateMatch", "GeneratedMathematicalImplementation", "GenerationDecision", "GenerationPlan",
            "MathematicalFormula", "MathematicalPatternIndex", "ProviderContract", "SearchBudget", "default_provider_registry",
            "function", "mathematical_features", "plan_generation", "CanonicalSymbolRegistry",
            "AntiUnificationResult", "MathBuilder", "MathSurfaceAST", "MathematicalSubstitution", "NotationResolutionError", "SymbolDeclaration",
            "TypedPattern", "UnificationResult", "canonical_equal", "generalize", "instantiate",
            "anti_unify", "parse_tex", "to_dsl", "to_json", "to_markdown", "to_tex", "to_unicode", "typed_unify", "CertifiedRange",
            "ConvergenceResult", "Domain", "EvidenceStatus", "FourierSeries", "FunctionProperties", "InfiniteProcess",
            "MathematicalDebugLocation", "PowerSeries", "TaylorSeries",
            "MathematicalRelation", "OriginSet", "Sequence", "SourceOrigin", "TransformSemantics",
            "TruncationRequirement", "TruncationRequirementSolver", "TruncationSolution",
            "analyze_convergence", "discrete_transform_layers", "function_properties",
            "integral_transform", "inverse_mapping", "localize_mathematical_node", "convolution", "propagate_properties",
            "range_condition_status", "series_evaluation_candidates", "BoundedRewriteResult", "RewriteRuleDescriptor", "RewriteState",
            "bounded_rewrite_search", "load_rewrite_catalog", "EClass", "EGraphMatchResult", "ENode",
            "EqualityTraceStep", "ExactEqualitySaturator", "FactConflict", "MathematicalFact",
            "MathematicalFactEngine", "MathematicalRelationGraph", "RelationEdge", "RelationKind",
            "RewritePack", "SaturationBudget", "SaturationResult", "SaturationStatus", "TypedEGraph",
            "load_rewrite_packs", "replay_equality_trace", "saturate_and_match", "select_rewrite_packs"]
__all__ += ["BitAssuranceResult", "BitEncoding", "BitRepresentation", "NumeralRepresentation",
            "BitOverflowSemantics", "ShiftSemantics", "Signedness", "bit_field_extract", "bit_field_insert",
            "bit_ir", "decode_bits", "encode_bits", "evaluate_bit_operation", "recognize_bit_field_extract",
            "representation_for_dtype", "representation_from_dict", "run_exhaustive_bit_assurance",
            "BranchDomain", "PiecewiseDomainAnalysis", "analyze_piecewise_domains", "canonicalize_logic",
            "indicator", "piecewise", "predicate", "select", "KnowledgeEvidenceKind", "KnowledgeRelationKind",
            "MathematicalKnowledgeEntry", "MathematicalKnowledgeRegistry", "MathematicalPrimitive",
            "mathematical_primitive_registry", "primitive_categories", "AlgebraicStructure", "DomainSemantics",
            "NumericDomain", "domain_facts", "structure_closure", "structure_fact", "LENGTH", "MASS",
            "TEMPERATURE", "TIME", "PhysicalDimension", "Quantity", "Unit"]
__all__ += ["KnowledgeAssuranceCase", "KnowledgeAssuranceReport", "run_knowledge_assurance"]
__all__ += ["AdversarialOutcome", "MathematicalAssuranceReport", "RetrievalOutcome",
            "run_mathematical_assurance"]
__all__ += ["NativeCallError", "NativeContext", "NativeFormula", "NativeLibrary",
            "NativeEvidence", "NativeRelation", "NativeResult", "NativeResultValue", "NativeMathematicalFunction",
            "NativeFunctionalValue", "NativeRangeValue",
            "NativeSemanticObjectValue", "NativeUnavailableError", "compare_ir", "execute_native_kernel",
            "native_available"]
__all__ += ["record_semantic_path", "reset_semantic_runtime_metrics",
            "semantic_runtime_events", "semantic_runtime_snapshot",
            "write_semantic_runtime_snapshot", "observe_python_semantic_runtime",
            "semantic_execution_scope"]
__all__ += ["QuotientNormalizationResult", "StructuralIsomorphismResult",
            "quotient_normalize", "structural_isomorphism"]
__all__ += ["ReconstructionResult", "reconstruct"]
