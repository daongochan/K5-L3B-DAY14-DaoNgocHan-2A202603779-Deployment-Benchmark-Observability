# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích xuất trực tiếp từ các file report thực nghiệm trong `reports/` và `benchmark-results/`.

**Họ tên:** Đào Ngọc Hân — 2A202603779
**Ngày chạy:** 2026-11-26
**Môi trường:** Windows 11 (AMD Ryzen 5 5600H, 7 GB RAM), Python 3.11.17, Docker Desktop 29.7.2 (WSL2 backend: 12 vCPUs / 3.52 GiB RAM)

---

## 1. SLO của agent & Thiết kế Metrics (Exercise 7.1)

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `≤ 500 ms` | Với luồng RAG (`~20 ms` retrieval + `~120–180 ms` LLM inference), ngưỡng `500 ms` đủ phản hồi tức thì cho giao diện chat tương tác mà vẫn hấp thụ được dao động mạng ngắn hạn, đồng thời phát hiện ngay khi hàng đợi bị nghẽn hoặc tail latency lan sang nhóm 5% người dùng. |
| Error rate `/ask` | `≤ 2.0 %` | Upstream LLM thực tế luôn có tỷ lệ lỗi thoáng qua (`~1%` lỗi `503`/`429`); đặt SLO `≤ 2.0%` (error budget `2%`) vừa tránh báo động giả cho lỗi đơn lẻ, vừa bắt kịp sự cố suy giảm diện rộng. |
| Accuracy trên golden dataset | `≥ 85.0 %` (CI) / `100.0 %` (sau khi vá KB) | Đảm bảo mọi thay đổi về prompt, model hoặc kho tri thức RAG không làm tụt chất lượng trả lời hay gây regression trên tập 23 câu hỏi chuẩn trước khi merge/deploy. |

**Ghi chú Instrumentation (`/metrics` — Exercise 7.1):**
- **3 loại Prometheus metric trên agent:**
  - *Counter* (chỉ tăng): `http_requests_total{method="POST",route="/ask",status="200"}`, `llm_tokens_total`, `llm_cost_usd_total`.
  - *Gauge* (tăng/giảm tức thời): `agent_in_flight_requests`, `agent_info{model="mock-llm-small",version="v2"}`.
  - *Histogram* (phân phối theo bucket): `http_request_duration_seconds`, `llm_request_duration_seconds`, và metric mới bổ sung **`agent_question_length_chars`** (`buckets=(20, 50, 100, 200, 500, 1000, 2000)`).
- **Lý do dùng `route.path` (và gán `"unmatched"`) thay vì `request.url.path`:** Nếu gắn trực tiếp đường dẫn URL thô làm label `route`, khi bot quét hàng vạn URL ngẫu nhiên (`/wp-admin`, `/.env`, `/scan-9f8a1b`...) mỗi URL sẽ sinh ra một tổ hợp label mới (**cardinality explosion**), làm bùng nổ hàng triệu time series và gây tràn RAM trên Prometheus.

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2 — `300` requests/lượt)

Số liệu khớp chính xác với `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`:

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (`p95 ≤ 500ms`, `err ≤ 2%`) |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 4.38 | 213.3 | 246.8 | 1701.4 | 0.67% | ✅ PASS |
| 10 | 38.06 | 199.7 | 245.9 | 1702.6 | 0.67% | ✅ PASS |
| 50 | 55.16 | 420.6 | 2856.2 | 3714.3 | 1.00% | ❌ FAIL (`p95 > 500ms`) |
| 100 | 31.55 | 1277.2 | 6931.0 | 8217.4 | 1.00% | ❌ FAIL (`p95 > 500ms`) |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency:
- Ở vùng tải thấp (`concurrency` từ `1` → `10`), RPS tăng gần tuyến tính (`4.38` → `38.06 req/s`, gấp `8.69×`) trong khi `p95` giữ nguyên quanh `~246 ms` vì `uvicorn` async event loop tận dụng hiệu quả thời gian chờ I/O bất đồng bộ (`asyncio.sleep` của bước retrieval và LLM).
- Khi đẩy lên `concurrency = 50` và `100` trên một tiến trình Python đơn lẻ, RPS đạt đỉnh quanh `55.16 req/s` rồi suy giảm xuống `31.55 req/s`, đồng thời `p95` tăng vọt lên `2856.2 ms` và `6931.0 ms`. Nguyên nhân là CPU overhead khi serialize JSON/logging hàng loạt coroutines cùng lúc và tranh chấp socket loopback khiến các request bị dồn ứ trong hàng đợi (theo định luật Little $L = \lambda \times W$: khi thông lượng $\lambda$ chạm trần năng lực phục vụ mà số kết nối đồng thời $L$ tăng gấp đôi thì thời gian chờ $W$ tăng vọt).

