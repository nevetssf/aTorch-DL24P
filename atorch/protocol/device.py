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
    READ_TIMEOUT = 0.1
    STATUS_INTERVAL = 1.0  # Device reports every ~1 second

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

            # Start read thread
            self._running = True
            self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._read_thread.start()
            self._debug("INFO", "Read thread started, waiting for data...")

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
    SUB_CMD_RESET = 0x47      # Reset counters (suspected)

    # Polling interval (device doesn't push data, we must poll)
    POLL_INTERVAL = 0.5  # seconds

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
        for i, b in enumerate(data):
            if i + 4 < 62:
                packet[4 + i] = b
        packet[62] = 0xEE
        packet[63] = 0xFF
        return bytes(packet)

    def _send_command(self, cmd_type: int, sub_cmd: int, data: bytes = b'') -> bool:
        """Send a command (no response expected)."""
        if not self.is_connected:
            return False

        with self._lock:
            try:
                cmd = self._build_command(cmd_type, sub_cmd, data)
                self._debug("SEND", f"Cmd {cmd_type:02x}/{sub_cmd:02x}", cmd[:16])
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
                    if response[0] == self.RESP_HEADER and response[1] == self.PROTO_VERSION:
                        self._debug("RECV", f"Resp {response[2]:02x}/{response[3]:02x}", response[:16])
                        return response
                    else:
                        self._debug("WARN", f"Unexpected response: {response[:8].hex()}")
                return None

            except Exception as e:
                self._debug("ERROR", f"Communication error: {e}")
                return None

    def _parse_live_data(self, payload: bytes, counters: Optional[dict] = None) -> DeviceStatus:
        """Parse live data response (sub-cmd 0x03) into DeviceStatus."""
        # Payload structure:
        # Offset 0-3: current_set (big-endian float, A)
        # Offset 4-7: unknown (1.0)
        # Offset 8-11: unknown ratio (~0.99)
        # Offset 12-15: unknown ratio (~0.98)
        # Offset 16-19: unknown (6.0)
        # Offset 20-23: temperature (big-endian float, C)
        # Offset 24-43: various settings
        # Offset 44: flags byte 0 (load on/off)
        # Offset 45-46: unknown
        # Offset 47-48: voltage (big-endian uint16, divide by 100 for V)

        def get_float(offset: int) -> float:
            return struct.unpack('>f', payload[offset:offset+4])[0]

        def get_uint16_be(offset: int) -> int:
            return struct.unpack('>H', payload[offset:offset+2])[0]

        current_set = get_float(0)
        temperature = int(get_float(20))
        flags = payload[44:48]

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

        # Load on/off based on whether significant current is flowing
        load_on = current > 0.01

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
            overcurrent=False,
            overvoltage=False,
            overtemperature=False,
            fan_rpm=fan_rpm,
        )

    def _parse_counters(self, payload: bytes) -> dict:
        """Parse counter data response (sub-cmd 0x05)."""
        # Payload structure (little-endian integers):
        # Offset 0-3: unknown (zeros)
        # Offset 4-5: voltage (uint16, mV)
        # Offset 8-9: current (uint16, mA)
        # Offset 12-13: power (uint16, 0.1mW units - divide by 10000 for W)
        # Offset 24-27: capacity (uint32, µAh - divide by 1000 for mAh)

        def get_uint16_le(offset: int) -> int:
            return struct.unpack('<H', payload[offset:offset+2])[0]

        def get_uint32_le(offset: int) -> int:
            return struct.unpack('<I', payload[offset:offset+4])[0]

        voltage_mv = get_uint16_le(4)
        current_ma = get_uint16_le(8)   # Current at offset 8
        power_raw = get_uint16_le(12)   # Power at offset 12 (mW units)
        capacity_uah = get_uint32_le(24)

        # Temperatures at offsets 32 (external) and 36 (MOSFET) (uint16, divide by 1000 for C)
        ext_temp_raw = get_uint16_le(32)
        mosfet_temp_raw = get_uint16_le(36)

        # Fan speed at offset 40 (uint16, RPM)
        fan_rpm = get_uint16_le(40)

        # Runtime at offset 28 (uint16, in ~48 ticks/second) - total time load has been on
        runtime_ticks = get_uint16_le(28)
        runtime_s = runtime_ticks // 48

        # Calculate energy from capacity and voltage (approximation)
        energy_wh = (capacity_uah / 1000.0) * (voltage_mv / 1000.0) / 1000.0

        # Debug: log the raw values
        self._debug("PARSE", f"Counters: V={voltage_mv}mV I={current_ma}mA P={power_raw} C={capacity_uah}µAh MosT={mosfet_temp_raw} ExtT={ext_temp_raw} Fan={fan_rpm} RT={runtime_s}s")

        return {
            'voltage_mv': voltage_mv,
            'current_ma': current_ma,
            'power_w': power_raw / 1000.0,  # Convert from mW to W
            'capacity_mah': capacity_uah / 1000.0,  # Convert from µAh to mAh
            'energy_wh': energy_wh,
            'mosfet_temp_c': mosfet_temp_raw / 1000.0,  # MOSFET temperature in C
            'ext_temp_c': ext_temp_raw / 1000.0,  # External temperature in C
            'fan_rpm': fan_rpm,
            'runtime': runtime_s,
        }

    def _poll_loop(self) -> None:
        """Background thread to poll device for status."""
        self._debug("INFO", "Poll loop started")

        while self._running and self._device:
            try:
                # Request counters first
                counters = None
                counter_resp = self._send_and_receive(self.CMD_TYPE_QUERY, self.SUB_CMD_COUNTERS, b'\x0b')
                if counter_resp:
                    counters = self._parse_counters(counter_resp[4:62])

                # Request live data
                response = self._send_and_receive(self.CMD_TYPE_QUERY, self.SUB_CMD_LIVE_DATA, b'\x0b')
                if response:
                    payload = response[4:62]
                    status = self._parse_live_data(payload, counters)

                    self._last_status = status
                    self._debug("PARSE", f"Status: {status.voltage:.2f}V {status.current:.3f}A T={status.temperature_c}C")

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

    def set_discharge_time(self, hours: int, minutes: int = 0) -> bool:
        """Set discharge timeout in hours and minutes.

        Args:
            hours: Discharge timeout hours (0-99)
            minutes: Discharge timeout minutes (0-59)
        """
        # Sub-command 0x31 sets discharge timeout
        # Format: [hours] [minutes] 00 [enable] where enable=01 to enable, 00 to disable
        hours = max(0, min(99, hours))  # Clamp to valid range
        minutes = max(0, min(59, minutes))  # Clamp to valid range
        enable = 0x01 if (hours > 0 or minutes > 0) else 0x00
        data = bytes([hours, minutes, 0x00, enable])
        self._debug("INFO", f"Setting discharge time to {hours}h {minutes}m (enable={enable})")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_SET_DISCHARGE_TIME, data)

    def reset_counters(self) -> bool:
        """Reset Wh, mAh, and time counters.

        Note: The reset command (0x47) has been observed in USB captures but
        may not actually reset counters on all firmware versions. The counters
        may need to be reset via the device's physical buttons.
        """
        self._debug("INFO", "Sending reset counters command (may not work on all devices)")
        return self._send_command(self.CMD_TYPE_SET, self.SUB_CMD_RESET, b'\x00\x00\x00\x00')
