# SPDX-License-Identifier: AGPL-3.0-or-later
import re

import showrunner


def test_version_is_set() -> None:
    assert re.match(r"^\d+\.\d+\.\d+", showrunner.__version__)