### 2.2 Tail latency (`concurrency = 20`, `300` requests/lượt)

Số liệu khớp chính xác với `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`:

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) | SLO (`p95 ≤ 500ms`) |
|---|---:|---:|---:|---|
| `0` | 210.6 | 268.6 | 301.0 | ✅ PASS |
| `0.03` (mặc định) | 262.9 | 450.4 | 1695.7 | ✅ PASS |
| `0.1` | 348.3 | 1699.5 | 1738.1 | ❌ FAIL |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm:** **`p99`** (nhảy vọt gấp **`5.6×`** từ `301.0 ms` lên `1695.7 ms` ngay khi mới có `3%` request chậm ở `MOCK_SLOW_RATE=0.03`) và tiếp theo là **`p95`** (nhảy từ `450.4 ms` lên `1699.5 ms` khi tỷ lệ request chậm tăng lên `10%`, vượt ngưỡng 5% đuôi phân phối).
- **Vì sao tuyệt đối không đặt SLO theo `average`:** Khi `MOCK_SLOW_RATE = 0.1` (cứ 10 người dùng thì có 1 người phải chờ `~1.7 giây`), chỉ số `avg` mới chỉ là **`348.3 ms`** (vẫn thấp hơn nhiều so với `500 ms`!) do bị 90% request nhanh (`~200 ms`) kéo trung bình xuống. Nếu đặt SLO theo `avg < 500 ms`, hệ thống vẫn báo "xanh" trong khi 10% khách hàng thực tế đang gặp trải nghiệm rất tệ. Đặt SLO theo percentile (`p95` và `p99`) giúp phản ánh trung thực trải nghiệm của nhóm người dùng chịu độ trễ xấu nhất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu khớp chính xác với `reports/eval_v1.json`, `reports/eval_v2.json`, và `reports/eval_v2_fixed.json` (tập `golden_dataset.jsonl` gồm `23` câu):

| Chỉ số | Agent v1 (`eval_v1.json`) | Agent v2 (`eval_v2.json`) | Agent v2 sau khi sửa KB (`eval_v2_fixed.json`) |
|---|---:|---:|---:|
| Accuracy | 4.35% (`1/23`) | 91.30% (`21/23`) | **100.00% (`23/23`)** |
| Avg tokens / câu | 56.6 | 109.0 | 113.7 |
| Tổng cost (USD) | \$0.000397 | \$0.000760 | \$0.000790 |
| Cost / câu đúng (USD) | \$0.00039675 | \$0.00003619 | **\$0.00003436** |
| Quality gate | ❌ FAIL (`min_accuracy=0.8`) | ✅ PASS (`min_accuracy=0.8`, `0` regression) | ✅ PASS (`min_accuracy=1.0`, `0` regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Cách đã sửa trong `utils/mock_llm.py` (`KNOWLEDGE_BASE`) |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Bổ sung tài liệu phân biệt API key (chuỗi bí mật cố định, không tự hết hạn) và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn) với từ khóa kích hoạt `["jwt"]`. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Bổ sung tài liệu về Kubernetes HPA (Horizontal Pod Autoscaler scale số pod theo CPU, memory hoặc custom metrics như RPS / hàng đợi) với từ khóa kích hoạt `["hpa", "kubernetes", "autoscal"]`. |

