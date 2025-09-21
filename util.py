def iter_bits(k: int) -> list[int]:
    bin_rep = bin(k).replace("0b", "")
    return [int(bit) for bit in "0" * (8 - len(bin_rep)) + bin_rep]
