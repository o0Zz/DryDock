import os
import tempfile
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

# Importing app.main reads settings and persists a session key under the data
# path, so point both somewhere disposable before any app module is imported.
os.environ.setdefault("DRYDOCK_DATA_PATH", tempfile.mkdtemp(prefix="drydock-test-"))
os.environ.setdefault("DRYDOCK_REPO_PATH", tempfile.mkdtemp(prefix="drydock-repo-"))
os.environ.setdefault("DRYDOCK_SECRET_KEY", "test-secret-key")


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An admin client. Test files with their own `client` fixture override this one."""
    # Imported here: the environment above must be set before any app module loads.
    from app.core.security import get_current_user
    from app.main import app

    # No `with`: the lifespan (DB init, scheduler) is not needed for these routes.
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, is_admin=True)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
