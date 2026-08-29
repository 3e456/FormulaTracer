import cpp_audit as audit


@audit.theory(output="y", expression="y = 3 * x + 2")
def compute(x):
    y = 3 * x + 2
    return y
