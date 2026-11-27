# FFmpeg for VideoUniq Pro

Place platform binaries here so the app stays portable:

- Windows: `vendor/ffmpeg/win64/ffmpeg.exe` and `ffprobe.exe`
- Linux: `vendor/ffmpeg/linux64/ffmpeg` and `ffprobe`

If these files are missing, the app uses `ffmpeg` / `ffprobe` from `PATH`.
