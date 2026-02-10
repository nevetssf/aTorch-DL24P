"""Tests for PX100 protocol implementation."""

import pytest
from atorch.protocol.px100_protocol import PX100Protocol


class TestPX100Protocol:
    """Tests for PX100 protocol encoder/decoder."""

    def test_command_header(self):
        """Test command header bytes."""
        assert PX100Protocol.CMD_HEADER == bytes([0xB1, 0xB2])

    def test_command_trailer(self):
        """Test command trailer byte."""
        assert PX100Protocol.CMD_TRAILER == bytes([0xB6])

    def test_response_header(self):
        """Test response header bytes."""
        assert PX100Protocol.RSP_HEADER == bytes([0xCA, 0xCB])

    def test_response_trailer(self):
        """Test response trailer bytes."""
        assert PX100Protocol.RSP_TRAILER == bytes([0xCE, 0xCF])


class TestBuildCommand:
    """Tests for command building."""

    def test_build_command_structure(self):
        """Test that built command has correct structure."""
        cmd = PX100Protocol.build_command(0x01, 0x02, 0x03)

        assert len(cmd) == 6
        assert cmd[0:2] == bytes([0xB1, 0xB2])  # Header
        assert cmd[2] == 0x01  # Command
        assert cmd[3] == 0x02  # D1
        assert cmd[4] == 0x03  # D2
        assert cmd[5] == 0xB6  # Trailer

    def test_build_command_default_data(self):
        """Test command with default data bytes."""
        cmd = PX100Protocol.build_command(0x10)

        assert cmd[3] == 0x00  # D1 default
        assert cmd[4] == 0x00  # D2 default

    def test_cmd_turn_on(self):
        """Test turn on command."""
        cmd = PX100Protocol.cmd_turn_on()

        assert len(cmd) == 6
        assert cmd[2] == 0x01  # ON_OFF command
        assert cmd[3] == 0x01  # ON
        assert cmd[4] == 0x00

    def test_cmd_turn_off(self):
        """Test turn off command."""
        cmd = PX100Protocol.cmd_turn_off()

        assert len(cmd) == 6
        assert cmd[2] == 0x01  # ON_OFF command
        assert cmd[3] == 0x00  # OFF
        assert cmd[4] == 0x00

    def test_cmd_set_current_integer(self):
        """Test setting integer current value."""
        cmd = PX100Protocol.cmd_set_current(2.0)

        assert cmd[2] == 0x02  # SET_CURRENT command
        assert cmd[3] == 2     # Integer part
        assert cmd[4] == 0     # Decimal part

    def test_cmd_set_current_decimal(self):
        """Test setting current with decimal."""
        cmd = PX100Protocol.cmd_set_current(1.5)

        assert cmd[2] == 0x02
        assert cmd[3] == 1   # Integer part
        assert cmd[4] == 50  # Decimal part (0.50 * 100)

    def test_cmd_set_current_small(self):
        """Test setting small current value."""
        cmd = PX100Protocol.cmd_set_current(0.25)

        assert cmd[3] == 0   # Integer part
        assert cmd[4] == 25  # Decimal part

    def test_cmd_set_cutoff_integer(self):
        """Test setting integer cutoff voltage."""
        cmd = PX100Protocol.cmd_set_cutoff(3.0)

        assert cmd[2] == 0x03  # SET_CUTOFF command
        assert cmd[3] == 3     # Integer part
        assert cmd[4] == 0     # Decimal part

    def test_cmd_set_cutoff_decimal(self):
        """Test setting cutoff with decimal."""
        cmd = PX100Protocol.cmd_set_cutoff(2.75)

        assert cmd[2] == 0x03
        assert cmd[3] == 2   # Integer part
        assert cmd[4] == 75  # Decimal part

    def test_cmd_reset(self):
        """Test reset counters command."""
        cmd = PX100Protocol.cmd_reset()

        assert cmd[2] == 0x05  # RESET command
        assert cmd[3] == 0x00
        assert cmd[4] == 0x00

    def test_cmd_get_on_off(self):
        """Test get on/off state query."""
        cmd = PX100Protocol.cmd_get_on_off()

        assert cmd[2] == 0x10  # GET_ON_OFF command

    def test_cmd_get_voltage(self):
        """Test get voltage query."""
        cmd = PX100Protocol.cmd_get_voltage()

        assert cmd[2] == 0x11  # GET_VOLTAGE command

    def test_cmd_get_current(self):
        """Test get current query."""
        cmd = PX100Protocol.cmd_get_current()

        assert cmd[2] == 0x12  # GET_CURRENT command


