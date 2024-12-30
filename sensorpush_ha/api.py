"""Library for interfacing with the SensorPush Cloud API."""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from datetime import datetime, timedelta
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

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

ACCESS_TOKEN_EXPIRATION: Final = timedelta(minutes=60)
REQUEST_RETRIES: Final = 3
REQUEST_TIMEOUT: Final = timedelta(seconds=15)

logger = logging.getLogger(__package__)


class SensorPushCloudError(Exception):
    """An exception occurred when calling the SensorPush Cloud API."""


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
                self.deadline = dt_util.now()

                # The SensorPush Cloud API suffers from frequent exceptions;
                # requests are retried before raising an error.
                if retries < REQUEST_RETRIES:
                    retries = retries + 1
                    continue

                logger.debug("API call to %s failed after %d retries", func, retries)
                if isinstance(e, ApiException):
                    # API exceptions provide a JSON-encoded message in the
                    # body; otherwise, fall back to the general behavior.
                    try:
                        data = json.loads(e.body)
                        raise SensorPushCloudError(data["message"]) from e
                    except Exception:  # noqa: BLE001
                        pass
                raise SensorPushCloudError(e) from e
            else:
                logger.debug("API call to %s succeeded after %d retries", func, retries)
                return result

    return _api_call


class SensorPushCloudApi:
    """SensorPush Cloud API class."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        """Initialize the SensorPush Cloud API object."""
        self.email = email
        self.password = password
        self.configuration = Configuration(pool_manager=async_get_clientsession(hass))
        self.api = ApiApi(ApiClient(self.configuration))
        self.deadline = dt_util.now()
        self.lock = Lock()

    async def async_renew_access(self) -> None:
        """Renew an access token if it has expired."""
        async with self.lock:  # serialize authorize calls
            if dt_util.now() >= self.deadline:
                await self.async_authorize()

    @api_call
    async def async_authorize(self) -> None:
        """Sign in and request an authorization code."""
        # SensorPush provides a simplified OAuth endpoint using access tokens
        # without refresh tokens. It is not possible to use 3rd party client
        # IDs without first contacting SensorPush support.
        auth_response = await self.api.oauth_authorize_post(
            AuthorizeRequest(email=self.email, password=self.password),
            _request_timeout=REQUEST_TIMEOUT.total_seconds(),
        )
        access_response = await self.api.access_token(
            AccessTokenRequest(authorization=auth_response.authorization),
            _request_timeout=REQUEST_TIMEOUT.total_seconds(),
        )
        self.configuration.api_key["oauth"] = access_response.accesstoken
        self.deadline = dt_util.now() + ACCESS_TOKEN_EXPIRATION

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
