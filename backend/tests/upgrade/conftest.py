import pytest

from .v31_fixture import build_v31_install


@pytest.fixture(scope="module")
def v31_install(tmp_path_factory):
    return build_v31_install(tmp_path_factory.mktemp("v31-install"))
