import os
import tempfile

# Importing app.main reads settings and persists a session key under the data
# path, so point both somewhere disposable before any app module is imported.
os.environ.setdefault("DRYDOCK_DATA_PATH", tempfile.mkdtemp(prefix="drydock-test-"))
os.environ.setdefault("DRYDOCK_REPO_PATH", tempfile.mkdtemp(prefix="drydock-repo-"))
os.environ.setdefault("DRYDOCK_SECRET_KEY", "test-secret-key")
