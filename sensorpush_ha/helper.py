"""Library for interfacing with the SensorPush Cloud API."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime
import logging
from typing import Any

from pydantic import BaseModel

from homeassistant.helpers.device_registry import DeviceInfo

from .api import SensorPushCloudApi, SensorPushCloudError

logger = logging.getLogger(__package__)


class SensorPushCloudData(BaseModel):
    """SensorPush Cloud data class."""

    device_id: str
    manufacturer: str
    model: str
    name: str
    altitude: float | None
    atmospheric_pressure: float | None
    battery_voltage: float | None
    dewpoint: float | None
    humidity: float | None
    last_update: datetime
    signal_strength: float | None
    temperature: float | None
    vapor_pressure: float | None

    def __getitem__(self, item) -> Any:
        """Return a data item."""
        return getattr(self, item)

    def device_info(self, domain: str) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(domain, self.device_id)},
            manufacturer=self.manufacturer,
            model=self.model,
            name=self.name,
        )


class SensorPushCloudHelper:
    """SensorPush Cloud API helper class."""

    def __init__(self, api: SensorPushCloudApi) -> None:
        """Initialize the SensorPush Cloud API helper object."""
        self.api = api

    async def async_get_data(self) -> dict[str, SensorPushCloudData]:
        """Fetch data from API endpoints in parallel."""
        data: dict[str, SensorPushCloudData] = {}
        try:
            # Sensor data is spread across two endpoints, which are requested
            # in parallel and denormalized before handing off to entities.
            sensors, samples = await asyncio.gather(
                self.api.async_sensors(),
                self.api.async_samples(limit=1),
            )
        except SensorPushCloudError:
            logger.exception("Unexpected exception")
        else:
            for device_id, sensor in sensors.items():
                sample = samples.sensors[device_id][0]
                data[device_id] = SensorPushCloudData(
                    device_id=sensor.device_id,
                    manufacturer="SensorPush",
                    model=sensor.type,
                    name=sensor.name,
                    altitude=sample.altitude,
                    atmospheric_pressure=sample.barometric_pressure,
                    battery_voltage=sensor.battery_voltage,
                    dewpoint=sample.dewpoint,
                    humidity=sample.humidity,
                    last_update=sample.observed,
                    signal_strength=sensor.rssi,
                    temperature=sample.temperature,
                    vapor_pressure=sample.vpd,
                )
        return data
