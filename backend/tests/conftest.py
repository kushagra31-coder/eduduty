import os
import inspect
from starlette.testclient import TestClient as StarletteTestClient
import auth

os.environ["ENV"] = "local"
os.environ["AUTH_DISABLED"] = "false"

_orig_init = StarletteTestClient.__init__


def _patched_init(self, app, *args, **kwargs):
    frame = inspect.currentframe()
    in_test_auth = False
    while frame:
        filename = frame.f_code.co_filename
        if "test_auth" in filename:
            in_test_auth = True
            break
        frame = frame.f_back

    if not in_test_auth:
        headers = kwargs.get("headers")
        if headers is None:
            headers = {}
            kwargs["headers"] = headers
        if "Authorization" not in headers:
            token = auth.create_jwt_token(
                user_id=1,
                role="coordinator",
                email="coord@eduduty.local",
                name="Coordinator User",
            )
            headers["Authorization"] = f"Bearer {token}"

    _orig_init(self, app, *args, **kwargs)


StarletteTestClient.__init__ = _patched_init
