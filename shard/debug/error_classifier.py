class FailureType:
    GENERIC = "generic"


def classify_error(stderr: str) -> str:
    # Minimal classifier stub.
    return FailureType.GENERIC