**Nhận xét về trade-off chất lượng / chi phí / latency & CI Quality Gate:**
- **Trade-off RAG (`v1` vs `v2`):** `Agent v2` bổ sung bước tìm kiếm ngữ cảnh (`search_knowledge_base`) rồi ghép tài liệu vào prompt nên số token trung bình mỗi câu tăng khoảng `2×` (`56.6` → `113.7` tokens), tổng chi phí cho 23 câu tăng từ `\$0.000397` lên `\$0.000790` và độ trễ trung vị `p50` tăng nhẹ `~33 ms` (`168.1 ms` → `201.1 ms`). Tuy nhiên, độ chính xác tăng vọt từ `4.35%` lên **`100.0%`**, làm cho chỉ số thực chất là **`Cost / câu đúng` giảm hơn 11.5 lần** (`\$0.00039675` xuống chỉ còn `\$0.00003436` mỗi câu trả lời hữu ích).
- **Chặn merge tự động trong CI (`.github/workflows/eval.yml`):** Script `eval/run_eval.py` kiểm tra đồng thời hai điều kiện `accuracy >= --min-accuracy` và `len(regressions) == 0` (không có câu nào bản cũ đúng mà bản mới sai); nếu vi phạm một trong hai, script kết thúc bằng `raise SystemExit(1)` (`exit code 1`). Trong GitHub Actions (đã cấu hình tại `.github/workflows/eval.yml` chạy ở sự kiện `pull_request`), mã thoát khác `0` sẽ đánh dấu job `eval` **Failed** và khóa nút Merge trên Pull Request khi bật Branch Protection rule.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Phân tích Dashboard (Exercise 7.4)

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có lỗi `503` tại span `chat mock-llm-small` do `exception` upstream): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với cả 4 alert đang **firing**: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời các câu hỏi quan sát trên Grafana & Nginx (Exercise 7.4):**
1. **Khoảng cách giữa `p95` và `avg`:** Khi chạy tải ổn định 30 users trên 2 instances `v2`, truy vấn trực tiếp PromQL ghi nhận `avg = 331.5 ms` trong khi `p95 = 669.2 ms` (và ở cửa sổ chuyển tiếp sau bài tải cao đạt `2.22 s` trên dashboard). Khoảng cách lớn giữa `p95` và `avg` cho thấy phân phối độ trễ bị lệch phải mạnh (*tail latency*): đa số request hoàn tất quanh `~200–220 ms`, nhưng nhóm nhỏ request dính `MOCK_SLOW_RATE` (`+1500 ms`) hoặc chờ hàng đợi kéo đuôi phân vị thứ 95/99 lên cao mà số trung bình cộng không phản ánh hết.
2. **Panel "Requests/s theo instance":** Nginx phân phối lưu lượng xấp xỉ đồng đều giữa 2 instances `172.19.0.4:8000` và `172.19.0.8:8000` (cùng dao động quanh `4–8 req/s` mỗi bên trên biểu đồ; độ lệch nhỏ tức thời là bình thường do tái sử dụng kết nối `keepalive 32` và chu kỳ `resolve` Docker DNS 10 giây).
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`:** Số đo thực tế ghi nhận `input = 299.2 tokens/s` so với `output = 156.5 tokens/s` (lớn hơn `~1.91×`). Ở `agent v2` (RAG), mỗi lượt gọi LLM phải gửi kèm `SYSTEM_PROMPT` + **toàn bộ đoạn văn bản tài liệu truy xuất từ `KNOWLEDGE_BASE`** + câu hỏi vào phần input (`~100–120 tokens`), trong khi câu trả lời sinh ra ở phần output ngắn gọn hơn nhiều (`~40–55 tokens`).
4. **`curl http://localhost:8080/metrics` trả về gì và vì sao:** Trả về **`HTTP/1.1 404 Not Found`** vì file `nginx/nginx.conf` cấu hình `location = /metrics { return 404; }`. Endpoint `/metrics` tiết lộ nhiều thông tin nội bộ nhạy cảm (danh sách route, lưu lượng thực tế, tỷ lệ lỗi, chi phí LLM, tên model/phiên bản) nên chỉ cho phép Prometheus truy cập trực tiếp qua mạng nội bộ Docker (`obs_net` tại `agent:8000/metrics`), tuyệt đối không phơi bày ra cổng public của Reverse Proxy.

