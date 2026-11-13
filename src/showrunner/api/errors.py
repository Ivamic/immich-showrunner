# SPDX-License-Identifier: AGPL-3.0-or-later
"""API errors. The page translates ``code`` (with ``params``) into the language of the user."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, **params: Any) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.params = params


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status_code, content={"code": exc.code, "params": exc.params}
    )
