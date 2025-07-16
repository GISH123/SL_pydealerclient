P:\Anaconda3\condabin\active.bat pk
pyinstaller -c -n ImageDetector --noconfirm -i logo.ico --add-binary="opencv_ffmpeg410_64.dll;." main.pyw
pause