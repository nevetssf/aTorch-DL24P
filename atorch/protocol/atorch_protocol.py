"""Atorch protocol encoder/decoder for DL24P electronic load."""

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional
import struct


class DeviceType(IntEnum):
    """Atorch device types."""
    AC_METER = 0x01
    DC_LOAD = 0x02
    USB_METER = 0x03


class MessageType(IntEnum):
    """Atorch message types."""
    STATUS = 0x01
    REPLY = 0x02
    COMMAND = 0x11


class Command(IntEnum):
    """DL24P command codes."""
    TURN_ON = 0x01
    TURN_OFF = 0x02
    SET_CURRENT = 0x03
    SET_VOLTAGE_CUTOFF = 0x04
    SET_TIMER = 0x05
    RESET_COUNTERS = 0x06
    SET_BACKLIGHT = 0x07


@dataclass
class DeviceStatus:
    """Parsed device status from DL24P."""
    voltage: float  # Volts
    current: float  # Amps
    power: float  # Watts
    energy_wh: float  # Watt-hours
    capacity_mah: float  # mAh
    temperature_c: int  # Celsius (internal)
    temperature_f: int  # Fahrenheit (internal)
    ext_temperature_c: int  # External probe Celsius
    ext_temperature_f: int  # External probe Fahrenheit
    hours: int
    minutes: int
    seconds: int
    load_on: bool
    ureg: bool  # Unregulated - no load present
    overcurrent: bool
    overvoltage: bool
    overtemperature: bool
    fan_rpm: int  # Approximate fan speed
    # Device settings (read from device)
    mode: Optional[int] = None  # Current mode (0=CC, 1=CP, 2=CV, 3=CR)
    value_set: Optional[float] = None  # Configured value for current mode
    voltage_cutoff: Optional[float] = None  # Configured voltage cutoff (V)
    time_limit_hours: Optional[int] = None  # Configured time limit hours
    time_limit_minutes: Optional[int] = None  # Configured time limit minutes

    @property
    def runtime_seconds(self) -> int:
        """Total runtime in seconds."""
        return self.hours * 3600 + self.minutes * 60 + self.seconds

    def __str__(self) -> str:
        state = "ON" if self.load_on else "OFF"
        return (
            f"DL24P [{state}]: {self.voltage:.2f}V @ {self.current:.3f}A = {self.power:.2f}W | "
            f"{self.capacity_mah:.0f}mAh / {self.energy_wh:.2f}Wh | "
            f"Temp: {self.temperature_c}°C | "
            f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"
        )


