# 延迟 JSON HTTP / HTTPS 接口说明

請先參照README_simple_instruction.txt 進行安裝。

该服务运行在 **ImageDetector / pydealerclient** 进程内，对外提供：

- 控制接口：通知 **开始预测 / 停止预测**（按局号 `gmcode`）  
- 查询接口：获取“最新一笔延迟数据”的 JSON

设计用途为：部署在与检测端同一局域网 / VPN 的内部服务。

- HTTP 基址：`http://<host>:8880/...`
- HTTPS 基址：`https://<host>:8881/...`（仅在存在证书时）

一局完整流程的典型调用顺序：

1. 一局开始预测 → 调用 **`/start_predict`**，带上 `gmcode` 与 `t0`（荷官起始时间）  
2. 同一局结束预测 → 调用 **`/stop_predict`**，带上相同的 `gmcode`  
3. 监控端 / 上游系统周期性轮询 **`/latency`**（如每 10 秒一次），读取最新一笔延迟记录

> **注意：** 查询参数名必须是小写 `t0`。  
> 若使用大写 `T0`，服务会返回错误，提示：`required parameters gmcode and t0`。

---

## 1. 基本地址与端口

默认监听端口：

- **HTTP**：端口 **8880**
- **HTTPS**：端口 **8881**

本机示例：

```text
http://127.0.0.1:8880/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123
http://127.0.0.1:8880/latency
http://127.0.0.1:8880/stop_predict?gmcode=GN00725C040WO
```

在存在证书时，对应的 HTTPS 示例：

```text
https://127.0.0.1:8881/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123
https://127.0.0.1:8881/latency
https://127.0.0.1:8881/stop_predict?gmcode=GN00725C040WO
```

HTTPS 使用自签名证书，默认放置在：

```text
<exe_folder>/certs/latency_server.crt
<exe_folder>/certs/latency_server.key
```

若上述文件不存在，则仅启动 HTTP（8880），不会启动 HTTPS。

---

## 2. HTTP 方法与认证

- **HTTP 方法：** 当前仅支持 `GET`  
- **认证方式：** 无认证  
- 使用场景：仅限于内部网络（建议置于防火墙 / VPN 背后）

---

## 3. 接口列表

### 3.1 `GET /start_predict`

通知延迟服务：某个 `gmcode`（一局游戏）已开始预测，服务会记录该局的
**荷官起始时间** `t0`。

**请求示例**

```http
GET /start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123 HTTP/1.1
Host: <host>:8880
```

查询参数：

| 参数名   | 类型   | 必填 | 说明                                             |
|----------|--------|------|--------------------------------------------------|
| `gmcode` | string | 是   | 游戏局号，例如 `GN00725C040WO`                  |
| `t0`     | string | 是   | 荷官起始时间戳，格式由双方约定（如 `YYYYMMDD HHMMSS.mmm`） |

- 其中 `t0` 字段中的空格需做 URL 编码，例如：  
  `t0=20251218%20134000.123`

**响应**

- 正常情况：HTTP `200 OK`；
- 若缺少或参数非法（如未提供 `gmcode` 或 `t0`），接口返回非 200 错误，
  并在日志中记录需要参数 `gmcode` 与 `t0`。

客户端通常只需确认状态码是否为 200。

---

### 3.2 `GET /stop_predict`

通知延迟服务：某个 `gmcode` 对应的一局预测已结束。服务会据此计算该局的
延迟信息，并更新 `/latency` 使用的“最新记录”。

**请求示例**

```http
GET /stop_predict?gmcode=GN00725C040WO HTTP/1.1
Host: <host>:8880
```

查询参数：

| 参数名   | 类型   | 必填 | 说明                               |
|----------|--------|------|------------------------------------|
| `gmcode` | string | 是   | 游戏局号，需与 `/start_predict` 时的 gmcode 一致 |

**响应**

- 正常情况：HTTP `200 OK`；
- 若缺少 `gmcode`，接口返回错误并记录日志。

成功调用 `stop_predict` 后，本局的延迟信息会被写入内存及 CSV，并通过
`/latency` 对外提供。

---

### 3.3 `GET /latency`

返回 **最新一笔延迟记录** 的 JSON。  
这是外部监控 / 上游系统的主要查询接口。

**请求示例**

```http
GET /latency HTTP/1.1
Host: <host>:8880
Accept: application/json
```

**正常响应（有记录）**

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

#### 字段说明

| 字段名                | 类型   | 含义                                                                 |
|-----------------------|--------|----------------------------------------------------------------------|
| `now`                 | string | 记录写入时间（HH:MM:SS.mmm）                                         |
| `gmcode`              | string | 本局游戏局号，例如 `DT251118094758`                                  |
| `start_t0`            | string | 触发预测开始的时间                                                   |
| `stop_t1`             | string | 收到 `stop_predict` 并完成处理的时间                                 |
| `inference_latency_s` | number | 检测端推理耗时（秒），即 T1 − T0，保留 3 位小数                      |
| `dealer_latency_s`    | number | 荷官侧延迟（秒），T1 − 荷官时间戳；若无荷官时间戳，则等于 inference   |
| `latency_Ndelta_s`    | number | 本局 `dealer_latency_s` − 上一局 `dealer_latency_s` 的差值          |

