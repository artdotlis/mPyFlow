def str_to_bytes(val: str) -> bytes:
    return val.encode("utf-8")


def bytes_to_str(val: bytes) -> str:
    return val.decode("utf-8")