class TestParseResponse:
    """Tests for response parsing."""

    def test_parse_valid_response(self):
        """Test parsing a valid response packet."""
        # CA CB CMD D1 D2 D3 CE CF
        data = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])

        result = PX100Protocol.parse_response(data)

        assert result is not None
        assert result["cmd"] == 0x11
        assert result["d1"] == 0x01
        assert result["d2"] == 0x02
        assert result["d3"] == 0x03

    def test_parse_response_raw_value(self):
        """Test that raw_value combines d1, d2, d3 correctly."""
        # Value: 0x010203 = 66051
        data = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])

        result = PX100Protocol.parse_response(data)

        expected = (0x01 << 16) | (0x02 << 8) | 0x03
        assert result["raw_value"] == expected
        assert result["raw_value"] == 66051

    def test_parse_response_too_short(self):
        """Test that short data returns None."""
        data = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02])

        result = PX100Protocol.parse_response(data)

        assert result is None

    def test_parse_response_invalid_header(self):
        """Test that invalid header returns None."""
        data = bytes([0xAA, 0xBB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])

        result = PX100Protocol.parse_response(data)

        assert result is None

    def test_parse_response_invalid_trailer(self):
        """Test that invalid trailer returns None."""
        data = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xDE, 0xDF])

        result = PX100Protocol.parse_response(data)

        assert result is None

    def test_parse_response_zero_values(self):
        """Test parsing response with zero values."""
        data = bytes([0xCA, 0xCB, 0x10, 0x00, 0x00, 0x00, 0xCE, 0xCF])

        result = PX100Protocol.parse_response(data)

        assert result is not None
        assert result["raw_value"] == 0


class TestFindResponse:
    """Tests for finding response packets in buffer."""

    def test_find_response_at_start(self):
        """Test finding response at buffer start."""
        buffer = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])

        packet, remaining = PX100Protocol.find_response(buffer)

        assert packet == buffer
        assert remaining == b""

    def test_find_response_with_garbage_prefix(self):
        """Test finding response after garbage bytes."""
        garbage = bytes([0x00, 0x11, 0x22])
        response = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])
        buffer = garbage + response

        packet, remaining = PX100Protocol.find_response(buffer)

        assert packet == response
        assert remaining == b""

    def test_find_response_with_extra_data(self):
        """Test finding response with extra data after."""
        response = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])
        extra = bytes([0xAA, 0xBB, 0xCC])
        buffer = response + extra

        packet, remaining = PX100Protocol.find_response(buffer)

        assert packet == response
        assert remaining == extra

    def test_find_response_incomplete(self):
        """Test handling incomplete response."""
        buffer = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02])  # Only 5 bytes

        packet, remaining = PX100Protocol.find_response(buffer)

        assert packet is None
        assert remaining == buffer  # Keep for later

    def test_find_response_no_header(self):
        """Test handling buffer without header."""
        buffer = bytes([0x00, 0x11, 0x22, 0x33])

        packet, remaining = PX100Protocol.find_response(buffer)

        assert packet is None
        assert remaining == bytes([0x33])  # Only last byte kept

    def test_find_response_empty_buffer(self):
        """Test handling empty buffer."""
        packet, remaining = PX100Protocol.find_response(b"")

        assert packet is None
        assert remaining == b""

    def test_find_multiple_responses(self):
        """Test finding multiple responses sequentially."""
        response1 = bytes([0xCA, 0xCB, 0x11, 0x01, 0x02, 0x03, 0xCE, 0xCF])
        response2 = bytes([0xCA, 0xCB, 0x12, 0x04, 0x05, 0x06, 0xCE, 0xCF])
        buffer = response1 + response2

        # Find first
        packet1, remaining = PX100Protocol.find_response(buffer)
        assert packet1 == response1

        # Find second
        packet2, remaining = PX100Protocol.find_response(remaining)
        assert packet2 == response2
        assert remaining == b""
