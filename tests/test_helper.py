"""Tests for merging sensor metadata and cloud samples."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from sensorpush_api import Sample, Samples, Sensor

from sensorpush_ha import SensorPushCloudApi, SensorPushCloudError, SensorPushCloudHelper


class SensorPushCloudHelperTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = AsyncMock(spec=SensorPushCloudApi)
        self.helper = SensorPushCloudHelper(self.api)
        self.observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.sample = Sample(observed=self.observed, temperature=68.0, humidity=50.0)
        self.sensor = Sensor(deviceId="healthy", type="HT1", name="Living room")

    async def test_missing_samples_do_not_block_other_sensors(self):
        for missing_samples in ({}, {"missing": []}):
            with self.subTest(samples=missing_samples):
                self.api.async_sensors.return_value = {
                    "missing": Sensor(deviceId="missing", type="HT1", name="Offline"),
                    "healthy": self.sensor,
                }
                self.api.async_samples.return_value = Samples(
                    sensors={**missing_samples, "healthy": [self.sample]}
                )
                data = await self.helper.async_get_data()
                self.assertEqual(set(data), {"healthy"})
                self.assertEqual(data["healthy"].temperature, 68.0)
                self.assertEqual(data["healthy"].humidity, 50.0)
                self.assertEqual(data["healthy"].last_update, self.observed)
                self.assertEqual(data["healthy"].name, "Living room")

    async def test_missing_name_uses_stable_device_id(self):
        self.api.async_sensors.return_value = {
            "unnamed": Sensor(deviceId="unnamed", type="HT1"),
            "healthy": self.sensor,
        }
        for temperature in (68.0, 69.0):
            with self.subTest(temperature=temperature):
                self.api.async_samples.return_value = Samples(
                    sensors={
                        "unnamed": [
                            Sample(observed=self.observed, temperature=temperature)
                        ],
                        "healthy": [self.sample],
                    }
                )
                data = await self.helper.async_get_data()
                self.assertEqual(set(data), {"unnamed", "healthy"})
                self.assertEqual(data["unnamed"].name, "unnamed")
                self.assertEqual(data["unnamed"].device_id, "unnamed")
                self.assertEqual(data["unnamed"].temperature, temperature)
                self.assertEqual(data["healthy"].name, "Living room")
                self.assertEqual(data["healthy"].temperature, 68.0)

    async def test_missing_timestamp_does_not_block_other_sensors(self):
        self.api.async_sensors.return_value = {
            "undated": Sensor(deviceId="undated", type="HT1", name="Bedroom"),
            "healthy": self.sensor,
        }
        self.api.async_samples.return_value = Samples(
            sensors={
                "undated": [Sample(temperature=70.0)],
                "healthy": [self.sample],
            }
        )
        data = await self.helper.async_get_data()
        self.assertEqual(set(data), {"healthy"})
        self.assertEqual(data["healthy"].temperature, 68.0)
        self.assertEqual(data["healthy"].last_update, self.observed)

    async def test_missing_samples_mapping_raises_library_error(self):
        for sensors in ({}, {"healthy": self.sensor}):
            with self.subTest(sensors=sensors):
                self.api.async_sensors.return_value = sensors
                self.api.async_samples.return_value = Samples()
                with self.assertRaises(SensorPushCloudError):
                    await self.helper.async_get_data()

    async def test_sensor_appears_when_samples_resume(self):
        self.api.async_sensors.return_value = {"healthy": self.sensor}
        for samples in ({}, {"healthy": []}, {"healthy": [Sample(temperature=68.0)]}):
            with self.subTest(samples=samples):
                self.api.async_samples.return_value = Samples(sensors=samples)
                self.assertEqual(await self.helper.async_get_data(), {})
                self.api.async_samples.return_value = Samples(
                    sensors={"healthy": [self.sample]}
                )
                data = await self.helper.async_get_data()
                self.assertEqual(set(data), {"healthy"})
                self.assertEqual(data["healthy"].temperature, 68.0)
                self.assertEqual(data["healthy"].last_update, self.observed)
        self.api.async_samples.assert_awaited_with(limit=1)

    async def test_api_errors_are_propagated(self):
        self.api.async_sensors.return_value = {}
        self.api.async_samples.side_effect = SensorPushCloudError("Cloud unavailable")
        with self.assertRaisesRegex(SensorPushCloudError, "Cloud unavailable"):
            await self.helper.async_get_data()
