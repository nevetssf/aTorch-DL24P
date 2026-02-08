"""PX100 protocol support for DL24P load control.

The PX100 protocol uses a 6-byte packet structure:
B1 B2 CMD D1 D2 B6

Where:
- B1 B2: Header bytes (0xB1 0xB2)
- CMD: Command byte
- D1 D2: Data bytes (big-endian value)
- B6: Trailer byte (0xB6)

Responses come in format:
CA CB CMD D1 D2 D3 CE CF
"""

from dataclasses import dataclass
from typing import Optional
import struct


class PX100Protocol:
    """Encoder/decoder for PX100 protocol used by DL24P."""

    # Command packet structure
    CMD_HEADER = bytes([0xB1, 0xB2])
    CMD_TRAILER = bytes([0xB6])

    # Response packet structure
    RSP_HEADER = bytes([0xCA, 0xCB])
    RSP_TRAILER = bytes([0xCE, 0xCF])

    # Commands
    CMD_ON_OFF = 0x01        # Data: 0x01=on, 0x00=off
    CMD_SET_CURRENT = 0x02   # Data: current in format int.decimal
    CMD_SET_CUTOFF = 0x03    # Data: voltage in format int.decimal
    CMD_RESET = 0x05         # Reset counters

    # Query commands (responses come in CA CB format)
    CMD_GET_ON_OFF = 0x10
    CMD_GET_VOLTAGE = 0x11   # Response: voltage in mV
    CMD_GET_CURRENT = 0x12   # Response: current in mA
    CMD_GET_AH = 0x14        # Response: amp-hours
    CMD_GET_WH = 0x15        # Response: watt-hours
    CMD_GET_TEMP = 0x16      # Response: temperature
    CMD_GET_SET_CURRENT = 0x17  # Response: set current value
    CMD_GET_CUTOFF = 0x18    # Response: cutoff voltage

    @classmethod
    def build_command(cls, cmd: int, d1: int = 0, d2: int = 0) -> bytes:
        """Build a PX100 command packet.

        Args:
            cmd: Command byte
            d1: First data byte
            d2: Second data byte

        Returns:
            6-byte command packet
        """
        return cls.CMD_HEADER + bytes([cmd, d1, d2]) + cls.CMD_TRAILER

    @classmethod
    def cmd_turn_on(cls) -> bytes:
        """Command to turn load ON."""
        return cls.build_command(cls.CMD_ON_OFF, 0x01, 0x00)

    @classmethod
    def cmd_turn_off(cls) -> bytes:
        """Command to turn load OFF."""
        return cls.build_command(cls.CMD_ON_OFF, 0x00, 0x00)

    @classmethod
    def cmd_set_current(cls, current_a: float) -> bytes:
        """Set load current.

        Args:
            current_a: Current in amps (e.g., 1.5 for 1.5A)

        Returns:
            Command packet
        """
        # Format: integer part in d1, decimal part in d2
        # e.g., 1.50A = d1=1, d2=50
        int_part = int(current_a)
        dec_part = int((current_a - int_part) * 100)
        return cls.build_command(cls.CMD_SET_CURRENT, int_part, dec_part)

    @classmethod
    def cmd_set_cutoff(cls, voltage: float) -> bytes:
        """Set voltage cutoff.

        Args:
            voltage: Cutoff voltage in volts

        Returns:
            Command packet
        """
        int_part = int(voltage)
        dec_part = int((voltage - int_part) * 100)
        return cls.build_command(cls.CMD_SET_CUTOFF, int_part, dec_part)

    @classmethod
    def cmd_reset(cls) -> bytes:
        """Reset counters."""
        return cls.build_command(cls.CMD_RESET, 0x00, 0x00)

    @classmethod
    def cmd_get_on_off(cls) -> bytes:
        """Query ON/OFF state."""
        return cls.build_command(cls.CMD_GET_ON_OFF, 0x00, 0x00)

    @classmethod
    def cmd_get_voltage(cls) -> bytes:
        """Query current voltage."""
        return cls.build_command(cls.CMD_GET_VOLTAGE, 0x00, 0x00)

    @classmethod
    def cmd_get_current(cls) -> bytes:
        """Query current draw."""
        return cls.build_command(cls.CMD_GET_CURRENT, 0x00, 0x00)

    @classmethod
    def parse_response(cls, data: bytes) -> Optional[dict]:
        """Parse a PX100 response packet.

        Args:
            data: Raw bytes (should be 8 bytes: CA CB CMD D1 D2 D3 CE CF)

        Returns:
            Dict with parsed response or None if invalid
        """
        if len(data) < 8:
            return None

        if data[0:2] != cls.RSP_HEADER:
            return None

        if data[-2:] != cls.RSP_TRAILER:
            return None

        cmd = data[2]
        d1 = data[3]
        d2 = data[4]
        d3 = data[5]

        # Parse based on command
        value = (d1 << 16) | (d2 << 8) | d3

        return {
            "cmd": cmd,
            "raw_value": value,
            "d1": d1,
            "d2": d2,
            "d3": d3,
        }

    @classmethod
    def find_response(cls, buffer: bytes) -> tuple[Optional[bytes], bytes]:
        """Find and extract a response packet from buffer."""
        # Look for response header CA CB
        idx = buffer.find(cls.RSP_HEADER)
        if idx == -1:
            return None, buffer[-1:] if buffer else b""

        buffer = buffer[idx:]

        # Response is 8 bytes: CA CB CMD D1 D2 D3 CE CF
        if len(buffer) >= 8:
            packet = buffer[:8]
            remaining = buffer[8:]
            return packet, remaining

        return None, buffer
