"""
Tests for the yamler utility functions.
"""
import pytest
from scicd.yamler import nest_dict

def test_nest_dict_simple():
    flat = {"a": 1, "b": 2}
    expected = {"a": 1, "b": 2}
    assert nest_dict(flat) == expected

def test_nest_dict_nested():
    flat = {"a.b.c": 1, "a.b.d": 2, "x.y": 3}
    expected = {
        "a": {
            "b": {
                "c": 1,
                "d": 2
            }
        },
        "x": {
            "y": 3
        }
    }
    assert nest_dict(flat) == expected

def test_nest_dict_collision():
    # If a key is both a branch and a leaf, we preserve the leaf under _value
    flat = {"a": 1, "a.b": 2}
    # Current implementation behavior:
    # 1. current['a'] = 1
    # 2. parts = ['a', 'b'], current = nested
    # 3. current['a'] is int, so it becomes {'_value': 1}
    # 4. current['a']['b'] = 2
    expected = {"a": {"_value": 1, "b": 2}}
    assert nest_dict(flat) == expected

def test_nest_dict_delimiter():
    flat = {"a/b/c": 1}
    expected = {"a": {"b": {"c": 1}}}
    assert nest_dict(flat, delimiter="/") == expected