### 4.2 Thí nghiệm "phá hệ thống" (Exercise 7.6)

Kết quả kiểm thử unit test trước khi chạy: `promtool test rules /p/alert_rules_test.yml` → **`SUCCESS`**.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| **A** | `MOCK_ERROR_RATE=0.25` (≥ `0.2`) | `AgentHighErrorRate` (`severity="critical"`, giá trị `22.99% > 5%`) | **`~101.8 giây`** *(~40s tích lũy `rate[1m]` vượt 5% + `for: 1m`)* | **Error rate**, **Requests/s theo status code (`503`)**, **LLM calls theo kết quả (`error`)** |
| **B** | `MOCK_SLOW_RATE=0.35` (≥ `0.3`) | `AgentHighLatencyP95` (`severity="warning"`, giá trị `p95 > 1s`) | **`~163.5 giây`** *(~43s tích lũy histogram `[1m]` vượt 1s + `for: 2m`)* | **Latency p95**, **Latency /ask — p50 / p95 / p99** |
| **C** | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`severity="warning"`, giá trị `\$7.41–\$7.65/giờ > \$2/giờ`) | **`~163.5 giây`** *(~43s đẩy `rate[5m] * 3600` vượt `\$2/h` + `for: 2m`)* | **Cost burn rate (USD/giờ)**, **LLM cost (1h)** |
| **D** | `docker pause` 1 instance (`agent-2`) | `AgentInstanceDown` (`severity="critical"`, `up == 0` trên `172.19.0.4:8000`) | **`~35 giây`** *(1 chu kỳ scrape `5s` phát hiện timeout + `for: 30s`)* | **Instances up** (giảm từ `2` về `1`), **Requests/s theo instance** |
| **E** | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không kích hoạt (`∞`) | **Retrieval hit ratio** (mất dữ liệu), **Tokens/s** (giảm), bảng **Phiên bản đang chạy** (`v1`) |

**Phân tích chuyên sâu Thí nghiệm D và Thí nghiệm E:**
- **Ở Thí nghiệm D (`docker pause`):** Dùng `docker pause` thay vì `docker stop` vì `docker stop` rút tên container khỏi Docker DNS làm `dns_sd_configs` xóa luôn target (Prometheus hiểu là giảm số lượng container hợp lệ chứ không phải sập), còn `docker pause` giữ nguyên bản ghi DNS nhưng đóng băng tiến trình khiến scrape thất bại (`up == 0`). Ngoài ra, vài lỗi `504 Gateway Time-out` lúc Nginx chưa kịp loại upstream bị đóng băng xảy ra tại tầng Nginx (`proxy_read_timeout 10s`), chưa từng đi hết vòng đời middleware trong `agent` nên panel *Error rate* của `agent` không đếm các lỗi `504` này — cho thấy production cần giám sát cả metrics ở tầng Load Balancer / Ingress.
- **Ở Thí nghiệm E (`AGENT_VERSION=v1` không làm alert nào firing — cách phát hiện trong production):** Các alert hạ tầng (CPU, RAM, HTTP `5xx`, latency) hoàn toàn "mù" trước lỗi suy thoái chất lượng câu trả lời (*silent quality regression*: agent vẫn trả `200 OK` rất nhanh và rẻ nhưng nội dung sai tới 95%). Để bắt loại sự cố này trong production cần kết hợp 3 lớp:
  1. **Offline Quality Gate trong CI/CD:** Chặn ngay từ Pull Request bằng `run_eval.py` trên `golden_dataset.jsonl` (so sánh accuracy và regression với bản baseline trước khi cho phép deploy).
  2. **Semantic / Domain Metrics & Alerts:** Đặt cảnh báo khi chỉ số nghiệp vụ thay đổi bất thường, ví dụ `rate(agent_retrieval_hits_total{result="hit"}[5m]) == 0` khi đang chạy RAG, độ dài câu trả lời trung bình tụt đột ngột, hoặc tỷ lệ người dùng bấm *thumbs-down* tăng cao.
  3. **Online Eval (LLM-as-a-Judge) & Canary Probes:** Lấy mẫu ngẫu nhiên 5–10% cặp câu hỏi/trả lời thực tế kèm `trace_id` để chấm điểm chất lượng bất đồng bộ và chạy kịch bản câu hỏi chuẩn định kỳ mỗi 5–10 phút trên production.

