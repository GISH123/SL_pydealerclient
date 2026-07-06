# Latency JSON HTTP / HTTPS API

Please refer to README_simple_instruction.txt for installation.

This service runs **inside ImageDetector / pydealerclient** and exposes:

- Control endpoints for **start / stop predict** for each round (`gmcode`)
- A query endpoint to fetch the **latest latency measurement as JSON**

It is designed for **internal use on the same LAN / VPN** as the detector.

- HTTP base:  `http://<host>:8880/...`
- HTTPS base: `https://<host>:8881/...`  (only if certs are present)

Typical flow for one round:

1. Dealer starts prediction → calls **`/start_predict`** with `gmcode` + `t0`
2. Dealer stops prediction → calls **`/stop_predict`** with the same `gmcode`
3. Dealer / monitor polls **`/latency`** (e.g. every 10 seconds) to read the
   latest latency record.

> **Important:** the query parameter name is strictly `t0` (lowercase).  
> Using `T0` (uppercase) will cause an error like: `required parameters gmcode and t0`.

---

## 1. Base URL & Ports

By default the service listens on:

- **HTTP**: port **8880**
- **HTTPS**: port **8881**

Local examples:

```text
http://127.0.0.1:8880/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123
http://127.0.0.1:8880/latency
http://127.0.0.1:8880/stop_predict?gmcode=GN00725C040WO
```

HTTPS equivalents (when certs exist):

```text
https://127.0.0.1:8881/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123
https://127.0.0.1:8881/latency
https://127.0.0.1:8881/stop_predict?gmcode=GN00725C040WO
```

HTTPS uses a self-signed certificate from:

```text
<exe_folder>/certs/latency_server.crt
<exe_folder>/certs/latency_server.key
```

If these files are missing, only HTTP (8880) will be started.

---

## 2. HTTP Methods & Authentication

- **HTTP method:** currently only `GET` is supported.
- **Authentication:** none.  
  This API is meant to be used **inside a trusted network only** (behind firewall / VPN).

---

## 3. Endpoints

### 3.1 `GET /start_predict`

Notify the latency service that prediction has started for a specific `gmcode`
(round). The service records the **dealer-side start time** `t0` for that round.

**Request**

```http
GET /start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123 HTTP/1.1
Host: <host>:8880
```

Query parameters:

| Name     | Type   | Required | Description                                                                 |
|----------|--------|----------|-----------------------------------------------------------------------------|
| `gmcode` | string | Yes      | Round ID / game code (e.g. `GN00725C040WO`).                               |
| `t0`     | string | Yes      | Dealer start timestamp. Format is agreed by both sides (e.g. `YYYYMMDD HHMMSS.mmm`). |

- The space in `t0` should be URL encoded as `%20`, e.g.  
  `t0=20251218%20134000.123`

**Response**

- On success: HTTP `200 OK`.  
- On missing / invalid parameters: the service returns an error (non-200) and logs a
  message mentioning that parameters `gmcode` and `t0` are required.

Typical client logic: only needs to check that the status code is 200.

---

### 3.2 `GET /stop_predict`

Notify the latency service that prediction has stopped for a specific `gmcode`.
This triggers latency calculation for that round and updates the “latest latency”
data used by `/latency`.

**Request**

```http
GET /stop_predict?gmcode=GN00725C040WO HTTP/1.1
Host: <host>:8880
```

Query parameters:

| Name     | Type   | Required | Description                                           |
|----------|--------|----------|-------------------------------------------------------|
| `gmcode` | string | Yes      | Round ID / game code (must match the start gmcode).  |

**Response**

- On success: HTTP `200 OK`.  
- On missing `gmcode`: an error is returned and logged.

After a successful `/stop_predict`, the `/latency` endpoint will expose the new
record for this round.

---

### 3.3 `GET /latency`

Return the **latest latency record** as JSON.  
This is the main endpoint for external monitoring / dealer polling.

**Request**

```http
GET /latency HTTP/1.1
Host: <host>:8880
Accept: application/json
```

**Successful response (record exists)**

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
Content-Length: ...

{
  "now": "09:48:26.907",
  "gmcode": "DT251118094758",
  "start_t0": "09:47:58.740",
  "stop_t1": "09:48:26.907",
  "inference_latency_s": 28.167,
  "dealer_latency_s": 28.167,
  "latency_Ndelta_s": 21.149
}
```

#### Field meanings

| Field                 | Type   | Description                                                                 |
|-----------------------|--------|-----------------------------------------------------------------------------|
| `now`                 | string | Time (HH:MM:SS.mmm) when this line was recorded                             |
| `gmcode`              | string | Current round ID (e.g. `DT251118094758`)                                    |
| `start_t0`            | string | Time when prediction started                                                |
| `stop_t1`             | string | Time when `stop_predict` was processed                                      |
| `inference_latency_s` | number | Detector inference latency in seconds (T1 − T0, 3 decimal places)           |
| `dealer_latency_s`    | number | Dealer latency in seconds (T1 − dealer timestamp, or = `inference_latency`) |
| `latency_Ndelta_s`    | number | Difference from previous round’s `dealer_latency_s` (current − previous)    |

> For the **first round**, `latency_Ndelta_s` is defined as `0.0`.

#### “No record yet” response

If ImageDetector is running but **no latency record has been produced yet**:

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
X-Latency-Status: no_record
X-Latency-Message: no latency record currently

{}
```

