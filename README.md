# SL_pydealerclient / ImageDetector Latency

Public sanitized handoff repository for the original pydealerclient / ImageDetector latency source.

This repository is intended for source-code handoff. Local runtime configs, model files, videos, generated build outputs, and binary artifacts should not be committed.

---

## Verified Fresh Environment Setup

Verified on Windows with a fresh conda environment.

Recommended environment name:

    pydealerclient_latency_py31012

Create and activate the environment:

    conda create -n pydealerclient_latency_py31012 python=3.10.12 pip "openssl=1.1.1w" ca-certificates certifi -y
    conda activate pydealerclient_latency_py31012

Important: this Python 3.10.12 environment must use OpenSSL 1.1.1w. If conda installs OpenSSL 3.x, `import ssl` may fail and pip may not be able to download packages.

Verify SSL before installing dependencies:

    python -c "import ssl; print('SSL OK:', ssl.OPENSSL_VERSION)"

Expected output:

    SSL OK: OpenSSL 1.1.1w  11 Sep 2023

Install dependencies:

    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r requirements.txt

Verify imports:

    python -c "import cv2, numpy, twisted, pandas, tensorflow as tf, PyInstaller; print('imports OK'); print('tf', tf.__version__); print('cv2', cv2.__version__); print('numpy', numpy.__version__); print('PyInstaller', PyInstaller.__version__)"

Verified import result:

    imports OK
    tf 2.10.1
    cv2 4.9.0
    numpy 1.23.5
    PyInstaller 6.5.0

CPU-only note: if TensorFlow prints a warning about `cudart64_110.dll` missing, that is acceptable for CPU-only smoke testing. TensorFlow can still import and the application can still be tested for startup/runtime flow without GPU acceleration.

Verify source syntax:

    python -m compileall -q .

If `compileall` has no output, the source compile check passed.

---

## Local Runtime Configs

The following files are local runtime files and should not be committed:

    config.xml
    models/videolist.xml
    doc/model_B04/videolist.xml

Use these sanitized templates as references:

    config.example.xml
    models/videolist.example.xml

Before running or packaging locally, copy/edit the templates into real local runtime files as needed.

---

## Build EXE

Activate the verified environment first:

    conda activate pydealerclient_latency_py31012

Recommended build command:

    python -m PyInstaller --clean --noconfirm ImageDetector_Latency.spec

The spec may auto-bump `version.txt` during build and copy the version file into the generated dist folder.

Expected local build outputs:

    build/
    dist/

Do not commit generated build outputs.

---

## Git Hygiene

Do not commit:

- local runtime configs
- real internal stream URLs, dealer IPs, FTP hosts, or credentials
- generated EXE/DLL/PYD files
- model `.pb` files
- videos or datasets
- logs, CSV output, screenshots, or prediction images

This repository keeps sanitized examples for handoff and documents how to recreate the runtime environment.

---

# 20260528 update : pydealerLatency UAT final source + HTTP latency service

This version is the current **pydealerLatency / ImageDetector_Latency** package used for latency testing in the UAT environment.

Main purpose:

- Run the original pydealer / ImageDetector inference flow.
- Support latency-mode testing for MH5 / WS bridge / dealer-side testing.
- Expose an internal HTTP / HTTPS JSON service for latency control and latest latency query.
- Write latency CSV records for long-running UAT observation.
- Prevent CSV file locks, especially when the CSV is opened by Excel, from blocking the pydealer inference process.

## Current project scope

This repository is for the latency testing version of pydealer.

It is different from the normal Ball3 / BAC production branches.  
The main testing target is `lattest` latency mode, where the detector focuses on index `1` and measures the time difference between start / stop events.

Typical external test flow:

```text
MH5 / dealer test client
    -> WS bridge / TCP bridge
    -> ImageDetector_Latency
    -> model inference
    -> latency CSV + latest JSON API
```

## Main changes in this version

### 1. Embedded latency HTTP / HTTPS service

The detector now starts an internal latency service when `main.py` starts.

Default ports:

```text
HTTP  : 8880
HTTPS : 8881
```

HTTP is always started.

HTTPS is started only when the following cert files exist:

