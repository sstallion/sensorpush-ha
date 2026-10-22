"""Regression tests for SensorPush Cloud error handling."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientSession
from sensorpush_api import (
    AccessTokenResponse,
    ApiApi,
    ApiException,
    AuthorizeResponse,
    Samples,
)

from sensorpush_ha import (
    SensorPushCloudApi,
    SensorPushCloudAuthError,
    SensorPushCloudError,
)


def http_error(status, body='{"message": "Cloud error"}'):
    """Make an HTTP error without sending a request."""
    error = ApiException(status=status, reason="Synthetic response")
    error.body = body
    return error


class SensorPushCloudApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = Mock(spec=ApiApi)
        self.client.oauth_authorize_post = AsyncMock(
            return_value=AuthorizeResponse(authorization="synthetic-authorization")
        )
        self.client.access_token = AsyncMock(
            return_value=AccessTokenResponse(accesstoken="synthetic-token")
        )
        self.client.sensors = AsyncMock(return_value={})
        self.client.samples = AsyncMock(return_value=Samples(sensors={}))
        with patch("sensorpush_ha.api.ApiApi", return_value=self.client):
            self.api = SensorPushCloudApi(
                "audit@example.invalid", "synthetic-password", Mock(spec=ClientSession)
            )

    async def test_unexpected_error_bodies_remain_library_errors(self):
        for body in (
            None,
            "",
            "<html>Unavailable</html>",
            "{}",
            "[]",
            "null",
            '{"message": 1}',
        ):
            with self.subTest(body=body):
                error = http_error(400, body)
                self.client.oauth_authorize_post.side_effect = error
                with self.assertRaises(SensorPushCloudAuthError) as raised:
                    await self.api.async_authorize()
                self.assertIn("HTTP 400", str(raised.exception))
                self.assertIs(raised.exception.__cause__, error)

    async def test_json_error_message_is_preserved(self):
        error = http_error(400, '{"message": "Invalid credentials"}')
        self.client.oauth_authorize_post.side_effect = error
        with self.assertRaisesRegex(
            SensorPushCloudAuthError, "Invalid credentials"
        ) as raised:
            await self.api.async_authorize()
        self.assertIs(raised.exception.__cause__, error)
        self.client.oauth_authorize_post.assert_awaited_once()

    async def test_auth_errors_are_not_retried_or_reclassified_by_data_calls(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.client.oauth_authorize_post.reset_mock()
                error = http_error(status)
                self.client.oauth_authorize_post.side_effect = error
                with self.assertRaises(SensorPushCloudAuthError) as raised:
                    await self.api.async_samples(limit=1)
                self.assertIs(raised.exception.__cause__, error)
                self.client.oauth_authorize_post.assert_awaited_once()
        self.client.samples.assert_not_awaited()

    async def test_failed_authorization_does_not_multiply_transport_retries(self):
        error = TimeoutError("Synthetic timeout")
        self.client.oauth_authorize_post.side_effect = error
        with self.assertRaises(SensorPushCloudError) as raised:
            await self.api.async_samples(limit=1)
        self.assertNotIsInstance(raised.exception, SensorPushCloudAuthError)
        self.assertIs(raised.exception.__cause__, error)
        self.assertEqual(self.client.oauth_authorize_post.await_count, 4)
        self.client.samples.assert_not_awaited()

    async def test_classified_library_errors_are_preserved_without_retries(self):
        for error in (SensorPushCloudError("Unavailable"), SensorPushCloudAuthError()):
            with self.subTest(error=type(error).__name__):
                self.client.sensors.reset_mock()
                self.client.sensors.side_effect = error
                with self.assertRaises(type(error)) as raised:
                    await self.api.async_sensors()
                self.assertIs(raised.exception, error)
                self.client.sensors.assert_awaited_once()

    async def test_data_client_errors_are_not_auth_errors_or_retried(self):
        for status in (404, 422, 429):
            with self.subTest(status=status):
                self.client.sensors.reset_mock()
                error = http_error(status)
                self.client.sensors.side_effect = error
                with self.assertRaises(SensorPushCloudError) as raised:
                    await self.api.async_sensors()
                self.assertNotIsInstance(raised.exception, SensorPushCloudAuthError)
                self.assertIs(raised.exception.__cause__, error)
                self.client.sensors.assert_awaited_once()
        # An error on one endpoint does not invalidate the token or block another.
        await self.api.async_samples(limit=1)
        self.client.oauth_authorize_post.assert_awaited_once()
        self.client.samples.assert_awaited_once()

    async def test_transient_failures_retain_the_token_and_existing_retry_limit(self):
        for error in (
            TimeoutError("Synthetic timeout"),
            http_error(503, "<html>Unavailable</html>"),
        ):
            with self.subTest(error=type(error).__name__):
                self.client.sensors.reset_mock()
                self.client.sensors.side_effect = error
                with self.assertRaises(SensorPushCloudError) as raised:
                    await self.api.async_sensors()
                self.assertNotIsInstance(raised.exception, SensorPushCloudAuthError)
                self.assertIs(raised.exception.__cause__, error)
                self.assertEqual(self.client.sensors.await_count, 4)
                self.client.sensors.side_effect = None
                self.assertEqual(await self.api.async_sensors(), {})
        self.client.oauth_authorize_post.assert_awaited_once()
        self.client.access_token.assert_awaited_once()

    async def test_rejected_data_token_is_renewed_on_the_next_call(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.client.sensors.reset_mock()
                self.client.sensors.side_effect = http_error(status)
                with self.assertRaises(SensorPushCloudAuthError):
                    await self.api.async_sensors()
                self.client.sensors.assert_awaited_once()
                previous_authorizations = self.client.oauth_authorize_post.await_count
                self.client.sensors.side_effect = None
                self.assertEqual(await self.api.async_sensors(), {})
                self.assertEqual(
                    self.client.oauth_authorize_post.await_count,
                    previous_authorizations + 1,
                )

    async def test_parallel_requests_still_share_initial_authorization(self):
        await asyncio.gather(self.api.async_sensors(), self.api.async_samples(limit=1))
        self.client.oauth_authorize_post.assert_awaited_once()
        self.client.access_token.assert_awaited_once()

    async def test_cancellation_still_propagates_without_retries(self):
        self.client.sensors.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.api.async_sensors()
        self.client.sensors.assert_awaited_once()
