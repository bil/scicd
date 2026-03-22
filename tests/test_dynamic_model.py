"""Tests for the recursive and unpackable DynamicModel."""

import json
from scicd.config import DynamicModel

def test_dynamic_model_dot_access():
    """Verify that extra fields are accessible via dot-notation."""
    m = DynamicModel(a=1, b="test")
    assert m.a == 1
    assert m.b == "test"

def test_dynamic_model_recursive_nesting():
    """Verify that nested dictionaries are automatically wrapped in DynamicModels."""
    data = {
        "outer": {
            "inner": 123,
            "deep": {
                "leaf": "found"
            }
        }
    }
    m = DynamicModel.model_validate(data)
    
    assert isinstance(m.outer, DynamicModel)
    assert m.outer.inner == 123
    assert isinstance(m.outer.deep, DynamicModel)
    assert m.outer.deep.leaf == "found"

def test_dynamic_model_unpacking():
    """Verify that DynamicModel supports ** unpacking."""
    m = DynamicModel(x=10, y=20)
    
    # 1. Unpacking into a dictionary
    unpacked_dict = {**m}
    assert unpacked_dict == {"x": 10, "y": 20}
    
    # 2. Unpacking into a function call
    def add(x, y):
        return x + y
    
    assert add(**m) == 30

def test_dynamic_model_serialization():
    """Verify that DynamicModel serializes correctly using Pydantic methods."""
    data = {"a": 1, "nested": {"b": 2}}
    m = DynamicModel.model_validate(data)
    
    # Check dict dump
    dump = m.model_dump()
    assert dump == data
    
    # Check JSON dump
    json_dump = m.model_dump_json()
    assert json.loads(json_dump) == data
