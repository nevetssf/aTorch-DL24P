"""Desktop and sound notification system."""

import platform
import subprocess
import threading
from typing import Callable, Optional
from pathlib import Path

from .conditions import AlertCondition, AlertResult
from ..protocol.atorch_protocol import DeviceStatus


class Notifier:
    """Manages alert conditions and sends notifications."""

    def __init__(self):
        self._conditions: list[AlertCondition] = []
        self._sound_enabled = True
        self._desktop_enabled = True
        self._callback: Optional[Callable[[AlertResult], None]] = None

    @property
    def sound_enabled(self) -> bool:
        return self._sound_enabled

    @sound_enabled.setter
    def sound_enabled(self, value: bool) -> None:
        self._sound_enabled = value

    @property
    def desktop_enabled(self) -> bool:
        return self._desktop_enabled

    @desktop_enabled.setter
    def desktop_enabled(self, value: bool) -> None:
        self._desktop_enabled = value

    def set_callback(self, callback: Callable[[AlertResult], None]) -> None:
        """Set callback for when alerts trigger."""
        self._callback = callback

    def add_condition(self, condition: AlertCondition) -> None:
        """Add an alert condition."""
        self._conditions.append(condition)

    def remove_condition(self, condition: AlertCondition) -> None:
        """Remove an alert condition."""
        if condition in self._conditions:
            self._conditions.remove(condition)

    def clear_conditions(self) -> None:
        """Remove all conditions."""
        self._conditions.clear()

    def reset_all(self) -> None:
        """Reset all alert conditions."""
        for condition in self._conditions:
            condition.reset()

    def get_condition(self, condition_type: type) -> Optional[AlertCondition]:
        """Get a specific condition by type.

        Args:
            condition_type: The class type of the condition to find

        Returns:
            The condition instance if found, None otherwise
        """
        for condition in self._conditions:
            if isinstance(condition, condition_type):
                return condition
        return None

    def check(self, status: DeviceStatus) -> list[AlertResult]:
        """Check all conditions against current status.

        Args:
            status: Current device status

        Returns:
            List of triggered alerts
        """
        results = []

        for condition in self._conditions:
            result = condition.check(status)
            if result and result.triggered:
                results.append(result)
                self._notify(result)

        return results

    def _notify(self, result: AlertResult) -> None:
        """Send notification for an alert."""
        # Callback
        if self._callback:
            try:
                self._callback(result)
            except Exception:
                pass

        # Desktop notification (run in background thread to avoid blocking GUI)
        if self._desktop_enabled:
            thread = threading.Thread(
                target=self._send_desktop_notification,
                args=(result,),
                daemon=True
            )
            thread.start()

        # Sound (run in background thread to avoid blocking GUI)
        if self._sound_enabled:
            thread = threading.Thread(
                target=self._play_sound,
                args=(result.severity,),
                daemon=True
            )
            thread.start()

    def _send_desktop_notification(self, result: AlertResult) -> None:
        """Send a desktop notification."""
        title = "Load Test Bench"
        message = result.message

        system = platform.system()

        try:
            if system == "Darwin":
                # macOS
                script = f'display notification "{message}" with title "{title}"'
                subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    timeout=5,
                )
            elif system == "Windows":
                # Windows 10+ toast notification via PowerShell
                ps_script = f'''
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
                $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
                $text = $xml.GetElementsByTagName("text")
                $text[0].AppendChild($xml.CreateTextNode("{title}")) | Out-Null
                $text[1].AppendChild($xml.CreateTextNode("{message}")) | Out-Null
                $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
                [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Load Test Bench").Show($toast)
                '''
                subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True,
                    timeout=5,
                )
            elif system == "Linux":
                # Linux notify-send
                subprocess.run(
                    ["notify-send", title, message],
                    capture_output=True,
                    timeout=5,
                )
        except Exception:
            pass

    def _play_sound(self, severity: str) -> None:
        """Play an alert sound."""
        system = platform.system()

        try:
            if system == "Darwin":
                # macOS system sounds
                if severity == "error":
                    sound = "Basso"
                elif severity == "warning":
                    sound = "Ping"
                else:
                    sound = "Glass"

                subprocess.run(
                    ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                    capture_output=True,
                    timeout=5,
                )
            elif system == "Windows":
                # Windows system sounds via PowerShell
                if severity == "error":
                    sound_type = "SystemHand"
                elif severity == "warning":
                    sound_type = "SystemExclamation"
                else:
                    sound_type = "SystemAsterisk"

                subprocess.run(
                    ["powershell", "-Command", f"[System.Media.SystemSounds]::{sound_type}.Play()"],
                    capture_output=True,
                    timeout=5,
                )
            elif system == "Linux":
                # Try paplay (PulseAudio) or aplay
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    capture_output=True,
                    timeout=5,
                )
        except Exception:
            pass
