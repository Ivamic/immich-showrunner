# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
