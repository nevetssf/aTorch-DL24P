"""Tests for the Atorch protocol implementation."""

import pytest
from atorch.protocol.atorch_protocol import AtorchProtocol, Command, DeviceStatus


class TestAtorchProtocol:
    """Tests for AtorchProtocol encoder/decoder."""

    def test_checksum_calculation(self):
        """Test checksum XOR calculation."""
        # Known test case: empty data should return 0x44
        data = bytes([])
        assert AtorchProtocol.calculate_checksum(data) == 0x44

        # Single byte
        data = bytes([0x44])
        assert AtorchProtocol.calculate_checksum(data) == 0x00

    def test_build_turn_on_command(self):
        """Test building turn on command."""
        cmd = AtorchProtocol.cmd_turn_on()

        # Check header
        assert cmd[0:2] == bytes([0xFF, 0x55])

        # Check message type (command)
        assert cmd[2] == 0x11

        # Check device type (DC load)
        assert cmd[3] == 0x02

        # Check command (turn on)
        assert cmd[4] == 0x01

        # Check length
        assert len(cmd) == 10

    def test_build_turn_off_command(self):
        """Test building turn off command."""
        cmd = AtorchProtocol.cmd_turn_off()

        assert cmd[0:2] == bytes([0xFF, 0x55])
        assert cmd[2] == 0x11
        assert cmd[3] == 0x02
        assert cmd[4] == 0x02  # Turn off command

    def test_set_current_command(self):
        """Test building set current command."""
        # Set 0.5A = 500mA
        cmd = AtorchProtocol.cmd_set_current(0.5)

        assert cmd[0:2] == bytes([0xFF, 0x55])
        assert cmd[2] == 0x11
        assert cmd[3] == 0x02
        assert cmd[4] == 0x03  # Set current command

        # Value should be 500 (0x000001F4) big-endian
        value = (cmd[5] << 24) | (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert value == 500

    def test_set_current_clamping(self):
        """Test that current is clamped to valid range."""
        # Negative should clamp to 0
        cmd = AtorchProtocol.cmd_set_current(-1.0)
        value = (cmd[5] << 24) | (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert value == 0

        # Above max should clamp to 24000
        cmd = AtorchProtocol.cmd_set_current(30.0)
        value = (cmd[5] << 24) | (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert value == 24000

    def test_set_voltage_cutoff_command(self):
        """Test building voltage cutoff command."""
        # Set 3.0V = 300 centivolt
        cmd = AtorchProtocol.cmd_set_voltage_cutoff(3.0)

        assert cmd[4] == 0x04  # Voltage cutoff command

        value = (cmd[5] << 24) | (cmd[6] << 16) | (cmd[7] << 8) | cmd[8]
        assert value == 300

    def test_parse_status_invalid_header(self):
        """Test that invalid header returns None."""
        data = bytes([0x00, 0x00] + [0] * 34)
        assert AtorchProtocol.parse_status(data) is None

    def test_parse_status_too_short(self):
        """Test that short data returns None."""
        data = bytes([0xFF, 0x55] + [0] * 10)
        assert AtorchProtocol.parse_status(data) is None

    def test_parse_status_valid(self):
        """Test parsing a valid status packet."""
        # Build a mock status packet
        data = bytearray(36)
        data[0:2] = [0xFF, 0x55]  # Header
        data[2] = 0x01  # Status message type
        data[3] = 0x02  # DC load device type

        # Voltage: 12.5V = 125 (bytes 4-6)
        data[4:7] = [0x00, 0x00, 0x7D]

        # Current: 0.5A = 500mA (bytes 7-9)
        data[7:10] = [0x00, 0x01, 0xF4]

        # Power: 6.25W = 62.5 (bytes 10-12)
        data[10:13] = [0x00, 0x02, 0x71]

        # Energy: 1.25Wh = 125 (bytes 13-16)
        data[13:17] = [0x00, 0x00, 0x00, 0x7D]

        # Capacity: 100mAh (bytes 17-20)
        data[17:21] = [0x00, 0x00, 0x00, 0x64]

        # Temperatures (bytes 21-24)
        data[21] = 35  # Internal C
        data[22] = 95  # Internal F
        data[23] = 25  # External C
        data[24] = 77  # External F

        # Time: 1h 23m 45s (bytes 25-27)
        data[25] = 1   # Hours
        data[26] = 23  # Minutes
        data[27] = 45  # Seconds

        # Status flags (byte 28)
        data[28] = 0x01  # Load on

        # Fan RPM (bytes 29-30)
        data[29:31] = [0x0B, 0xB8]  # 3000 RPM

        # Calculate and set checksum
        checksum = AtorchProtocol.calculate_checksum(data[2:-1])
        data[-1] = checksum

        # Parse
        status = AtorchProtocol.parse_status(bytes(data))

        assert status is not None
        assert status.voltage == pytest.approx(12.5, rel=0.01)
        assert status.current == pytest.approx(0.5, rel=0.01)
        assert status.temperature_c == 35
        assert status.hours == 1
        assert status.minutes == 23
        assert status.seconds == 45
        assert status.load_on is True
        assert status.fan_rpm == 3000

    def test_find_packet_no_header(self):
        """Test finding packet with no header."""
        buffer = bytes([0x00, 0x01, 0x02, 0x03])
        packet, remaining = AtorchProtocol.find_packet(buffer)

        assert packet is None
        assert remaining == bytes([0x03])

    def test_find_packet_incomplete(self):
        """Test finding packet with incomplete data."""
        buffer = bytes([0xFF, 0x55, 0x01, 0x02])
        packet, remaining = AtorchProtocol.find_packet(buffer)

        assert packet is None
        assert remaining == buffer

    def test_find_packet_complete(self):
        """Test finding complete packet."""
        # Create a 36-byte packet
        packet_data = bytes([0xFF, 0x55] + [0x01, 0x02] + [0] * 32)
        extra_data = bytes([0xAA, 0xBB])
        buffer = packet_data + extra_data

        packet, remaining = AtorchProtocol.find_packet(buffer)

        assert packet == packet_data
        assert remaining == extra_data


class TestDeviceStatus:
    """Tests for DeviceStatus dataclass."""

    def test_runtime_seconds(self):
        """Test runtime_seconds property."""
        status = DeviceStatus(
            voltage=12.0,
            current=0.5,
            power=6.0,
            energy_wh=1.0,
            capacity_mah=100,
            temperature_c=30,
            temperature_f=86,
            ext_temperature_c=25,
            ext_temperature_f=77,
            hours=2,
            minutes=30,
            seconds=45,
            load_on=True,
            overcurrent=False,
            overvoltage=False,
            overtemperature=False,
            fan_rpm=2000,
        )

        # 2h 30m 45s = 2*3600 + 30*60 + 45 = 9045
        assert status.runtime_seconds == 9045

    def test_str_representation(self):
        """Test string representation."""
        status = DeviceStatus(
            voltage=12.5,
            current=0.5,
            power=6.25,
            energy_wh=1.0,
            capacity_mah=100,
            temperature_c=30,
            temperature_f=86,
            ext_temperature_c=25,
            ext_temperature_f=77,
            hours=0,
            minutes=10,
            seconds=30,
            load_on=True,
            overcurrent=False,
            overvoltage=False,
            overtemperature=False,
            fan_rpm=2000,
        )

        s = str(status)
        assert "ON" in s
        assert "12.50V" in s
        assert "0.500A" in s
        assert "00:10:30" in s