```text
<exe_folder>/certs/latency_server.crt
<exe_folder>/certs/latency_server.key
```

If the certs do not exist, the program continues with HTTP only.

### 2. Latency JSON API

Main endpoints:

```text
GET  /latency
GET  /latency_json
GET  /start_predict
POST /start_predict
GET  /stop_predict
POST /stop_predict
```

Common examples:

```text
http://127.0.0.1:8880/latency

http://127.0.0.1:8880/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123

http://127.0.0.1:8880/stop_predict?gmcode=GN00725C040WO
```

`/latency` returns the latest latency row from in-memory state.  
If no latency record exists yet, it returns `{}` with the `X-Latency-Status: no_record` header.

`/start_predict` requires:

```text
gmcode
t0
```

Important:

```text
t0 must be lowercase.
```

Do not use uppercase `T0`.

`/start_predict` will:

1. record the external dealer timestamp `t0`
2. call `startPredict`
3. dispatch index `1`
4. wait for model result
5. auto-stop the round when prediction is done
6. write latency result

`/stop_predict` can manually stop the current active latency round.

The `mark` parameter controls whether this manual stop writes latency CSV:

```text
mark=1  stop and write latency
mark=0  stop without writing latency
```

When no `gmcode` is provided for manual stop, the default behavior is to stop the current active round without writing a latency row.

### 3. Latency CSV output

Latency CSV is written under:

```text
log/<YYYY-MM-DD>/latency_<YYYYMMDD>_<HHMMSS>.csv
```

Main columns:

```text
now
gmcode
start_t0
stop_t1
inference_latency_s
dealer_latency_s
latency_Ndelta_s
video_url
tableID
```

The visible CSV timestamp format is now:

```text
YYYYMMDD HH:MM:SS
```

This makes long-running multi-day UAT logs easier to review.

`latency_Ndelta_s` means the difference between the current round’s `dealer_latency_s` and the previous round’s `dealer_latency_s`.

For the first row:

```text
latency_Ndelta_s = 0
```

### 4. CSV lock protection

This version prevents the detector from blocking when the CSV is opened by Excel.

If Windows / Excel locks the CSV file:

1. the current row is written to a sidecar pending file
2. the pydealer inference process continues running
3. pending rows are flushed back into the real CSV on a later successful write

Pending file format:

```text
<latency_csv_filename>.pending
```

This behavior is used both in the latency CSV writer and the general CSV tool.

### 5. Latency mode dispatch behavior

For `gmtype == lattest`:

- only index `1` is used
- multiple dispatches can happen within one round
- each accepted dispatch starts a new dispatch cycle
- duplicate dispatch is ignored if the previous cycle is still detecting
- empty class is treated as transient and does not complete the dispatch cycle
- cardback / valid prediction result can complete a dispatch cycle
- the round is ended by stop predict / HTTP control flow, not by dispatch alone

This is designed for latency measurement, not normal Ball3 / BAC gameplay logic.

### 6. Runtime and stream related settings

Current `config.xml` supports several runtime options:

```xml
<save_small_image>1</save_small_image>
<video_loop>1</video_loop>
<max_grab_fps>60</max_grab_fps>
<cap_buffersize>2</cap_buffersize>
<stream_publish_fps>60</stream_publish_fps>
<stream_drain_grab_max>200</stream_drain_grab_max>
```

Purpose:

- `save_small_image`: enable / disable cropped prediction image saving
- `video_loop`: loop local video when it reaches the end
- `max_grab_fps`: cap local video / stream grabbing speed
- `cap_buffersize`: OpenCV capture buffer hint
- `stream_publish_fps`: UI / prediction publish rate for network streams
- `stream_drain_grab_max`: max grab attempts used to reduce network stream backlog

### 7. Version and packaging

The PyInstaller spec is:

```text
ImageDetector_Latency.spec
```

The spec auto-bumps `version.txt` during build.

Current version file format:

```text
Imagedetector_latency_v<MAJOR>_<MINOR>_<PATCH>
```

Example:

```text
Imagedetector_latency_v1_0_9
```

The generated version is printed on startup and also copied into the packaged dist folder.

