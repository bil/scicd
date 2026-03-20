# Testing

SciCD uses `pytest` for all unit and integration tests.

## Running Tests

Run the full suite from the project root:

```bash
pytest
```

## Key Test Suites

- **`tests/test_luigi.py`**: Verifies the full Luigi execution lifecycle and frontend-to-DAG resolution.
- **`tests/test_gitlab.py`**: Validates YAML linting, JSON parameter integrity, and SliceNode child pipelines.
- **`tests/test_overrides.py`**: Verifies CLI argument namespacing, validation, and type-casting.
- **`tests/test_config_discovery.py`**: Ensures configuration files are found in the correct priority order.

## Testing Conventions

- **Mocking**: Use the `mocker` fixture (from `pytest-mock`) for system calls and environment state.
- **Fixtures**: Use `tmp_path` for any test requiring filesystem interactions.
