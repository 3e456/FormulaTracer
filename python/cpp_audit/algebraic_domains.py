"""Algebraic-structure and mathematical-domain requirements for rewrites."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class AlgebraicStructure(str, Enum):
    SEMIGROUP = "SEMIGROUP"
    MONOID = "MONOID"
    SEMIRING = "SEMIRING"
    COMMUTATIVE_SEMIRING = "COMMUTATIVE_SEMIRING"
    GROUP = "GROUP"
    COMMUTATIVE_GROUP = "COMMUTATIVE_GROUP"
    RING = "RING"
    COMMUTATIVE_RING = "COMMUTATIVE_RING"
    INTEGRAL_DOMAIN = "INTEGRAL_DOMAIN"
    FIELD = "FIELD"
    BOOLEAN_ALGEBRA = "BOOLEAN_ALGEBRA"
    VECTOR_SPACE = "VECTOR_SPACE"
    MATRIX_ALGEBRA = "MATRIX_ALGEBRA"
    MODULAR_RING = "MODULAR_RING"
    FINITE_FIELD = "FINITE_FIELD"
    BITVECTOR_ALGEBRA = "BITVECTOR_ALGEBRA"


class NumericDomain(str, Enum):
    NATURAL = "NATURAL"
    INTEGER = "INTEGER"
    RATIONAL = "RATIONAL"
    REAL = "REAL"
    COMPLEX = "COMPLEX"
    MODULAR_INTEGER = "MODULAR_INTEGER"
    FINITE_FIELD = "FINITE_FIELD"
    BOOLEAN = "BOOLEAN"
    BITVECTOR = "BITVECTOR"


_PARENTS = {
    AlgebraicStructure.MONOID: {AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.GROUP: {AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.COMMUTATIVE_GROUP: {AlgebraicStructure.GROUP, AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.SEMIRING: {AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.COMMUTATIVE_SEMIRING: {AlgebraicStructure.SEMIRING, AlgebraicStructure.MONOID,
                                              AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.RING: {AlgebraicStructure.SEMIRING, AlgebraicStructure.GROUP,
                              AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.COMMUTATIVE_RING: {AlgebraicStructure.RING, AlgebraicStructure.COMMUTATIVE_SEMIRING,
                                         AlgebraicStructure.COMMUTATIVE_GROUP,
                                         AlgebraicStructure.GROUP, AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.INTEGRAL_DOMAIN: {AlgebraicStructure.COMMUTATIVE_RING, AlgebraicStructure.RING,
                                         AlgebraicStructure.COMMUTATIVE_GROUP, AlgebraicStructure.GROUP,
                                         AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.FIELD: {AlgebraicStructure.INTEGRAL_DOMAIN, AlgebraicStructure.COMMUTATIVE_RING,
                               AlgebraicStructure.RING, AlgebraicStructure.COMMUTATIVE_GROUP,
                               AlgebraicStructure.GROUP, AlgebraicStructure.MONOID, AlgebraicStructure.SEMIGROUP},
    AlgebraicStructure.FINITE_FIELD: {AlgebraicStructure.FIELD, AlgebraicStructure.INTEGRAL_DOMAIN,
                                      AlgebraicStructure.COMMUTATIVE_RING, AlgebraicStructure.RING},
    AlgebraicStructure.MODULAR_RING: {AlgebraicStructure.COMMUTATIVE_RING, AlgebraicStructure.RING},
}


_DOMAIN_STRUCTURES = {
    NumericDomain.NATURAL: {AlgebraicStructure.COMMUTATIVE_SEMIRING},
    NumericDomain.INTEGER: {AlgebraicStructure.COMMUTATIVE_RING},
    NumericDomain.RATIONAL: {AlgebraicStructure.FIELD},
    NumericDomain.REAL: {AlgebraicStructure.FIELD},
    NumericDomain.COMPLEX: {AlgebraicStructure.FIELD},
    NumericDomain.MODULAR_INTEGER: {AlgebraicStructure.MODULAR_RING},
    NumericDomain.FINITE_FIELD: {AlgebraicStructure.FINITE_FIELD},
    NumericDomain.BOOLEAN: {AlgebraicStructure.BOOLEAN_ALGEBRA},
    NumericDomain.BITVECTOR: {AlgebraicStructure.BITVECTOR_ALGEBRA},
}


def _reference_structure_closure(structures: Iterable[AlgebraicStructure | str]) -> frozenset[AlgebraicStructure]:
    values = {item if isinstance(item, AlgebraicStructure) else AlgebraicStructure(item) for item in structures}
    changed = True
    while changed:
        changed = False
        for item in tuple(values):
            for parent in _PARENTS.get(item, ()):
                if parent not in values: values.add(parent); changed = True
    return frozenset(values)


def structure_closure(structures: Iterable[AlgebraicStructure | str]) -> frozenset[AlgebraicStructure]:
    """Return the Rust-owned algebraic closure through the stable kernel boundary."""
    from formulatracer.native import execute_native_kernel
    values = [item.value if isinstance(item, AlgebraicStructure) else AlgebraicStructure(item).value
              for item in structures]
    result = execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                                    "operation": "STRUCTURE_CLOSURE",
                                    "structures": values})["result"]
    return frozenset(AlgebraicStructure(item) for item in result["structures"])


@dataclass(frozen=True)
class DomainSemantics:
    domain: NumericDomain
    structures: frozenset[AlgebraicStructure]
    characteristic: int | None = 0
    modulus: int | None = None
    commutative_multiplication: bool = True

    @classmethod
    def for_domain(cls, domain: NumericDomain | str, *, modulus: int | None = None) -> "DomainSemantics":
        from formulatracer.native import execute_native_kernel
        value = domain if isinstance(domain, NumericDomain) else NumericDomain(domain)
        supported = []
        for structure in AlgebraicStructure:
            result = execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                                            "operation": "SUPPORTS_STRUCTURE",
                                            "domain": value.value,
                                            "structure": structure.value})["result"]
            if result["status"] == "PROVEN_TRUE":
                supported.append(structure)
        structures = frozenset(supported)
        characteristic = modulus if value == NumericDomain.MODULAR_INTEGER else 0
        return cls(value, structures, characteristic, modulus,
                   AlgebraicStructure.MATRIX_ALGEBRA not in structures)

    def satisfies(self, required: Iterable[AlgebraicStructure | str]) -> bool:
        from formulatracer.native import execute_native_kernel
        for item in required:
            structure = item if isinstance(item, AlgebraicStructure) else AlgebraicStructure(item)
            result = execute_native_kernel({"schema_version": "1.0", "kernel": "A",
                                            "operation": "SUPPORTS_STRUCTURE",
                                            "domain": self.domain.value,
                                            "structure": structure.value})["result"]
            if result["status"] != "PROVEN_TRUE":
                return False
        return True


def structure_fact(structure: AlgebraicStructure | str) -> str:
    value = structure if isinstance(structure, AlgebraicStructure) else AlgebraicStructure(structure)
    return f"algebraic_structure:{value.value}"


def domain_facts(domain: DomainSemantics) -> tuple[str, ...]:
    return (f"numeric_domain:{domain.domain.value}",
            *(structure_fact(item) for item in sorted(domain.structures, key=lambda x: x.value)))
