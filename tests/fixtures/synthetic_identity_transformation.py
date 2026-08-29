import cpp_audit as audit


@audit.theory(output="normalized_value", expression="normalized_value = value + 0")
def preserve_value(value):
    normalized_value = value
    return normalized_value