### 4.3 Debug bằng trace (Exercise 7.5)

Trace chậm nhất trích xuất từ Jaeger (`screenshots/jaeger-slow-trace.png`):

- `trace_id`: `ceec03e1badd4dd1ff7f051c66b25092`
- Tổng thời gian (`POST /ask`): `1903.5 ms` *(hiển thị làm tròn `2.0 s` trên thanh tiêu đề Jaeger; span `agent.run`: `1.8 s`, `agent.retrieve_context`: `97.2 ms`)*
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (`1698.3 ms` — hiển thị `1.7 s` trên Jaeger, chiếm **`89.2%`** tổng thời gian request; chứng minh độ trễ nằm ở bước chờ upstream LLM chứ không phải ở bước retrieval hay xử lý nội bộ).
- Dòng log JSON tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-26T10:07:51.293414+00:00", "level": "INFO", "service": "observable-agent", "instance": "c73e8f055aa5", "event": "llm_call", "trace_id": "ceec03e1badd4dd1ff7f051c66b25092", "span_id": "c5aa4d0419161f7f", "request_id": "7d2d36f95b35", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1698.3}
```

*(Trace lỗi đối chứng trong `screenshots/jaeger-error-trace.png` có `trace_id = ceced40bf7af1479f04c3c86cf3a3dd1`, tổng thời gian `114 ms`, span `chat mock-llm-small` lỗi `503` ở `88.9 ms`, khớp dòng log: `{"ts": "2026-11-26T10:14:34.113478+00:00", "level": "INFO", "service": "observable-agent", "instance": "c6c450f640e7", "event": "llm_error", "trace_id": "ceced40bf7af1479f04c3c86cf3a3dd1", "span_id": "2cc041844155db02", "request_id": "33a4ab8cce6a", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}`).*

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu trích xuất trực tiếp từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`:

### Dòng `Aggregated` (tổng hợp toàn bộ tải Locust)

| Số instance | Tổng Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---:|---|
| **1** | 6153 | 52.87 | 230 | 2000 | 3300 | 63 (`1.02%`) |
| **3** | 6905 | 59.32 | 210 | 1700 | 3000 | 65 (`0.94%`) |

### Riêng dòng endpoint `POST /ask`

| Số instance | Requests `/ask` | RPS `/ask` | Avg (ms) | p50 (ms) | p75 (ms) | p95 (ms) | p99 (ms) | Failures |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **1** | 5584 | 47.98 | 601.15 | 230 | 670 | 2100 | 3400 | 63 (`1.13%`) |
| **3** | 6277 | 53.93 | 400.30 | 220 | 280 | 1700 | 3000 | 65 (`1.04%`) |

