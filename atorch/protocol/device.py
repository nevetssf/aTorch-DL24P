"""Device communication for aTorch DL24P (Serial and USB HID)."""

import struct
import threading
import time
from enum import Enum, auto
from typing import Callable, Optional
import serial
import serial.tools.list_ports

try:
    import hid
    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False

from .atorch_protocol import AtorchProtocol, DeviceStatus
from .px100_protocol import PX100Protocol


class DeviceError(Exception):
    """Exception for device communication errors."""
    pass


class PortType(Enum):
    """Type of serial port."""
    USB = auto()
    BLUETOOTH = auto()
    UNKNOWN = auto()


class Device:
    """Serial communication handler for DL24P electronic load."""

    BAUD_RATE = 9600
    CH340_VID = 0x1A86
    CH340_PID = 0x7523
    READ_TIMEOUT = 1.0  # Longer timeout for Bluetooth stability
    STATUS_INTERVAL = 1.0  # Device reports every ~1 second
    BT_INIT_DELAY = 2.0  # Bluetooth ports need time to initialize

    # Common USB-serial chip identifiers
    USB_CHIPS = ["ch340", "ch341", "cp210", "ftdi", "pl2303", "usb-serial", "usb serial", "usbserial"]
    # Bluetooth port identifiers
    BT_IDENTIFIERS = ["bluetooth", "bt-", "bthenum", "rfcomm", "cu.bt", "tty.bt"]

    def __init__(self):
        self._serial: Optional[serial.Serial] = None
        self._port: Optional[str] = None
        self._running = False
        self._read_thread: Optional[threading.Thread] = None
        self._buffer = b""
        self._last_status: Optional[DeviceStatus] = None
        self._status_callback: Optional[Callable[[DeviceStatus], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None
        self._debug_callback: Optional[Callable[[str, str, bytes], None]] = None
        self._lock = threading.Lock()
        self._is_bluetooth = False  # Flag for Bluetooth connection (uses polling)

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._serial is not None and self._serial.is_open

    @property
    def port(self) -> Optional[str]:
        """Get current port name."""
        return self._port

    @property
    def last_status(self) -> Optional[DeviceStatus]:
        """Get the most recent device status."""
        return self._last_status

    def set_status_callback(self, callback: Callable[[DeviceStatus], None]) -> None:
        """Set callback for status updates."""
        self._status_callback = callback

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for error notifications."""
        self._error_callback = callback

    def set_debug_callback(self, callback: Callable[[str, str, bytes], None]) -> None:
        """Set callback for debug logging.

        Args:
            callback: Function(event_type, message, data) where:
                - event_type: 'SEND', 'RECV', 'INFO', 'ERROR', 'PARSE'
                - message: Human-readable message
                - data: Raw bytes (may be empty)
        """
        self._debug_callback = callback

    def _debug(self, event_type: str, message: str, data: bytes = b"") -> None:
        """Send debug event."""
        if self._debug_callback:
            try:
                self._debug_callback(event_type, message, data)
            except Exception:
                pass

    @classmethod
    def classify_port(cls, port) -> PortType:
        """Classify a port as USB, Bluetooth, or unknown.

        Args:
            port: A serial port info object from list_ports

        Returns:
            PortType enum value
        """
        device_lower = port.device.lower()
        desc_lower = (port.description or "").lower()

        # Check for USB identifiers first
        # Has VID/PID = definitely USB device
        if port.vid is not None:
            return PortType.USB

        # macOS: /dev/cu.usbserial* or /dev/cu.usbmodem* or /dev/cu.wchusbserial*
        if "usbserial" in device_lower or "usbmodem" in device_lower or "wchusbserial" in device_lower:
            return PortType.USB

        # Linux: /dev/ttyUSB* or /dev/ttyACM*
        if "/dev/ttyusb" in device_lower or "/dev/ttyacm" in device_lower:
            return PortType.USB

        # Check description for USB chips
        for chip in cls.USB_CHIPS:
            if chip in desc_lower:
                return PortType.USB

        # Windows: COM ports with USB in description
        if device_lower.startswith("com") and "usb" in desc_lower:
            return PortType.USB

        # Check for Bluetooth identifiers
        for bt_id in cls.BT_IDENTIFIERS:
            if bt_id in device_lower or bt_id in desc_lower:
                return PortType.BLUETOOTH

        # macOS: /dev/cu.* ports without VID/PID are typically Bluetooth
        # (except debug-console which is a system port)
        if device_lower.startswith("/dev/cu.") and port.vid is None:
            if "debug-console" in device_lower:
                return PortType.UNKNOWN
            # It's a Bluetooth device
            return PortType.BLUETOOTH

        return PortType.UNKNOWN

    @classmethod
    def _is_bluetooth_port(cls, port_name: str) -> bool:
        """Check if a port name indicates a Bluetooth connection.

        Args:
            port_name: The port device name (e.g., /dev/cu.DL24-BT)

        Returns:
            True if this appears to be a Bluetooth port
        """
        port_lower = port_name.lower()

        # Check for Bluetooth identifiers in port name
        for bt_id in cls.BT_IDENTIFIERS:
            if bt_id in port_lower:
                return True

        # macOS: /dev/cu.* ports that aren't USB are typically Bluetooth
        if port_lower.startswith("/dev/cu."):
            # USB ports have patterns like usbserial, usbmodem, wchusbserial
            usb_patterns = ["usbserial", "usbmodem", "wchusbserial", "usb"]
            if not any(p in port_lower for p in usb_patterns):
                return True

        # Linux: /dev/rfcomm* are Bluetooth
        if "/dev/rfcomm" in port_lower:
            return True

        return False

    @classmethod
    def list_ports(cls, port_type: Optional[PortType] = None) -> list[tuple[str, str, PortType]]:
        """List available serial ports.

        Args:
            port_type: Filter by port type. None returns all ports.

        Returns:
            List of (port_name, description, port_type) tuples
        """
        ports = []
        for port in serial.tools.list_ports.comports():
            ptype = cls.classify_port(port)
            if port_type is None or ptype == port_type:
                ports.append((port.device, port.description, ptype))
        return ports

    @classmethod
    def list_usb_ports(cls) -> list[tuple[str, str]]:
        """List USB serial ports.

        Returns:
            List of (port_name, description) tuples
        """
        return [(p, d) for p, d, t in cls.list_ports(PortType.USB)]

    @classmethod
    def list_bluetooth_ports(cls) -> list[tuple[str, str]]:
        """List Bluetooth serial ports.

        Returns:
            List of (port_name, description) tuples
        """
        return [(p, d) for p, d, t in cls.list_ports(PortType.BLUETOOTH)]

    @classmethod
    def find_dl24p_ports(cls) -> list[str]:
        """Find likely DL24P ports (CH340 USB-serial adapters).

        Returns:
            List of port names that might be DL24P devices
        """
        candidates = []
        for port in serial.tools.list_ports.comports():
            # Check for CH340 chip
            if port.vid == cls.CH340_VID and port.pid == cls.CH340_PID:
                candidates.append(port.device)
            # Also check description for common USB-serial chips
            elif port.description and any(
                chip in port.description.lower()
                for chip in cls.USB_CHIPS
            ):
                candidates.append(port.device)
        return candidates

    def connect(self, port: Optional[str] = None) -> bool:
        """Connect to the DL24P device.

        Args:
            port: Serial port name. If None, auto-detect.

        Returns:
            True if connected successfully

        Raises:
            DeviceError: If connection fails
        """
        if self.is_connected:
            self.disconnect()

        # Auto-detect if no port specified
        if port is None:
            candidates = self.find_dl24p_ports()
            if not candidates:
                raise DeviceError("No DL24P device found. Check USB connection.")
            port = candidates[0]

        try:
            self._debug("INFO", f"Opening port {port} at {self.BAUD_RATE} baud...")
            self._serial = serial.Serial(
                port=port,
                baudrate=self.BAUD_RATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.READ_TIMEOUT,
            )
            self._port = port
            self._buffer = b""
            self._debug("INFO", f"Port opened successfully: {port}")

            # Check if this is a Bluetooth port and add initialization delay
            self._is_bluetooth = self._is_bluetooth_port(port)
            if self._is_bluetooth:
                self._debug("INFO", f"Bluetooth port detected, waiting {self.BT_INIT_DELAY}s for initialization...")
                time.sleep(self.BT_INIT_DELAY)
                # Clear any garbage data that may have accumulated
                self._serial.reset_input_buffer()
                self._debug("INFO", "Bluetooth initialization complete, using active polling mode")

            # Start read/poll thread
            self._running = True
            if self._is_bluetooth:
                # Bluetooth uses active polling with PX100 protocol
                self._read_thread = threading.Thread(target=self._poll_loop_bt, daemon=True)
            else:
                # USB serial listens for Atorch broadcasts
                self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
            self._debug("INFO", "Communication thread started...")

            return True

        except serial.SerialException as e:
            self._debug("ERROR", f"Failed to open port {port}: {e}")
            raise DeviceError(f"Failed to open port {port}: {e}")

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self._running = False

        if self._read_thread:
            self._read_thread.join(timeout=1.0)
            self._read_thread = None

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        self._port = None
        self._buffer = b""
        self._last_status = None

    def _read_loop(self) -> None:
        """Background thread for reading device data."""
        self._debug("INFO", "Read loop started")
        read_count = 0
        while self._running and self._serial:
            try:
                data = self._serial.read(64)
                if data:
                    read_count += 1
                    self._debug("RECV", f"Received {len(data)} bytes (total reads: {read_count})", data)
                    self._buffer += data
                    self._debug("INFO", f"Buffer size: {len(self._buffer)} bytes")
                    self._process_buffer()
            except serial.SerialException as e:
                if self._running:
                    self._debug("ERROR", f"Read error: {e}")
                    self._handle_error(f"Read error: {e}")
                    self._running = False
                break
            except Exception as e:
                if self._running:
                    self._debug("ERROR", f"Unexpected error: {e}")
                    self._handle_error(f"Unexpected error: {e}")
        self._debug("INFO", "Read loop ended")

    def _poll_loop_bt(self) -> None:
        """Background thread for polling device via Bluetooth using PX100 protocol."""
        self._debug("INFO", "Bluetooth poll loop started (PX100 protocol)")
        poll_count = 0

        while self._running and self._serial:
            try:
                poll_count += 1
                self._debug("INFO", f"Bluetooth poll #{poll_count}")

                # Query multiple values using PX100 protocol
                voltage = self._px100_query(PX100Protocol.CMD_GET_VOLTAGE)
                current = self._px100_query(PX100Protocol.CMD_GET_CURRENT)
                on_off = self._px100_query(PX100Protocol.CMD_GET_ON_OFF)

                if voltage is not None or current is not None:
                    # Build a DeviceStatus from the polled values
                    v = (voltage or 0) / 1000.0 if voltage else 0.0  # mV to V
                    i = (current or 0) / 1000.0 if current else 0.0  # mA to A
                    p = v * i
                    load_on = (on_off == 1) if on_off is not None else False

                    status = DeviceStatus(
                        voltage=v,
                        current=i,
                        power=p,
                        energy_wh=0.0,  # PX100 would need separate queries
                        capacity_mah=0.0,
                        temperature_c=0,
                        temperature_f=32,
                        ext_temperature_c=0,
                        ext_temperature_f=32,
                        hours=0,
                        minutes=0,
                        seconds=0,
                        load_on=load_on,
                        ureg=False,
                        overcurrent=False,
                        overvoltage=False,
                        overtemperature=False,
                        fan_rpm=0,
                    )

                    self._debug("PARSE", f"BT Status: {v:.2f}V {i:.3f}A {p:.2f}W Load={'ON' if load_on else 'OFF'}")
                    self._last_status = status

                    if self._status_callback:
                        try:
                            self._status_callback(status)
                        except Exception:
                            pass
                else:
                    self._debug("WARN", "No response from PX100 queries")

                time.sleep(self.STATUS_INTERVAL)

            except serial.SerialException as e:
                if self._running:
                    self._debug("ERROR", f"Bluetooth poll error: {e}")
                    self._handle_error(f"Bluetooth poll error: {e}")
                    self._running = False
                break
            except Exception as e:
                if self._running:
                    self._debug("ERROR", f"Unexpected error in BT poll: {e}")
                time.sleep(1.0)

        self._debug("INFO", "Bluetooth poll loop ended")

    def _px100_query(self, cmd: int) -> Optional[int]:
        """Send a PX100 query command and return the response value.

        Args:
            cmd: PX100 command byte (e.g., CMD_GET_VOLTAGE)

        Returns:
            Response value as integer, or None if no response
        """
        if not self.is_connected:
            return None

        with self._lock:
            try:
                # Build and send query
                query = PX100Protocol.build_command(cmd, 0, 0)
                self._debug("SEND", f"PX100 query cmd=0x{cmd:02X}", query)
                self._serial.write(query)
                self._serial.flush()

                # Wait for response (8 bytes: CA CB CMD D1 D2 D3 CE CF)
                time.sleep(0.1)
                response = self._serial.read(8)

                if response:
                    self._debug("RECV", f"PX100 response ({len(response)} bytes)", response)
                    parsed = PX100Protocol.parse_response(response)
                    if parsed:
                        self._debug("PARSE", f"PX100: cmd=0x{parsed['cmd']:02X} value={parsed['raw_value']}")
                        return parsed['raw_value']
                    else:
                        self._debug("WARN", "Failed to parse PX100 response")
                else:
                    self._debug("WARN", f"No response to PX100 cmd=0x{cmd:02X}")

                return None

            except Exception as e:
                self._debug("ERROR", f"PX100 query error: {e}")
                return None

    def _process_buffer(self) -> None:
        """Process accumulated buffer data."""
        while True:
            packet, self._buffer = AtorchProtocol.find_packet(self._buffer)
            if packet is None:
                break

            self._debug("PARSE", f"Found packet: {len(packet)} bytes", packet)

            # Identify packet type
            pkt_info = AtorchProtocol.identify_packet(packet)
            if pkt_info:
                self._debug("PARSE", f"Packet type: {pkt_info['msg_type_name']} device=0x{pkt_info['device']:02X}")

            # Try to parse as status
            status = AtorchProtocol.parse_status(packet)
            if status:
                self._debug("PARSE", f"Status: {status.voltage:.2f}V {status.current:.3f}A {status.power:.2f}W Load={'ON' if status.load_on else 'OFF'}")
                self._last_status = status
                if self._status_callback:
                    try:
                        self._status_callback(status)
                    except Exception:
                        pass
            else:
                # Try to parse as reply
                reply = AtorchProtocol.parse_reply(packet)
                if reply:
                    self._debug("PARSE", f"Reply: status=0x{reply['status']:02X}")
                else:
                    self._debug("ERROR", f"Unknown packet format", packet)

    def _handle_error(self, message: str) -> None:
        """Handle an error condition."""
        if self._error_callback:
            try:
                self._error_callback(message)
            except Exception:
                pass

    def send_command(self, command: bytes) -> bool:
        """Send a command to the device.

        Args:
            command: Raw command bytes

        Returns:
            True if sent successfully
        """
        if not self.is_connected:
            self._debug("ERROR", "Cannot send: not connected")
            return False

        with self._lock:
            try:
                self._debug("SEND", f"Sending {len(command)} bytes", command)
                self._serial.write(command)
                self._serial.flush()
                self._debug("INFO", "Command sent successfully")
                return True
            except serial.SerialException as e:
                self._debug("ERROR", f"Write error: {e}")
                self._handle_error(f"Write error: {e}")
                return False

    def turn_on(self) -> bool:
        """Turn the load on."""
        return self.send_command(AtorchProtocol.cmd_turn_on())

    def turn_off(self) -> bool:
        """Turn the load off."""
        return self.send_command(AtorchProtocol.cmd_turn_off())

    def set_current(self, current_a: float) -> bool:
        """Set the load current in CC mode.

        Args:
            current_a: Current in amps
        """
        return self.send_command(AtorchProtocol.cmd_set_current(current_a))

    def set_voltage_cutoff(self, voltage: float) -> bool:
        """Set voltage cutoff threshold.

        Args:
            voltage: Cutoff voltage in volts
        """
        return self.send_command(AtorchProtocol.cmd_set_voltage_cutoff(voltage))

    def set_timer(self, seconds: int) -> bool:
        """Set timer duration.

        Args:
            seconds: Timer in seconds
        """
        return self.send_command(AtorchProtocol.cmd_set_timer(seconds))

    def reset_counters(self) -> bool:
        """Reset Wh, mAh, and time counters."""
        return self.send_command(AtorchProtocol.cmd_reset_counters())


class USBHIDDevice:
    """USB HID communication handler for DL24P electronic load.

    The DL24P uses a custom USB HID protocol (not the serial Atorch protocol).
    Protocol format:
    - Commands: 55 05 [type] [sub] [data...] ee ff (padded to 64 bytes)
    - Responses: aa 05 [type] [sub] [data...] ee ff (64 bytes)
    """

    # DL24P USB HID identifiers
    VENDOR_ID = 0x0483   # STMicroelectronics
    PRODUCT_ID = 0x5750  # DL24P custom HID device
    REPORT_SIZE = 64

    # Protocol constants
    CMD_HEADER = 0x55
    RESP_HEADER = 0xAA
    PROTO_VERSION = 0x05
    TRAILER = bytes([0xEE, 0xFF])

    # Command types
    CMD_TYPE_QUERY = 0x01
    CMD_TYPE_SET = 0x01

    # Sub-commands
    SUB_CMD_LIVE_DATA = 0x03  # Get live measurements
    SUB_CMD_COUNTERS = 0x05   # Get accumulated counters
    SUB_CMD_SET_CURRENT = 0x21  # Set load current
    SUB_CMD_SET_CUTOFF = 0x22   # Set voltage cutoff
    SUB_CMD_POWER = 0x25      # Turn on/off
    SUB_CMD_SET_DISCHARGE_TIME = 0x31  # Set discharge timeout (hours)
    SUB_CMD_RESTORE_DEFAULTS = 0x33    # Restore device to factory defaults
    SUB_CMD_CLEAR_DATA = 0x34  # Clear accumulated data (mAh, Wh, time)

    # Polling interval (device doesn't push data, we must poll)
    POLL_INTERVAL = 1.0  # seconds (1 Hz to match serial device rate)

    def __init__(self):
        self._device = None
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_status: Optional[DeviceStatus] = None
        self._status_callback: Optional[Callable[[DeviceStatus], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None
        self._debug_callback: Optional[Callable[[str, str, bytes], None]] = None
        self._lock = threading.Lock()
        self._device_path: Optional[str] = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if USB HID support is available."""
        return HID_AVAILABLE

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._device is not None

    @property
    def port(self) -> Optional[str]:
        """Get current device path/identifier."""
        return self._device_path

    @property
    def last_status(self) -> Optional[DeviceStatus]:
        """Get the most recent device status."""
        return self._last_status

    def set_status_callback(self, callback: Callable[[DeviceStatus], None]) -> None:
        """Set callback for status updates."""
        self._status_callback = callback

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for error notifications."""
        self._error_callback = callback

    def set_debug_callback(self, callback: Callable[[str, str, bytes], None]) -> None:
        """Set callback for debug logging."""
        self._debug_callback = callback

    def _debug(self, event_type: str, message: str, data: bytes = b"") -> None:
        """Send debug event."""
        if self._debug_callback:
            try:
                self._debug_callback(event_type, message, data)
            except Exception:
                pass

    @classmethod
    def list_devices(cls) -> list[dict]:
        """List available DL24P USB HID devices."""
        if not HID_AVAILABLE:
            return []

        devices = []
        try:
            for dev in hid.enumerate(cls.VENDOR_ID, cls.PRODUCT_ID):
                devices.append({
                    'path': dev['path'].decode() if isinstance(dev['path'], bytes) else dev['path'],
                    'vendor_id': dev['vendor_id'],
                    'product_id': dev['product_id'],
                    'serial': dev.get('serial_number', ''),
                    'manufacturer': dev.get('manufacturer_string', 'Unknown'),
                    'product': dev.get('product_string', 'DL24P'),
                    'description': f"USB HID: {dev.get('product_string', 'DL24P')}"
                })
        except Exception:
            pass
        return devices

    @classmethod
    def find_dl24p(cls) -> Optional[str]:
        """Find a DL24P USB HID device."""
        devices = cls.list_devices()
        if devices:
            return devices[0]['path']
        return None

    def connect(self, path: Optional[str] = None) -> bool:
        """Connect to DL24P via USB HID."""
        if not HID_AVAILABLE:
            raise DeviceError("USB HID support not available. Install hidapi: pip install hidapi")

        if self.is_connected:
            self.disconnect()

        if path is None:
            path = self.find_dl24p()
            if path is None:
                raise DeviceError("No DL24P USB device found. Check USB connection.")

        try:
            self._debug("INFO", f"Opening USB HID device: {path}")
            self._device = hid.device()
            self._device.open_path(path.encode() if isinstance(path, str) else path)
            self._device.set_nonblocking(False)  # Blocking mode for reliable reads
            self._device_path = path

            manufacturer = self._device.get_manufacturer_string() or "Unknown"
            product = self._device.get_product_string() or "Unknown"
            self._debug("INFO", f"Connected to {manufacturer} {product}")

            # Start polling thread
            self._running = True
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
            self._debug("INFO", "Polling thread started")

            return True

        except Exception as e:
            self._debug("ERROR", f"Failed to open device: {e}")
            self._device = None
            raise DeviceError(f"Failed to open USB HID device: {e}")

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self._running = False

        if self._poll_thread:
            self._poll_thread.join(timeout=2.0)
            self._poll_thread = None

        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

        self._device_path = None
        self._last_status = None

    def _build_command(self, cmd_type: int, sub_cmd: int, data: bytes = b'') -> bytes:
        """Build a USB HID command packet."""
        packet = bytearray(64)
        packet[0] = self.CMD_HEADER
        packet[1] = self.PROTO_VERSION
        packet[2] = cmd_type
        packet[3] = sub_cmd

        # Put data starting at offset 4
        data_end = 4
        for i, b in enumerate(data):
            if 4 + i < 60:  # Leave room for checksum and trailer
                packet[4 + i] = b
                data_end = 4 + i + 1

        # Calculate checksum: sum of bytes from offset 2 to end of data, XOR with 0x44
        checksum_data = packet[2:data_end]
        checksum = (sum(checksum_data) ^ 0x44) & 0xFF
        packet[data_end] = checksum

        # Add trailer right after checksum
        packet[data_end + 1] = 0xEE
        packet[data_end + 2] = 0xFF

        return bytes(packet)

    def _send_command(self, cmd_type: int, sub_cmd: int, data: bytes = b'') -> bool:
        """Send a command (no response expected)."""
        if not self.is_connected:
            return False

        with self._lock:
            try:
                cmd = self._build_command(cmd_type, sub_cmd, data)
                self._debug("SEND", f"Cmd {cmd_type:02x}/{sub_cmd:02x} bytes={cmd[:10].hex()}", cmd[:16])
                self._device.write(b'\x00' + cmd)
                return True
            except Exception as e:
                self._debug("ERROR", f"Send error: {e}")
                return False

    def _send_and_receive(self, cmd_type: int, sub_cmd: int, data: bytes = b'') -> Optional[bytes]:
        """Send command and wait for response."""
        if not self.is_connected:
            return None

        with self._lock:
            try:
                cmd = self._build_command(cmd_type, sub_cmd, data)
                self._debug("SEND", f"Cmd {cmd_type:02x}/{sub_cmd:02x}", cmd[:16])

                # Send with report ID 0
                self._device.write(b'\x00' + cmd)

                # Read response (short timeout)
                time.sleep(0.05)  # Small delay before reading
                response = self._device.read(64, timeout_ms=500)
                if response:
                    response = bytes(response)
                    self._debug("RECV", f"Raw response ({len(response)} bytes): {response[:16].hex()}")
                    if response[0] == self.RESP_HEADER and response[1] == self.PROTO_VERSION:
                        self._debug("RECV", f"Resp {response[2]:02x}/{response[3]:02x}", response[:16])
                        return response
                    else:
                        self._debug("WARN", f"Unexpected header: {response[:8].hex()}")
                else:
                    self._debug("WARN", "No response received")
                return None

            except Exception as e:
                self._debug("ERROR", f"Communication error: {e}")
                return None

    def _parse_live_data(self, payload: bytes, counters: Optional[dict] = None) -> DeviceStatus:
        """Parse live data response (sub-cmd 0x03) into DeviceStatus."""
        # Payload structure (from USB capture analysis):
        # Offset 0-3: value_set (big-endian float) - meaning depends on current mode
        # Offset 4-7: unknown (possibly another setting)
        # Offset 8-11: unknown (calibration factor ~0.995)
        # Offset 12-15: unknown (calibration factor ~0.979)
        # Offset 16-19: voltage cutoff (big-endian float, V)
        # Offset 20-23: temperature (big-endian float, C)
        # Offset 24-27: unknown
        # Offset 28-31: unknown
        # Offset 32: time limit value (hours or minutes depending on mode)
        # Offset 33: time limit mode? (0x01=hours, 0x02=minutes, 0x00=disabled)
        # Offset 34-43: other settings
        # Offset 44: current mode (0=CC, 1=CP, 2=CV, 3=CR)
        # Offset 45-46: unknown
        # Offset 47-48: voltage (big-endian uint16, divide by 100 for V)

        def get_float(offset: int) -> float:
            return struct.unpack('>f', payload[offset:offset+4])[0]

        def get_uint16_be(offset: int) -> int:
            return struct.unpack('>H', payload[offset:offset+2])[0]

        value_set = get_float(0)  # Value for current mode (current/power/voltage/resistance)
        mode = payload[44]  # Current mode: 0=CC, 1=CP, 2=CV, 3=CR
        voltage_cutoff = get_float(16)  # Voltage cutoff at offset 16
        temperature = int(get_float(20))

        # Time limit is at offsets 49 (hours) and 50 (minutes)
        time_limit_hours = payload[49]
        time_limit_minutes = payload[50]


        flags = payload[44:48]

        # Debug: log full payload to find load on/off state
        self._debug("INFO", f"Full payload: {payload.hex()}")

        # Voltage is at offset 47 as big-endian uint16 / 100
        voltage = get_uint16_be(47) / 100.0

        # Get actual values from counters response (more accurate, real-time)
        if counters:
            if 'voltage_mv' in counters:
                voltage = counters['voltage_mv'] / 1000.0
            if 'current_ma' in counters:
                current = counters['current_ma'] / 1000.0  # mA to A
            else:
                current = 0.0
            if 'power_w' in counters:
                power = counters['power_w']
            else:
                power = voltage * current
        else:
            current = 0.0
            power = 0.0

        # Load on/off from counters response (byte 48)
        load_on = counters.get('load_on', False) if counters else False

        # UREG (Unregulated) - load is on but no current flowing (no load/battery present)
        ureg = (load_on and current < 0.01)

        # Extract runtime from counters
        runtime_s = counters.get('runtime', 0) if counters else 0
        hours = runtime_s // 3600
        minutes = (runtime_s % 3600) // 60
        seconds = runtime_s % 60

        # Get energy/capacity from counters
        capacity_mah = counters.get('capacity_mah', 0) if counters else 0
        energy_wh = counters.get('energy_wh', 0) if counters else 0

        # Get temperatures from counters (more accurate)
        if counters and 'mosfet_temp_c' in counters:
            temperature = counters['mosfet_temp_c']
        if counters and 'ext_temp_c' in counters:
            ext_temperature = counters['ext_temp_c']
        else:
            ext_temperature = 0.0

        # Get fan RPM from counters
        fan_rpm = counters.get('fan_rpm', 0) if counters else 0

        return DeviceStatus(
            voltage=voltage,
            current=current,
            power=power,
            energy_wh=energy_wh,
            capacity_mah=capacity_mah,
            temperature_c=temperature,
            temperature_f=int(temperature * 9 / 5 + 32),
            ext_temperature_c=ext_temperature,
            ext_temperature_f=int(ext_temperature * 9 / 5 + 32),
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            load_on=load_on,
            ureg=ureg,
            overcurrent=False,
            overvoltage=False,
            overtemperature=False,
            fan_rpm=fan_rpm,
            # Device settings
            mode=mode,
            value_set=value_set,
            voltage_cutoff=voltage_cutoff,
            time_limit_hours=time_limit_hours,
            time_limit_minutes=time_limit_minutes,
        )

    def _parse_counters(self, payload: bytes) -> dict:
        """Parse counter data response (sub-cmd 0x05)."""
        # Payload structure (little-endian integers):
        # Offset 0-3: zeros when no load connected
        # Offset 4-5: voltage (uint16, mV)
        # Offset 8-9: current (uint16, mA)
        # Offset 12-13: power (uint16, mW units)
        # Offset 20-23: energy (uint32, mWh - divide by 1000 for Wh)
        # Offset 24-27: capacity (uint32, µAh)
        # Offset 28-31: runtime (uint32, in ~48 ticks/second)
        # Offset 32-35: external temperature (uint32, milli-°C)
        # Offset 36-39: MOSFET temperature (uint32, milli-°C)
        # Offset 40-43: fan speed (uint32, milli-RPM)
        # Offset 48: load on/off flag (0x00=off, 0x01=on)

        def get_uint16_le(offset: int) -> int:
            return struct.unpack('<H', payload[offset:offset+2])[0]

        def get_uint32_le(offset: int) -> int:
            return struct.unpack('<I', payload[offset:offset+4])[0]

        voltage_mv = get_uint16_le(4)
        current_ma = get_uint16_le(8)
        power_mw = get_uint16_le(12)
        energy_mwh = get_uint32_le(20)  # Energy at offset 20 in mWh
        capacity_uah = get_uint32_le(24)

        # Temperatures in milli-°C (divide by 1000 for °C)
        ext_temp_mc = get_uint32_le(32)
        mosfet_temp_mc = get_uint32_le(36)

        # Fan speed in milli-RPM (divide by 1000 for RPM)
        fan_mrpm = get_uint32_le(40)

        # Runtime in ~48 ticks/second
        runtime_ticks = get_uint32_le(28)
        runtime_s = runtime_ticks // 48

        # Load on/off flag at byte 48
        load_on = payload[48] == 0x01 if len(payload) > 48 else False

        # Convert temperatures from milli-°C to °C
        mosfet_temp_c = mosfet_temp_mc / 1000.0
        ext_temp_c = ext_temp_mc / 1000.0
        fan_rpm = fan_mrpm // 1000

        # Calculate energy in Wh from mWh
        energy_wh = energy_mwh / 1000.0

        # Debug: log the parsed values
        self._debug("PARSE", f"Counters: V={voltage_mv}mV I={current_ma}mA E={energy_mwh}mWh C={capacity_uah}µAh MosT={mosfet_temp_c:.1f}°C ExtT={ext_temp_c:.1f}°C Fan={fan_rpm}RPM RT={runtime_s}s LoadOn={load_on}")

        return {
            'voltage_mv': voltage_mv,
            'current_ma': current_ma,
            'power_w': voltage_mv * current_ma / 1000000.0,  # Calculate power from V*I
            'capacity_mah': capacity_uah / 1000.0,  # Convert from µAh to mAh
            'energy_wh': energy_wh,
            'mosfet_temp_c': mosfet_temp_c,
            'ext_temp_c': ext_temp_c,
            'fan_rpm': fan_rpm,
            'runtime': runtime_s,
            'load_on': load_on,
        }

    def _poll_loop(self) -> None:
        """Background thread to poll device for status."""
        self._debug("INFO", "Poll loop started")

        while self._running and self._device:
            try:
                # Request counters first (no data parameter - it breaks the checksum!)
                counters = None
                counter_resp = self._send_and_receive(self.CMD_TYPE_QUERY, self.SUB_CMD_COUNTERS)
                if counter_resp:
                    counters = self._parse_counters(counter_resp[4:62])

                # Request live data (no data parameter)
                response = self._send_and_receive(self.CMD_TYPE_QUERY, self.SUB_CMD_LIVE_DATA)
                if response:
                    payload = response[4:62]
                    status = self._parse_live_data(payload, counters)

                    self._last_status = status
                    self._debug("PARSE", f"Status: {status.voltage:.2f}V {status.current:.3f}A T={status.temperature_c}C Load={'ON' if status.load_on else 'OFF'}{' UREG' if status.ureg else ''}")

                    if self._status_callback:
                        try:
                            self._status_callback(status)
                        except Exception:
                            pass

                time.sleep(self.POLL_INTERVAL)

            except Exception as e:
                if self._running:
                    self._debug("ERROR", f"Poll error: {e}")
                    self._handle_error(f"Poll error: {e}")
                time.sleep(1.0)

        self._debug("INFO", "Poll loop ended")

    def _handle_error(self, message: str) -> None:
        """Handle an error condition."""
        if self._error_callback:
            try:
                self._error_callback(message)
            except Exception:
                pass

    def send_command(self, command: bytes) -> bool:
        """Send raw command bytes (for compatibility with serial protocol)."""
        # This method exists for API compatibility but the USB HID protocol
        # uses a different format, so we just return False for raw commands
        self._debug("WARN", "Raw command not supported for USB HID, use specific methods")
        return False

    def turn_on(self) -> bool:
        """Turn the load on."""
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_POWER, b'\x01\x00\x00\x00')

    def turn_off(self) -> bool:
        """Turn the load off."""
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_POWER, b'\x00\x00\x00\x00')

    def set_current(self, current_a: float) -> bool:
        """Set the load current in CC mode."""
        data = struct.pack('>f', current_a)
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_CURRENT, data)

    def set_power(self, power_w: float) -> bool:
        """Set the load power in CP mode.

        Args:
            power_w: Power in watts
        """
        # Use same sub-command as current (0x21) - device uses current mode to interpret value
        data = struct.pack('>f', power_w)
        self._debug("INFO", f"Setting power to {power_w}W")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_CURRENT, data)

    def set_voltage(self, voltage_v: float) -> bool:
        """Set the load voltage in CV mode.

        Args:
            voltage_v: Voltage in volts
        """
        # Use same sub-command as current (0x21) - device uses current mode to interpret value
        data = struct.pack('>f', voltage_v)
        self._debug("INFO", f"Setting voltage to {voltage_v}V")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_CURRENT, data)

    def set_resistance(self, resistance_ohm: float) -> bool:
        """Set the load resistance in CR mode.

        Args:
            resistance_ohm: Resistance in ohms
        """
        # Use same sub-command as current (0x21) - device uses current mode to interpret value
        data = struct.pack('>f', resistance_ohm)
        self._debug("INFO", f"Setting resistance to {resistance_ohm}Ω")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_CURRENT, data)

    def set_mode(self, mode: int, value: float = None) -> bool:
        """Set the load mode and optionally set the value for that mode.

        Args:
            mode: Mode (0=CC, 1=CP, 2=CV, 3=CR)
            value: Value to set for the mode (current/power/voltage/resistance)

        From USB capture analysis:
        - 0x47 = CC (Constant Current)
        - 0x48 = CV (Constant Voltage)
        - 0x49 = CR (Constant Resistance)
        - 0x4A = CP (Constant Power)
        """
        # Map UI mode IDs to device sub-commands
        mode_subcmds = {
            0: 0x47,  # CC
            1: 0x4A,  # CP
            2: 0x48,  # CV
            3: 0x49,  # CR
        }
        mode_names = {0: "CC", 1: "CP", 2: "CV", 3: "CR"}
        mode_name = mode_names.get(mode, f"Unknown({mode})")
        subcmd = mode_subcmds.get(mode)

        if subcmd is None:
            self._debug("ERROR", f"Invalid mode: {mode}")
            return False

        self._debug("INFO", f"Setting mode to {mode_name} (sub-cmd=0x{subcmd:02X})")

        # Send mode select command
        data = bytes([0x00, 0x00, 0x00, 0x00])
        result = self._send_command(self.CMD_TYPE_SET, subcmd, data)

        # If value provided, set it for this mode
        if result and value is not None:
            self._debug("INFO", f"Setting {mode_name} value to {value}")
            value_data = struct.pack('>f', value)
            result = self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_CURRENT, value_data)

        return result

    def set_voltage_cutoff(self, voltage: float) -> bool:
        """Set voltage cutoff threshold.

        Args:
            voltage: Cutoff voltage in volts (e.g., 3.0 for 3V cutoff)
        """
        # Sub-command 0x29 sets voltage cutoff
        # Data format: big-endian IEEE 754 float
        data = struct.pack('>f', voltage)
        self._debug("INFO", f"Setting voltage cutoff to {voltage}V")
        return self._send_command(self.CMD_TYPE_SET, 0x29, data)

    def set_brightness(self, level: int) -> bool:
        """Set screen brightness level.

        Args:
            level: Brightness level (1-9, from USB capture)
        """
        # 0x22 controls screen brightness
        # Format: 00 00 00 [level] - level is a single byte integer (1=min, 9=max)
        level = max(1, min(9, level))  # Clamp to valid range
        data = bytes([0x00, 0x00, 0x00, level])
        self._debug("INFO", f"Setting brightness to {level}")
        return self._send_command(self.CMD_TYPE_SET, 0x22, data)

    def set_standby_brightness(self, level: int) -> bool:
        """Set standby screen brightness level.

        Args:
            level: Brightness level (1-9)
        """
        # 0x23 controls standby screen brightness
        level = max(1, min(9, level))  # Clamp to valid range
        data = bytes([0x00, 0x00, 0x00, level])
        self._debug("INFO", f"Setting standby brightness to {level}")
        return self._send_command(self.CMD_TYPE_SET, 0x23, data)

    def set_standby_timeout(self, seconds: int) -> bool:
        """Set standby timeout in seconds.

        Args:
            seconds: Standby timeout in seconds (10-60)
        """
        # 0x24 controls standby timeout
        seconds = max(10, min(60, seconds))  # Clamp to valid range
        data = bytes([0x00, 0x00, 0x00, seconds])
        self._debug("INFO", f"Setting standby timeout to {seconds}s")
        return self._send_command(self.CMD_TYPE_SET, 0x24, data)

    def set_discharge_time(self, hours: int = 0, minutes: int = 0) -> bool:
        """Set discharge timeout in hours and minutes.

        The device has two modes:
        - Minutes mode (enable=0x02): Sets time in minutes (1-59)
        - Hours mode (enable=0x01): Sets time in whole hours (1+)

        Note: Combined hours+minutes is not supported. When hours > 0,
        only whole hours are used and minutes are discarded.

        Args:
            hours: Discharge timeout hours (0-99)
            minutes: Discharge timeout minutes (0-59)
        """
        # Sub-command 0x31 sets discharge timeout
        # Format from pcapng analysis:
        # - Minutes mode: [minutes, 0x00, 0x00, 0x02]
        # - Hours mode: [hours, 0x00, 0x00, 0x01]
        hours = max(0, min(99, hours))
        minutes = max(0, min(59, minutes))

        if hours == 0 and minutes == 0:
            # Disable timeout - need to clear both hours and minutes
            # First send hours mode with 0 to clear hours
            data_hours = bytes([0x00, 0x00, 0x00, 0x01])
            self._debug("INFO", "Clearing hours (0h in hours mode) - sending data: " + data_hours.hex())
            self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_DISCHARGE_TIME, data_hours)
            import time
            time.sleep(0.1)  # Small delay between commands
            # Then send minutes mode with 0 to clear minutes
            data = bytes([0x00, 0x00, 0x00, 0x02])
            msg = "Clearing minutes (0m in minutes mode)"
        elif hours == 0:
            # Minutes mode: time < 60 min
            data = bytes([minutes, 0x00, 0x00, 0x02])
            msg = f"Setting discharge time to {minutes}m (minutes mode)"
        else:
            # Hours mode: time >= 60 min (minutes are dropped)
            data = bytes([hours, 0x00, 0x00, 0x01])
            if minutes > 0:
                msg = f"Setting discharge time to {hours}h (hours mode, {minutes}m ignored)"
            else:
                msg = f"Setting discharge time to {hours}h (hours mode)"

        self._debug("INFO", f"{msg} - sending data: {data.hex()}")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_DISCHARGE_TIME, data)

    def reset_counters(self) -> bool:
        """Clear accumulated data (mAh, Wh, time counters)."""
        self._debug("INFO", "Sending clear data command")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_CLEAR_DATA, b'\x00\x00\x00\x00')

    def restore_defaults(self) -> bool:
        """Restore device to factory default settings."""
        self._debug("INFO", "Sending restore defaults command")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_RESTORE_DEFAULTS, b'\x00\x00\x00\x00')
