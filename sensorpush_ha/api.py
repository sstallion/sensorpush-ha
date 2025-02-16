# Copyright (c) 2025 Steven Stallion <sstallion@gmail.com>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

from __future__ import annotations

from aiohttp import ClientSession
from asyncio import Lock
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from datetime import UTC, datetime, timedelta
from functools import wraps
import json
import logging
from typing import Any, Concatenate, Final

from sensorpush_api import (
    AccessTokenRequest,
    ApiApi,
    ApiClient,
    ApiException,
    AuthorizeRequest,
    Configuration,
    Samples,
    SamplesRequest,
    Sensor,
    SensorsRequest,
)

ACCESS_TOKEN_EXPIRATION: Final = timedelta(minutes=60)
REQUEST_RETRIES: Final = 3
REQUEST_TIMEOUT: Final = timedelta(seconds=15)

logger = logging.getLogger(__package__)


class SensorPushCloudError(Exception):
    """An exception occurred when calling the SensorPush Cloud API."""


class SensorPushCloudAuthError(SensorPushCloudError):
    """An auth exception occurred when calling the SensorPush Cloud API."""


def api_call[**_P, _R](
    func: Callable[Concatenate[SensorPushCloudApi, _P], Awaitable[_R]],
) -> Callable[Concatenate[SensorPushCloudApi, _P], Coroutine[Any, Any, _R]]:
    """Decorate API calls to handle SensorPush Cloud exceptions."""

    @wraps(func)
    async def _api_call(
        self: SensorPushCloudApi, *args: _P.args, **kwargs: _P.kwargs
    ) -> _R:
        retries: int = 0
        logger.debug("API call to %s with args=%s, kwargs=%s", func, args, kwargs)
        while True:
            try:
                result = await func(self, *args, **kwargs)
            except Exception as e:
                # Force reauthorization if an exception occurs to avoid
                # authorization failures after temporary outages.
                self.deadline = datetime.now(UTC)

                # The SensorPush Cloud API suffers from frequent exceptions;
                # requests are retried before raising an error.
                if retries < REQUEST_RETRIES:
                    retries = retries + 1
                    continue

                logger.debug("API call to %s failed after %d retries", func, retries)
                # API exceptions provide a JSON-encoded message in the
                # response body; otherwise, fall back to general behavior.
                if isinstance(e, ApiException):
                    data = json.loads(e.body)
                    raise SensorPushCloudError(data["message"]) from e
                else:
                    raise SensorPushCloudError(e) from e
            else:
                logger.debug("API call to %s succeeded after %d retries", func, retries)
                return result

    return _api_call


class SensorPushCloudApi:
    """SensorPush Cloud API class."""

    def __init__(self, email: str, password: str, clientsession: ClientSession = None) -> None:
        """Initialize the SensorPush Cloud API object."""
        self.email = email
        self.password = password
        self.configuration = Configuration(pool_manager=clientsession)
        self.api = ApiApi(ApiClient(self.configuration))
        self.deadline = datetime.now(UTC)
        self.lock = Lock()

    async def async_renew_access(self) -> None:
        """Renew an access token if it has expired."""
        async with self.lock:  # serialize authorize calls
            if datetime.now(UTC) >= self.deadline:
                await self.async_authorize()

    @api_call
    async def async_authorize(self) -> None:
        """Sign in and request an authorization code."""
        # SensorPush provides a simplified OAuth endpoint using access tokens
        # without refresh tokens. It is not possible to use 3rd party client
        # IDs without first contacting SensorPush support.
        try:
            auth_response = await self.api.oauth_authorize_post(
                AuthorizeRequest(email=self.email, password=self.password),
                _request_timeout=REQUEST_TIMEOUT.total_seconds(),
            )
            access_response = await self.api.access_token(
                AccessTokenRequest(authorization=auth_response.authorization),
                _request_timeout=REQUEST_TIMEOUT.total_seconds(),
            )
            self.configuration.api_key["oauth"] = access_response.accesstoken
            self.deadline = datetime.now(UTC) + ACCESS_TOKEN_EXPIRATION
        except SensorPushCloudError as e:
            # The SensorPush API does not distinguish between different types
            # of failures using status codes. For now, we assume any failure
            # is due to invalid authentication, however in the future this
            # should be updated to better reflect the true cause of failure
            # without matching human readable error messages.
            raise SensorPushCloudAuthError(e) from e;

    @api_call
    async def async_sensors(self, *args: Any, **kwargs: Any) -> Mapping[str, Sensor]:
        """List all sensors."""
        await self.async_renew_access()
        return await self.api.sensors(
            SensorsRequest(*args, **kwargs),
            _request_timeout=REQUEST_TIMEOUT.total_seconds(),
        )

    @api_call
    async def async_samples(self, *args: Any, **kwargs: Any) -> Samples:
        """Query sensor samples."""
        await self.async_renew_access()
        return await self.api.samples(
            SamplesRequest(*args, **kwargs),
            _request_timeout=REQUEST_TIMEOUT.total_seconds(),
        )
