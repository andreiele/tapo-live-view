from __future__ import annotations

import logging
import threading

DEFAULT_ONVIF_PORT = 2020


class PTZController:
    """Pan/tilt control for a single camera over ONVIF.

    Tapo cameras that physically support pan/tilt expose an ONVIF service
    (normally on port 2020) using the same camera-account credentials as
    RTSP. Non-PTZ models either refuse the connection or report a profile
    with no PTZConfiguration; both are treated as "not available" rather
    than as errors so the live view still works fine without the pad.
    """

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._lock = threading.Lock()
        self._ptz = None
        self._profile_token: str | None = None
        self.available = False
        self.error: str | None = None

    def connect(self) -> bool:
        try:
            from onvif import ONVIFCamera
            from zeep.transports import Transport
        except ImportError:
            self.error = "The onvif-zeep package is not installed."
            return False
        try:
            transport = Transport(timeout=5, operation_timeout=5)
            camera = ONVIFCamera(self.host, self.port, self.username, self.password, transport=transport)
            media = camera.create_media_service()
            profiles = media.GetProfiles()
            if not profiles:
                self.error = "The camera reported no media profiles."
                return False
            profile = profiles[0]
            if getattr(profile, "PTZConfiguration", None) is None:
                self.error = "This camera does not support pan/tilt."
                return False
            ptz = camera.create_ptz_service()
        except Exception as exc:
            self.error = str(exc)
            return False

        with self._lock:
            self._ptz = ptz
            self._profile_token = profile.token
            self.available = True
        return True

    def continuous_move(self, pan: float, tilt: float) -> None:
        with self._lock:
            ptz, token = self._ptz, self._profile_token
        if not ptz or not token:
            return
        try:
            ptz.ContinuousMove(
                {
                    "ProfileToken": token,
                    "Velocity": {"PanTilt": {"x": pan, "y": tilt}},
                }
            )
        except Exception as exc:
            logging.warning("PTZ move failed for %s: %s", self.host, exc)

    def stop(self) -> None:
        with self._lock:
            ptz, token = self._ptz, self._profile_token
        if not ptz or not token:
            return
        try:
            ptz.Stop({"ProfileToken": token, "PanTilt": True})
        except Exception as exc:
            logging.warning("PTZ stop failed for %s: %s", self.host, exc)

    def goto_home(self) -> None:
        with self._lock:
            ptz, token = self._ptz, self._profile_token
        if not ptz or not token:
            return
        try:
            ptz.GotoHomePosition({"ProfileToken": token})
        except Exception as exc:
            logging.warning("PTZ home failed for %s: %s", self.host, exc)