The spec also handles:

- CUDA DLL collection into `_internal/cuda`
- TensorFlow / setuptools distutils runtime hooks
- optional certs folder packaging
- `version.txt` packaging

### 8. Documents

Latency usage and API documents are already prepared under:

```text
doc/
  README_simple_instruction.txt
  latency_http_api_en.md
  latency_http_api_zh_CN.md
```

The root-level copies of the HTTP API documents are kept for convenience.

Recommended reading order:

```text
1. doc/README_simple_instruction.txt
2. doc/latency_http_api_zh_CN.md
3. doc/latency_http_api_en.md
```

---

# 20260426 latency 把csv的時間欄位多新增YYYYmmdd與修復csv開啟時無法寫入導致推論端卡住問題  

因應目前線上測試的要求，方便查詢持續好幾天的運行，欄位加上年月日供參考。  
且修復開啟 csv 時會讓推論卡住的問題。

# 20260216 latency for multiple dispatch index per round, continous to predict until first real card predicted  

配合 mock_dealer_app(DragonTigerWS) 重複發送 dispatch index 命令，主要是 for latency(lattest)。

# 20251226 latency update : command for packaging test on cuda related files

```bat
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
set "PYDEALER_PREHOOK_DEBUG=1"

dist_new2\ImageDetector_Latency\ImageDetector_Latency.exe > run_prod_sim.log 2>&1
```

# 20251226 update: env creation (pydealer_latency)

## 1. Create + activate env

```bat
conda create -n pydealer_latency_venv_nocuda python=3.10.12 -y
conda activate pydealer_latency_venv_nocuda
```

## 2. Upgrade pip toolchain

```bat
python -m pip install -U pip setuptools wheel
```

## 3. Pin CUDA11.2 + cuDNN inside env

Install CUDA 11.2 + cuDNN 8.9.7.29 on your own computer.

## 4. Install project requirements

```bat
pip install -r .\requirements.txt
```

## 5. Quick sanity checks

```bat
python -c "import tensorflow as tf; bi=tf.sysconfig.get_build_info(); print('TF', tf.__version__); print('cudart', bi.get('cudart_dll_name')); print('cuda_version', bi.get('cuda_version')); print('cudnn', bi.get('cudnn_dll_name')); print('is_cuda_build', bi.get('is_cuda_build'))"
python -c "import tensorflow as tf; print('GPUs:', tf.config.list_physical_devices('GPU'))"
```

## 6. Show key DLLs actually present in this env

```bat
dir "%CONDA_PREFIX%\Library\bin\cudart64_*.dll"
dir "%CONDA_PREFIX%\Library\bin\cublasLt64_*.dll"
dir "%CONDA_PREFIX%\Library\bin\cudnn64_*.dll"
```

## Smoke test

```bat
python main.py
```

## PyInstaller build command

Recommended:

```bat
pyinstaller --clean --noconfirm ImageDetector_Latency.spec
```

Legacy manual command:

```bat
pyinstaller --clean --onedir --console --name ImageDetector_PH --hidden-import=tkinter --runtime-hook=hook_force_stdlib_distutils.py --add-data "config.xml;." --add-data "models;models" main.py
```

If the generated dist folder does not contain `config.xml` or the `models` folder, manually copy them from the project root into the dist folder.

# PyDealerClient

Image recognition program that samples live video and sends result data to Dealer by network socket.

# Release note

## 2022/11/2 v1.5.6

1. fix screenshot upload after 16s.
2. log add `gmSaveFinalResult` and `gmCount`.
3. support samba folder to save snapshot images.

## 2022/10/22 v1.5.1

1. update snapshot image behavior.
2. config file update:

```xml
<save folder="./predict_images" autoUpload="0"/>
```

Reference code:

```cpp
// if len(save_descjudge) > 0:
//     self.imageSaver.save(gmcode, int(pos.index), save_descjudge, save_scorejudge, predict_image_save, False)

imageSaver = ImageSaver(cfg.save_folder)
```

## 2022/10/5 v1.5.0

Only produce one full image and upload to FTP Server.

## 2022/8/16 v1.4.2

Initial baseline.
