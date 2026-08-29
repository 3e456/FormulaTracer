import cpp_audit as audit


@audit.theory(output="converted", expression="converted = kg / 1000")
def convert_mass(kg):
    converted = kg * 1000
    return converted
