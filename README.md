# Tapo Live View

A small Windows desktop app that opens one TP-Link Tapo camera's local RTSP live feed in its own window. It is inspired by the structure of `andreiele/blink-live-view`, but it talks directly to the camera over your home network instead of using a cloud service.

## Features

- One-click live view from a Windows desktop shortcut
- Direct local-network RTSP connection
- High-quality (`stream1`) and standard-quality (`stream2`) switching
- Reconnect, mute/unmute and fullscreen controls
- On-screen pan/tilt controls over ONVIF for cameras that physically move
- Low-latency TCP playback through FFmpeg/ffplay
- Camera password stored in Windows Credential Manager, not `config.json`
- No browser and no Tapo cloud login in the app

## Requirements

- Windows 10 or Windows 11
- Python 3.9 or newer
- FFmpeg, including `ffplay.exe`
- A wired Tapo camera that supports RTSP, such as many C100/C110/C200/C210 models
- PC and camera connected to the same local network

## Camera preparation

1. Add the camera normally in the Tapo mobile app.
2. Give the camera a stable IP address using your router's DHCP reservation feature.
3. In the Tapo app, open **Camera Settings → Advanced Settings → Camera Account**.
4. Create a camera username and password. This is separate from your TP-Link account.

## Install

1. Extract this folder somewhere permanent, for example `C:\Tools\tapo-live-view`.
2. Double-click `Setup.bat`.
3. Enter the camera name, IP address and Camera Account credentials.
4. Run `Create Desktop Shortcut.bat`.
5. Open **Tapo Live View** from the desktop.

`Setup.bat` can install FFmpeg through Windows Package Manager when it is missing.

## Pan/tilt controls

If your camera model physically pans and tilts (for example Tapo C200/C210/C225), a directional pad
appears automatically in the bottom-right corner of the live view. It uses the camera's ONVIF service
(normally on port 554-adjacent port `2020`) with the same Camera Account credentials as RTSP — no
extra setup beyond what `Setup.bat` already asks for.

- The pad only appears after the app confirms the camera supports PTZ; fixed-position cameras never show it.
- Press and hold a direction to move, release to stop; the center button returns to the camera's home position (if it has one).
- If your camera uses a non-default ONVIF port, set it during setup or edit `onvif_port` in `config.json`.
- `ptz_speed` in `config.json` (0.0–1.0, default `0.5`) controls how fast the camera moves.

## Files

| File | Purpose |
|---|---|
| `Setup.bat` | Creates the local Python environment, installs dependencies and opens camera setup |
| `Run.bat` | Opens the configured live view |
| `Create Desktop Shortcut.bat` | Creates a desktop shortcut |
| `first_run.py` | Setup window and connection test |
| `live.py` | Native Windows live-view window and embedded ffplay process |
| `app_common.py` | Configuration, RTSP URL, credential and network helpers |
| `ptz.py` | ONVIF pan/tilt controller used by the live view |
| `config.example.json` | Example configuration without credentials |

## Troubleshooting

### Camera port is unreachable

Confirm the PC and camera are on the same Wi-Fi/LAN and are not separated by guest-network or AP-isolation settings. Verify the IP in the Tapo app or router.

### Authentication or stream error

Recreate the **Camera Account** in the Tapo app. This app does not use the email/password for your TP-Link account.

### High quality does not connect

Try **Standard quality**. Other Tapo app, NVR, RTSP or Tapo Care sessions may already be using the available camera streams.

### No pan/tilt controls appear

Your camera model is likely fixed-position (many Tapo cameras, including most `C1xx` models, do not
physically move). If the camera does support PTZ, confirm ONVIF is reachable at `<camera IP>:2020`
and that the Camera Account credentials are correct; check `tapo-live.log` for the specific ONVIF error.

### ffplay is missing

Open Command Prompt and run:

```bat
winget install --id Gyan.FFmpeg -e
```

Then reopen the terminal or sign out and back in so the updated PATH is available.

### Logs

See `tapo-live.log` in the project folder. Passwords and full RTSP URLs are not written to the log.

## Security

- Keep this app local to your home network.
- Do not expose RTSP port 554 or the ONVIF port (2020 by default) through your router.
- `config.json` contains the camera IP and username, but not the password.
- The password is stored using Python Keyring in Windows Credential Manager.

## Known limitations

- This build targets Windows because it embeds `ffplay` with the Win32 API.
- Pan/tilt only appears for camera models that physically support it; zoom is not implemented.
- Battery-powered Tapo cameras commonly do not support continuous RTSP.
