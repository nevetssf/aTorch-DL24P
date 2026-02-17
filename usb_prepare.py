#!/usr/bin/env python3
"""Send USB SET_IDLE HID class request to the DL24P device.

On macOS, after power-cycling the DL24P, the device needs a SET_IDLE request
that macOS doesn't send during USB enumeration (Windows does automatically).
Without this, the device will not respond to any HID commands.

This script requires root/admin privileges on macOS because the OS kernel
claims HID devices exclusively. We use libusb to detach the kernel driver,
send the SET_IDLE request, and reattach.

Usage:
    sudo python usb_prepare.py
"""

import sys

VENDOR_ID = 0x0483   # STMicroelectronics
PRODUCT_ID = 0x5750  # DL24P custom HID device

# USB HID SET_IDLE class request parameters
BMREQUEST_TYPE = 0x21  # Host-to-device, Class, Interface
BREQUEST_SET_IDLE = 0x0A
INTERFACE = 0


def main():
    try:
        import usb.core
        import usb.util
    except ImportError:
        print("ERROR: pyusb not installed. Install with: pip install pyusb", file=sys.stderr)
        sys.exit(1)

    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        print(f"ERROR: DL24P device not found (VID={VENDOR_ID:#06x} PID={PRODUCT_ID:#06x})", file=sys.stderr)
        sys.exit(1)

    print(f"Found DL24P: {dev.manufacturer} {dev.product}")

    # Detach kernel driver if active (required on macOS)
    try:
        if dev.is_kernel_driver_active(INTERFACE):
            print("Detaching kernel driver...")
            dev.detach_kernel_driver(INTERFACE)
    except (usb.core.USBError, NotImplementedError) as e:
        print(f"Warning: Could not detach kernel driver: {e}")

    # Send SET_IDLE request
    try:
        dev.ctrl_transfer(
            BMREQUEST_TYPE,    # bmRequestType
            BREQUEST_SET_IDLE, # bRequest
            0x0000,            # wValue (duration=0, report_id=0)
            INTERFACE,         # wIndex (interface)
        )
        print("SET_IDLE sent successfully")
    except usb.core.USBError as e:
        print(f"ERROR: Failed to send SET_IDLE: {e}", file=sys.stderr)
        sys.exit(1)

    # Reattach kernel driver so the OS can enumerate the device again
    try:
        usb.util.dispose_resources(dev)
        dev.attach_kernel_driver(INTERFACE)
        print("Kernel driver reattached")
    except (usb.core.USBError, NotImplementedError) as e:
        print(f"Warning: Could not reattach kernel driver: {e}")
        print("You may need to unplug and replug the device.")

    print("Device initialization complete")


if __name__ == "__main__":
    main()
