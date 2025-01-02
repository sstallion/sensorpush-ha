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

import asyncio
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .api import SensorPushCloudApi, SensorPushCloudError


class SensorPushCloudData(BaseModel):
    """SensorPush Cloud data class."""

    device_id: str
    manufacturer: str
    model: str
    name: str
    last_update: datetime

    # Data Items
    altitude: float | None
    atmospheric_pressure: float | None
    battery_voltage: float | None
    dewpoint: float | None
    humidity: float | None
    signal_strength: float | None
    temperature: float | None
    vapor_pressure: float | None

    def __getitem__(self, item) -> str | int | float | None:
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
        # Sensor data is spread across two endpoints, which are requested
        # in parallel and denormalized before handing off to entities.
        sensors, samples = await asyncio.gather(
            self.api.async_sensors(),
            self.api.async_samples(limit=1),
        )
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