**Giải thích kết quả:**
- **Scale từ 1 lên 3 instances CÓ cải thiện rõ rệt vùng nghẽn ứng dụng nhưng `p95` chỉ giảm từ `2000–2100 ms` về `1700 ms` (không thể xuống dưới `500 ms`):**
  1. **Hiệu quả ở tầng ứng dụng:** Khi chỉ có `1` container (`0.5 CPU`), 100 concurrent users tạo ra hiện tượng nghẽn hàng đợi trên event loop làm `Avg` của `/ask` tăng lên `601.15 ms` và `p75` vọt lên `670 ms`. Khi mở rộng lên `3` containers, tải được Nginx chia đều làm `p75` giảm mạnh hơn **2.4 lần** (`670 ms → 280 ms`), `Avg` giảm **33.4%** (`601.15 ms → 400.30 ms`), và tổng `RPS` tăng từ `52.87` lên `59.32 req/s` (chạm sát trần lý thuyết `~60.6 req/s` của 100 Locust users có `wait_time` nghỉ `0.5–2.0s` giữa mỗi lần gửi).
  2. **Nút thắt thật sự nằm ở Upstream LLM (`MOCK_SLOW_RATE = 0.03`):** Trong mô hình gọi API LLM bên ngoài, mỗi request có xác suất cố định bị upstream xử lý chậm (`+1500 ms` → tổng `~1700 ms`) và `~1%` lỗi upstream `503`. Việc nhân bản số container FastAPI chỉ loại bỏ thời gian chờ CPU/queueing tại bản thân tầng agent (kéo `p95` từ `2100 ms` về đúng ngưỡng nền `1700 ms`), chứ không thể rút ngắn thời gian suy luận bên trong dịch vụ LLM hay giảm tỷ lệ lỗi `503` từ nhà cung cấp. Muốn hạ tiếp `p95`, cần áp dụng semantic caching (Redis), streaming token đầu tiên (TTFT), hoặc hedged/fallback sang model dự phòng khi quá timeout.

---

## 6. Kết luận

- **3 bài học cốt lõi rút ra về Benchmark & Observability cho AI Agent:**
  1. **Đừng bao giờ tin vào Latency trung bình (`average`):** Chỉ cần 3–10% request gọi LLM bị tail latency (`~1.7s`), `average` vẫn trông rất đẹp (`~260–348 ms`) trong khi hàng loạt người dùng thực tế phải chờ đợi lâu; mọi SLI/SLO và Alert về tốc độ đều phải đặt trên phân vị **`p95` / `p99`**.
  2. **Hạ tầng "xanh" không đồng nghĩa Agent trả lời đúng:** Thí nghiệm hạ cấp xuống `v1` chứng minh Prometheus/Grafana hạ tầng không thể phát hiện lỗi suy giảm tri thức RAG; bắt buộc phải kết hợp **Offline Eval Quality Gate** trên golden dataset trong CI với **Online Eval** và chỉ số chất lượng đầu ra (`Cost / câu đúng` thay vì chỉ nhìn `Cost / câu`).
  3. **Liên kết chặt 3 trụ cột Metrics → Traces → Logs qua `trace_id`:** Metrics (Grafana/Prometheus) giúp phát hiện nhanh *khi nào* hệ thống vi phạm SLO, Distributed Tracing (OpenTelemetry/Jaeger) chỉ chính xác *span nào* gây chậm (`chat mock-llm-small` chiếm `89.2%`), và JSON Structured Logs chứa cùng `trace_id` cung cấp toàn bộ ngữ cảnh chi tiết của đúng request đó trong vài giây.
- **Các Metric & Alert sẽ bổ sung thêm nếu vận hành hệ thống này cho người dùng thật trên Production:**
  - **Metrics bổ sung:** *Time To First Token (TTFT)* và *Tokens Per Second (TPS)* cho trải nghiệm streaming; tỷ lệ cache hit trên Redis; số lượng request bị chặn bởi Rate Limiter (`429`) và Cost Guard (`402`); chỉ số ở tầng Load Balancer/Ingress (`nginx_http_requests_total` để bắt lỗi `502`/`504` khi container treo); và điểm đánh giá chất lượng trực tuyến (*user feedback score* / *faithfulness score*).
  - **Alerts bổ sung:** Cảnh báo khi `retrieval_hit_ratio` tụt dưới `50%` trong 5 phút (phát hiện hỏng Vector DB / lỗi pipeline RAG như Thí nghiệm E), cảnh báo lỗi `502`/`504` từ phía cổng vào Nginx/probe bên ngoài (blackbox synthetic check), và cảnh báo bất thường khi tỷ lệ trả `401`/`429` tăng đột biến (dấu hiệu bị tấn công dò khóa hoặc DDoS).