Client logic should:

1. Check header `X-Latency-Status`.
2. If it is `"no_record"`, treat body `{}` as “no data yet” and try again later.

Internally, this endpoint reads the latest latency from **in‑memory state**. The
latency CSV file on disk is written in the same format but is only for history
/ offline analysis.

---

### 3.4 `GET /`

`GET /` is an alias of `/latency` and behaves exactly the same.  
You can simply open `http://<host>:8880/` in a browser to see the same JSON.

---

## 4. CSV output format & location

Even though the JSON API uses in‑memory data, the system also writes each round
to a CSV file for history.

CSV files are created under:

```text
<exe_folder>/log/<YYYY-MM-DD>/latency_<YYYYMMDD>_<HHMMSS>.csv
```

Each line has the same columns as the `/latency` JSON:

```text
now,gmcode,start_t0,stop_t1,inference_latency_s,dealer_latency_s,latency_Ndelta_s
```

Example CSV row:

```text
10:06:31.399,DT251118100604,10:06:04.777,10:06:31.398,26.621,26.628,18.489
```

These CSV files are append‑only logs and can be used for:

- Offline analysis
- Debug / QA
- Comparing dealer vs detector behavior over time

There is also a toggle in `config.xml` that can disable CSV output while keeping
the JSON API working (for environments that do not want extra disk I/O).

---

## 5. HTTPS notes

When certs are present (`certs/latency_server.crt` + `.key`):

- An additional HTTPS listener is started on port **8881**.
- The certificate is usually **self-signed**, so the client must either:
  - ignore certificate verification (for internal testing), or
  - trust the cert in its OS / runtime (import as a trusted root / intermediate).

Example (curl, ignore self-signed cert):

```bash
# HTTP
curl "http://127.0.0.1:8880/latency"

# HTTPS (ignore self-signed issue)
curl -k "https://127.0.0.1:8881/latency"
```

You can also call the control endpoints via HTTPS:

```bash
curl -k "https://127.0.0.1:8881/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123"
curl -k "https://127.0.0.1:8881/stop_predict?gmcode=GN00725C040WO"
```

---

## 6. Polling recommendation

For an external dealer / dashboard:

- Recommended interval: **every 10 seconds** call `/latency`
- Always treat the response as “latest known good latency line”
- If you need full history, read the CSV files under `log/<YYYY-MM-DD>/...`

The service does **not** provide:

- Pagination
- Historical query by time range
- Filtering by `gmcode`

Those can be built outside by parsing CSVs if required.

---

## 7. Error handling

General rules:

- Normal operations return **HTTP 200**.
- When required parameters are missing / invalid (e.g. `/start_predict` called
  without `gmcode` or `t0`), the service returns a non‑200 error and logs
  details into the ImageDetector log.

For `/latency` specifically:

- If no record exists yet:
  - HTTP 200
  - Headers: `X-Latency-Status: no_record`
  - Body: `{}`
- Internal issues (e.g. CSV read failure, unexpected exception) will be logged
  via the same pylogger as the rest of ImageDetector.

Client logic suggestion:

1. Confirm HTTP status code (`2xx` vs others).
2. For `/latency`, check `X-Latency-Status`.
3. If status is OK and not `no_record`, parse the JSON body.

---

## 8. Quick examples

### 8.1 Start / stop a round via HTTP

```bash
# Start predict for a round
curl "http://127.0.0.1:8880/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123"

# Stop predict for the same round
curl "http://127.0.0.1:8880/stop_predict?gmcode=GN00725C040WO"
```

### 8.2 Read latest latency (HTTP)

```bash
curl "http://127.0.0.1:8880/latency"
```

### 8.3 Read latest latency (HTTPS)

```bash
curl -k "https://127.0.0.1:8881/latency"
```

### 8.4 Example `/latency` response

```json
{
  "now": "10:06:31.399",
  "gmcode": "DT251118100604",
  "start_t0": "10:06:04.777",
  "stop_t1": "10:06:31.398",
  "inference_latency_s": 26.621,
  "dealer_latency_s": 26.628,
  "latency_Ndelta_s": 18.489
}
```