class AtorchProtocol:
    """Encoder/decoder for Atorch DL24P protocol."""

    HEADER = bytes([0xFF, 0x55])
    DEVICE_TYPE = DeviceType.DC_LOAD
    STATUS_LENGTH = 36
    COMMAND_LENGTH = 10

    @classmethod
    def calculate_checksum(cls, data: bytes) -> int:
        """Calculate checksum: sum all bytes, XOR with 0x44, mask to 8-bit."""
        total = sum(data)
        return (total ^ 0x44) & 0xFF

    @classmethod
    def build_command(cls, command: Command, value: int = 0) -> bytes:
        """Build a command packet for the DL24P.

        Args:
            command: The command to send
            value: 4-byte big-endian value (for SET_CURRENT, etc.)

        Returns:
            Complete packet bytes ready to send
        """
        # Pack: header + type + device + command + 4-byte value BE
        payload = bytes([
            MessageType.COMMAND,
            cls.DEVICE_TYPE,
            command,
        ]) + struct.pack(">I", value)

        checksum = cls.calculate_checksum(payload)
        return cls.HEADER + payload + bytes([checksum])

    @classmethod
    def cmd_turn_on(cls) -> bytes:
        """Command to turn load on."""
        return cls.build_command(Command.TURN_ON)

    @classmethod
    def cmd_turn_off(cls) -> bytes:
        """Command to turn load off."""
        return cls.build_command(Command.TURN_OFF)

    @classmethod
    def cmd_set_current(cls, current_a: float) -> bytes:
        """Command to set load current in CC mode.

        Args:
            current_a: Current in amps (0.000 to 24.000)
        """
        # Current is sent as milliamps
        value = int(current_a * 1000)
        value = max(0, min(value, 24000))
        return cls.build_command(Command.SET_CURRENT, value)

    @classmethod
    def cmd_set_voltage_cutoff(cls, voltage: float) -> bytes:
        """Command to set voltage cutoff threshold.

        Args:
            voltage: Cutoff voltage in volts (0.00 to 200.00)
        """
        # Voltage is sent as centivol
        value = int(voltage * 100)
        value = max(0, min(value, 20000))
        return cls.build_command(Command.SET_VOLTAGE_CUTOFF, value)

    @classmethod
    def cmd_set_timer(cls, seconds: int) -> bytes:
        """Command to set timer duration.

        Args:
            seconds: Timer duration in seconds
        """
        return cls.build_command(Command.SET_TIMER, seconds)

    @classmethod
    def cmd_reset_counters(cls) -> bytes:
        """Command to reset Wh, mAh, and time counters."""
        return cls.build_command(Command.RESET_COUNTERS)

    @classmethod
    def parse_status(cls, data: bytes) -> Optional[DeviceStatus]:
        """Parse a status packet from the DL24P.

        Args:
            data: Raw bytes from device (should be 36 bytes)

        Returns:
            DeviceStatus if valid, None if invalid packet
        """
        if len(data) < cls.STATUS_LENGTH:
            return None

        # Verify header
        if data[0:2] != cls.HEADER:
            return None

        # Verify message type
        if data[2] != MessageType.STATUS:
            return None

        # Verify device type
        if data[3] != cls.DEVICE_TYPE:
            return None

        # Verify checksum
        expected_checksum = cls.calculate_checksum(data[2:-1])
        if data[-1] != expected_checksum:
            return None

        # Parse fields
        # Voltage: bytes 4-6 (3 bytes, big-endian) / 10
        voltage = ((data[4] << 16) | (data[5] << 8) | data[6]) / 10.0

        # Current: bytes 7-9 (3 bytes) / 1000
        current = ((data[7] << 16) | (data[8] << 8) | data[9]) / 1000.0

        # Power: bytes 10-12 (3 bytes) / 10
        power = ((data[10] << 16) | (data[11] << 8) | data[12]) / 10.0

        # Energy (Wh): bytes 13-16 (4 bytes) / 100
        energy_wh = struct.unpack(">I", data[13:17])[0] / 100.0

        # Capacity (mAh): bytes 17-20 (4 bytes)
        capacity_mah = struct.unpack(">I", data[17:21])[0]

        # Temperature internal: bytes 21-22
        temp_c = data[21]
        temp_f = data[22]

        # Temperature external: bytes 23-24
        ext_temp_c = data[23]
        ext_temp_f = data[24]

        # Time: bytes 25-27 (hours, minutes, seconds)
        hours = data[25]
        minutes = data[26]
        seconds = data[27]

        # Status flags: byte 28
        flags = data[28]
        load_on = bool(flags & 0x01)
        overcurrent = bool(flags & 0x02)
        overvoltage = bool(flags & 0x04)
        overtemperature = bool(flags & 0x08)

        # Fan RPM approximation: bytes 29-30
        fan_rpm = (data[29] << 8) | data[30]

        return DeviceStatus(
            voltage=voltage,
            current=current,
            power=power,
            energy_wh=energy_wh,
            capacity_mah=capacity_mah,
            temperature_c=temp_c,
            temperature_f=temp_f,
            ext_temperature_c=ext_temp_c,
            ext_temperature_f=ext_temp_f,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            load_on=load_on,
            ureg=False,  # TODO: Parse from flags if available in serial protocol
            overcurrent=overcurrent,
            overvoltage=overvoltage,
            overtemperature=overtemperature,
            fan_rpm=fan_rpm,
        )

    @classmethod
    def parse_reply(cls, data: bytes) -> Optional[dict]:
        """Parse a reply packet from the DL24P.

        Args:
            data: Raw bytes from device

        Returns:
            Dict with reply info if valid, None otherwise
        """
        if len(data) < 6:
            return None

        if data[0:2] != cls.HEADER:
            return None

        if data[2] != MessageType.REPLY:
            return None

        return {
            "type": "reply",
            "device": data[3],
            "status": data[4] if len(data) > 4 else 0,
            "raw": data,
        }

    @classmethod
    def identify_packet(cls, data: bytes) -> Optional[dict]:
        """Identify what type of packet this is.

        Args:
            data: Raw bytes

        Returns:
            Dict with packet info
        """
        if len(data) < 4:
            return None

        if data[0:2] != cls.HEADER:
            return None

        msg_type = data[2]
        device = data[3]

        return {
            "msg_type": msg_type,
            "msg_type_name": {0x01: "STATUS", 0x02: "REPLY", 0x11: "COMMAND"}.get(msg_type, f"UNKNOWN(0x{msg_type:02X})"),
            "device": device,
            "length": len(data),
        }

    @classmethod
    def find_packet(cls, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        """Find and extract a complete packet from a buffer.

        Args:
            buffer: Accumulated bytes from device

        Returns:
            Tuple of (packet if found, remaining buffer)
        """
        # Look for header
        idx = buffer.find(cls.HEADER)
        if idx == -1:
            # No header found, keep last byte in case it's start of header
            return None, buffer[-1:] if buffer else b""

        # Discard bytes before header
        buffer = buffer[idx:]

        # Check message type to determine packet length
        if len(buffer) >= 3:
            msg_type = buffer[2]

            if msg_type == MessageType.STATUS:
                # Status packets are 36 bytes
                if len(buffer) >= cls.STATUS_LENGTH:
                    packet = buffer[:cls.STATUS_LENGTH]
                    remaining = buffer[cls.STATUS_LENGTH:]
                    return packet, remaining
            elif msg_type == MessageType.REPLY:
                # Reply packets are typically shorter (around 6-10 bytes)
                # Try to find the next header or use a fixed length
                if len(buffer) >= 6:
                    # Look for next header to determine packet boundary
                    next_header = buffer[2:].find(cls.HEADER)
                    if next_header != -1:
                        packet = buffer[:next_header + 2]
                        remaining = buffer[next_header + 2:]
                        return packet, remaining
                    elif len(buffer) >= 10:
                        # Assume 10-byte reply packet
                        packet = buffer[:10]
                        remaining = buffer[10:]
                        return packet, remaining

        # Check if we have enough for a status packet (fallback)
        if len(buffer) >= cls.STATUS_LENGTH:
            packet = buffer[:cls.STATUS_LENGTH]
            remaining = buffer[cls.STATUS_LENGTH:]
            return packet, remaining

        # Not enough data yet
        return None, buffer