> 第一局时没有上一局，`latency_Ndelta_s` 定义为 `0.0`。

#### “暂无记录” 响应

ImageDetector 已运行，但目前 **尚未产生任何一笔延迟记录** 时：

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
X-Latency-Status: no_record
X-Latency-Message: no latency record currently

{}
```

客户端建议处理方式：

1. 先检查响应头 `X-Latency-Status`；  
2. 若值为 `"no_record"`，说明暂时无数据，本次轮询可忽略；  
3. 之后再按策略重试。

内部实现上，`/latency` 使用的是 **内存中的最新一笔数据**。  
磁盘上的 CSV 日志格式相同，但仅用于历史记录与离线分析。

---

### 3.4 `GET /`

`GET /` 是 `/latency` 的别名，行为完全相同。  
可直接在浏览器打开 `http://<host>:8880/` 查看最新一笔 JSON。

---

## 4. CSV 输出格式与位置

虽然 JSON 接口使用内存数据，系统仍会将每一局写入 CSV 方便追踪。

CSV 文件路径格式：

```text
<exe_folder>/log/<YYYY-MM-DD>/latency_<YYYYMMDD>_<HHMMSS>.csv
```

文件头（列名）：

```text
now,gmcode,start_t0,stop_t1,inference_latency_s,dealer_latency_s,latency_Ndelta_s
```

示例行：

```text
10:06:31.399,DT251118100604,10:06:04.777,10:06:31.398,26.621,26.628,18.489
```

CSV 文件为追加写入，可用于：

- 离线分析
- 调试 / QA
- 对比荷官端与检测端在长期运行下的行为

在 `config.xml` 中提供开关，可关闭 CSV 输出，只保留 JSON 服务，适用于
不希望额外磁盘 I/O 的环境。

---

## 5. HTTPS 说明

当存在证书文件（`certs/latency_server.crt` + `.key`）时：

- 额外开启 HTTPS 监听，端口 **8881**；
- 证书一般为自签名证书，客户端有两种处理方式：
  - 在测试环境中忽略证书验证；
  - 将该证书导入操作系统 / 运行环境的信任列表。

使用 curl 的示例：

```bash
# HTTP 获取最新延迟
curl "http://127.0.0.1:8880/latency"

# HTTPS（忽略自签名证书告警）
curl -k "https://127.0.0.1:8881/latency"
```

控制接口同样可通过 HTTPS 调用：

```bash
curl -k "https://127.0.0.1:8881/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123"
curl -k "https://127.0.0.1:8881/stop_predict?gmcode=GN00725C040WO"
```

---

## 6. 轮询建议

对于外部荷官端 / 监控系统：

- 建议每 **10 秒** 调用一次 `/latency`；  
- 每次请求都把响应视为“当前已知的最新一行数据”；  
- 若需要完整历史，可自行解析 `log/<YYYY-MM-DD>/...` 下的 CSV 文件。

服务本身 **不提供**：

- 分页
- 按时间范围查询
- 按 `gmcode` 过滤历史

如需上述能力，可在外部系统中基于 CSV 构建。

---

## 7. 错误处理

总体规则：

- 正常操作返回 **HTTP 200**；
- 当必填参数缺失 / 非法（例如 `/start_predict` 未提供 `gmcode` 或 `t0`）时，
  接口会返回非 2xx 状态码，并在 ImageDetector 日志中记录详细原因。

针对 `/latency`：

- 尚无任何记录时：
  - HTTP 200；
  - 响应头包含：`X-Latency-Status: no_record`；
  - Body 为 `{}`；
- 其他内部错误（如读取 CSV 失败、内部异常等）也会写入同一套 pylogger 日志。

客户端逻辑建议：

1. 先确认 HTTP 状态码是否为 2xx；  
2. 对于 `/latency`，再检查头信息 `X-Latency-Status`；  
3. 状态正常且非 `no_record` 时解析 JSON Body。

---

## 8. 快速测试示例

### 8.1 通过 HTTP 启动 / 结束一局

```bash
# 启动预测
curl "http://127.0.0.1:8880/start_predict?gmcode=GN00725C040WO&t0=20251218%20134000.123"

# 停止预测
curl "http://127.0.0.1:8880/stop_predict?gmcode=GN00725C040WO"
```

### 8.2 读取最新延迟（HTTP）

```bash
curl "http://127.0.0.1:8880/latency"
```

### 8.3 读取最新延迟（HTTPS）

```bash
curl -k "https://127.0.0.1:8881/latency"
```

### 8.4 `/latency` 正常响应示例

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

