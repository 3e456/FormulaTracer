import cpp_audit as audit

from constants import SCALE


@audit.theory(output="converted", expression="converted = kg / 1000")
def convert_mass(kg):
    converted = kg / SCALE
    return converted
