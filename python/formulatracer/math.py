"""TeX-first mathematical construction API."""

from cpp_audit.generation_planning import MathematicalFormula, function, plan_generation
from cpp_audit.math_surface import (CanonicalSymbolRegistry, MathBuilder, MathSurfaceAST,
                                    NotationResolutionError, SymbolDeclaration, canonical_equal,
                                    generalize, instantiate, parse_tex, to_dsl, to_json, to_markdown, to_tex, to_unicode, typed_unify)
from cpp_audit.math_semantics import *

Formula = MathematicalFormula
builder = MathBuilder

__all__ = ["Formula", "MathematicalFormula", "MathBuilder", "builder", "function",
           "plan_generation", "CanonicalSymbolRegistry", "MathSurfaceAST",
           "NotationResolutionError", "SymbolDeclaration", "canonical_equal",
           "generalize", "instantiate", "parse_tex", "to_dsl", "to_json", "to_markdown", "to_tex", "to_unicode", "typed_unify"]
