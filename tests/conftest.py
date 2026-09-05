import os
from tempfile import TemporaryDirectory

# Never let test imports create data in /data or use a developer's credentials.
_test_data = TemporaryDirectory(prefix="tg-sign-tests-")
os.environ["APP_DATA_DIR"] = _test_data.name
os.environ["APP_SECRET_KEY"] = "isolated-regression-test-secret"
os.environ["APP_DATABASE_URL"] = f"sqlite:///{_test_data.name}/test.sqlite"
