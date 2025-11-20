import pytest
import json
import hashlib
from ark_engine.core.loader import ArkLoader
from ark_engine.core.models import ArkModule

def test_checksum_logic():
    data = {"a": 1, "b": 2}
    expected = hashlib.sha256(b'{"a": 1, "b": 2}').hexdigest()
    assert ArkLoader._calculate_checksum(data) == expected

def test_load_non_existent_file():
    with pytest.raises(FileNotFoundError):
        ArkLoader.load("fake.ark")
