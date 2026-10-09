import hashlib

from aml.datagen.rng import stable_hash, table_rng


def test_stable_hash_pinned_value() -> None:
    expected = int.from_bytes(hashlib.sha256(b"customers").digest()[:8], "big")
    assert stable_hash("customers") == expected
    assert stable_hash("customers") == PINNED_CUSTOMERS_HASH


def test_table_rng_is_deterministic() -> None:
    a = table_rng(42, "customers").integers(0, 1_000_000, 10)
    b = table_rng(42, "customers").integers(0, 1_000_000, 10)
    assert a.tolist() == b.tolist()


def test_table_rng_differs_by_name() -> None:
    a = table_rng(42, "customers").integers(0, 1_000_000, 10)
    b = table_rng(42, "accounts").integers(0, 1_000_000, 10)
    assert a.tolist() != b.tolist()


def test_table_rng_differs_by_seed() -> None:
    a = table_rng(1, "customers").integers(0, 1_000_000, 10)
    b = table_rng(2, "customers").integers(0, 1_000_000, 10)
    assert a.tolist() != b.tolist()


PINNED_CUSTOMERS_HASH = 2444083866853737421
