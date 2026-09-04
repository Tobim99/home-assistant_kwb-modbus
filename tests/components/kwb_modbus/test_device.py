"""Tests for KWB Modbus device registration."""

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.kwb_modbus import async_setup_entry
from custom_components.kwb_modbus.const import (
    CONF_DISCOVERED_SENSORS,
    CONF_HEATING_DEVICE,
    DOMAIN,
)
from custom_components.kwb_modbus.coordinator import KWBDataUpdateCoordinator
from custom_components.kwb_modbus.number import KWBNumberEntity
from custom_components.kwb_modbus.register_maps.types import (
    RegisterDef,
    SelectRegisterDef,
)
from custom_components.kwb_modbus.select import KWBSelectEntity
from custom_components.kwb_modbus.sensor import KWBSensor
import pytest

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from tests.common import MockConfigEntry

type KWBEntity = KWBSensor | KWBNumberEntity | KWBSelectEntity
type EntityFactory = Callable[[KWBDataUpdateCoordinator, MockConfigEntry], KWBEntity]


def _sensor_factory(
    coordinator: KWBDataUpdateCoordinator, entry: MockConfigEntry
) -> KWBSensor:
    """Create an indexed sensor."""
    return KWBSensor(
        coordinator,
        RegisterDef(
            address=100,
            count=1,
            name="Temperature",
            param="BUF.temperature",
            data_type="s16",
            unit="°C",
            scale=0.1,
            index="BUF 0",
            value_table="",
            is_status=False,
        ),
        entry,
        True,
    )


def _number_factory(
    coordinator: KWBDataUpdateCoordinator, entry: MockConfigEntry
) -> KWBNumberEntity:
    """Create an indexed number entity."""
    return KWBNumberEntity(
        coordinator,
        RegisterDef(
            address=25000,
            count=1,
            name="Setpoint",
            param="BUF.setpoint",
            data_type="u16",
            unit="°C",
            scale=1,
            index="BUF 0",
            value_table="",
            is_status=False,
        ),
        entry,
    )


def _select_factory(
    coordinator: KWBDataUpdateCoordinator, entry: MockConfigEntry
) -> KWBSelectEntity:
    """Create an indexed select entity."""
    return KWBSelectEntity(
        coordinator,
        SelectRegisterDef(
            address=25001,
            name="Program",
            param="BUF.program",
            index="BUF 0",
            value_table="programs",
            data_type="u16",
            module="buffer_tank",
        ),
        entry,
        False,
    )


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(_sensor_factory, id="sensor"),
        pytest.param(_number_factory, id="number"),
        pytest.param(_select_factory, id="select"),
    ],
)
def test_indexed_entity_uses_parent_device_id(factory: EntityFactory) -> None:
    """Test indexed entities link to the registered parent device ID."""
    coordinator = cast(KWBDataUpdateCoordinator, MagicMock())
    coordinator.parent_device_id = "parent-device-id"
    coordinator.data = {}
    coordinator.get_value_table.return_value = {0: "Off", 1: "Auto"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HEATING_DEVICE: "easyfire"},
    )

    device_info = factory(coordinator, entry).device_info

    assert device_info["via_device_id"] == "parent-device-id"
    assert "via_device" not in device_info


async def test_setup_registers_parent_device(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """Test setup registers the parent before forwarding entity platforms."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: 502,
            CONF_HEATING_DEVICE: "easyfire",
            CONF_DISCOVERED_SENSORS: {"kwb_1": True},
        },
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.connect = AsyncMock()
    client.connected = True
    result = MagicMock()
    result.isError.return_value = False
    client.read_input_registers = AsyncMock(return_value=result)

    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.data = {8192: 1, 8193: 2, 8194: 3}

    with (
        patch(
            "custom_components.kwb_modbus.AsyncModbusTcpClient",
            return_value=client,
        ),
        patch(
            "custom_components.kwb_modbus.KWBDataUpdateCoordinator",
            return_value=coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ) as forward_setups,
    ):
        assert await async_setup_entry(hass, entry)

    parent_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert parent_device is not None
    assert parent_device.sw_version == "1.2.3"
    assert coordinator.parent_device_id == parent_device.id
    forward_setups.assert_awaited_once()
