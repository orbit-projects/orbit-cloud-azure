# orbit-cloud-azure: development

The supported Python range is declared in `pyproject.toml`. Local checks do not establish hosted CI or cloud-service compatibility.

```bash
python -m pip install -e '.[dev]'
pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Provider tests use fake SDK clients and do not require cloud credentials. Live inventory checks must be separately opted in and run against a dedicated non-production account/project/subscription.
