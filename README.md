# TabLink

An Android tablet next to a Windows PC, working like one setup:

- **Tablet audio plays on the PC.** Video, music and game sound from the tablet come out of the PC's speakers or headset.
- **Multi control.** Push the mouse past the edge of the screen and the cursor moves onto the tablet, like an extra monitor (similar to Samsung Multi Control or Apple Universal Control). The PC keyboard and wheel go to the tablet too, and the clipboard is shared.
- **USB or Wi-Fi.** It prefers USB and falls back to wireless debugging when the cable is unplugged.

> 한국어 요약: 안드로이드 태블릿 소리를 PC로 재생하고, 마우스를 화면 끝으로 밀면 태블릿으로 넘어가서 PC 마우스/키보드로 조작하는 무료 오픈소스 Windows 앱입니다. USB와 무선 디버깅을 모두 지원하고, 케이블이 빠지면 Wi-Fi로 자동 전환합니다.

Tested on a Galaxy Tab S9 Ultra (Android 16) with Windows 11.

## How it works

| Feature | Implementation |
|---|---|
| Audio | Runs [scrcpy](https://github.com/Genymobile/scrcpy) in audio-only mode (`--no-video --no-window`, Android 11+) |
| Mouse/keyboard | Starts the scrcpy server with control only and creates a virtual **UHID** USB mouse and keyboard. Android shows its own mouse cursor, so no screen mirroring is needed |
| Edge crossing | Windows low-level input hooks. While the tablet has input, the PC cursor is hidden and held still, and the movement is forwarded to the tablet. Android's UHID mouse has no acceleration, so the tablet cursor position can be tracked exactly on the PC; push past the opposite edge to come back |
| Connection | adb over USB, plus wireless debugging found automatically through mDNS |

## Requirements

- Windows 10/11
- Android 11 or later (audio forwarding needs 11+)
- **USB debugging** enabled on the tablet (Developer options); turn on **Wireless debugging** too if you want Wi-Fi

## Install

### Release build
Download `TabLink-win64.zip` from [Releases](../../releases), unzip it and run `TabLink.exe`. scrcpy and adb are included.

### Run from source
```powershell
winget install Genymobile.scrcpy     # provides adb and scrcpy-server
pip install -r requirements.txt
python app.py
```
You can also point the `SCRCPY_DIR` environment variable at a scrcpy folder.

## Usage

1. Connect the tablet over USB and tap **Allow** on the USB debugging prompt.
2. The app connects on its own, and tablet audio starts playing on the PC.
3. Push the mouse against the screen edge shown in the diagram and the cursor moves onto the tablet.
   - Push back past the opposite edge, or press **Ctrl+Alt+M**, to return.
   - Click the diagram or use the buttons to change which side the tablet is on.
4. Wi-Fi: turn on *Wireless debugging* on the tablet and it is found automatically.
   On a PC that hasn't been paired yet, pair once with **Wireless pairing** (IP:port plus the 6-digit code).

### Hangul/English key
Samsung Keyboard switches language with a hardware keyboard using **Shift+Space**, so TabLink's default maps the 한/영 key to Shift+Space. You can change this in the settings.

## Build
```powershell
pip install pyinstaller
python build.py      # → dist/TabLink-win64.zip
```

## License
MIT. The bundled scrcpy/adb are under the Apache License 2.0 (see `scrcpy/LICENSE.txt`).
