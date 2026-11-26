# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`

Qua phân tích mã nguồn `01-localhost-vs-production/develop/app.py`, có **7 anti-patterns** nghiêm trọng khiến ứng dụng không thể đưa thẳng lên môi trường production:

1. **Hardcode secrets & thông tin nhạy cảm trực tiếp trong code (`app.py`, dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - **Rủi ro:** Khi push code lên Git repository, bot quét tự động sẽ thu thập key trong vài giây dẫn đến mất quyền truy cập hoặc phát sinh hóa đơn LLM/cloud ngoài ý muốn; kể cả xóa ở commit sau thì secret vẫn nằm trong lịch sử Git.
2. **Cấu hình gán cứng, thiếu quản lý theo môi trường (`app.py`, dòng 21–22):**
   - `DEBUG = True` và `MAX_TOKENS = 500` được gán cố định trong code thay vì đọc từ biến môi trường (vi phạm nguyên lý **III. Config** của 12-Factor App). Muốn đổi cấu hình giữa `dev`, `staging`, `production` buộc phải sửa code và build lại.
3. **Dùng `print()` thay vì Structured Logging và làm lộ secret ra log (`app.py`, dòng 33–34, 38, 48):**
   - Dòng 34 `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` in thẳng API key ra `stdout`, khiến secret bị lưu lại trong hệ thống tập trung log (CloudWatch, Loki, Datadog).
   - Log dạng chuỗi tự do thiếu `timestamp` chuẩn UTC, `level` (`INFO`/`WARNING`/`ERROR`) và định dạng JSON nên rất khó truy vấn/lọc tự động khi có hàng nghìn dòng log mỗi phút.
4. **Thiếu Health Check (`/health`) và Readiness Probe (`/ready`) (`app.py`, dòng 42–43):**
   - Không có endpoint kiểm tra sức khỏe khiến nền tảng cloud/orchestrator (Railway, Render, Kubernetes) không biết khi nào tiến trình bị treo để tự động restart (*liveness*), cũng như Load Balancer không biết khi nào instance đã khởi tạo xong tài nguyên để điều phối traffic vào (*readiness*).
5. **Bind cứng `host="localhost"` và `port=8000` (`app.py`, dòng 49–52):**
   - `host="localhost"` (`127.0.0.1`) chỉ nhận kết nối nội bộ loopback; khi đóng gói vào Docker container hoặc chạy sau Reverse Proxy trên cloud, mọi request từ bên ngoài container sẽ bị từ chối kết nối (cần bind `0.0.0.0`).
   - `port=8000` cố định làm ứng dụng lỗi khi cổng `8000` trên máy đang bận hoặc khi deploy lên Railway/Render/Cloud Run (nơi cổng thực tế được cấp động qua biến môi trường `PORT`).
6. **Bật cứng `reload=True` khi khởi chạy Uvicorn (`app.py`, dòng 53):**
   - Chế độ file-watcher auto-reload chỉ dành cho môi trường phát triển; bật trên production gây tốn CPU/memory, phát sinh tiến trình con theo dõi file và có thể làm gián đoạn request không mong muốn.
7. **Không xử lý Graceful Shutdown (`SIGTERM`) và vòng đời ứng dụng (`lifespan`):**
   - Khi deploy bản mới (rolling update) hoặc scale down, hệ thống gửi tín hiệu `SIGTERM`. Nếu ứng dụng không quản lý lifecycle để ngừng nhận request mới, đợi các request đang xử lý dở (in-flight) hoàn tất và đóng kết nối DB/cache êm ái, người dùng sẽ gặp lỗi ngắt kết nối đột ngột (`502`/`504`).

---

### Exercise 1.2: Chạy và kiểm thử phiên bản Basic (`develop`)

Khởi chạy server `01-localhost-vs-production/develop` (lưu ý bản `develop` nhận tham số `question` qua **query string** thay vì JSON body):

1. **Gọi đúng qua query string (`POST /ask?question=Hello`) → `200 OK`:**
   ```http
   HTTP/1.1 200 OK
   date: Thu, 26 Nov 2026 07:32:02 GMT
   server: uvicorn
   content-length: 95
   content-type: application/json

   {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
   ```
   Đồng thời log trên terminal của server in lộ trực tiếp API key ra `stdout`:
   ```text
   [DEBUG] Got question: Hello
   [DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
   [DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
   ```

2. **Gọi bằng JSON body (`POST /ask -d '{"question":"Hello"}'`) → `422 Unprocessable Entity`:**
   ```http
   HTTP/1.1 422 Unprocessable Entity
   content-type: application/json

   {"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
   ```

3. **Kiểm tra `/health` (`GET /health`) → `404 Not Found`:**
   ```http
   HTTP/1.1 404 Not Found
   content-type: application/json

   {"detail":"Not Found"}
   ```

---

### Exercise 1.3: So sánh Basic (`develop`) vs Advanced (`production`)

#### Kết quả chạy kiểm thử bản `production`

Khởi chạy `01-localhost-vs-production/production/app.py` (đọc cấu hình từ biến môi trường, hỗ trợ đổi `PORT` linh hoạt không cần sửa code):

- **`GET /health` → `200 OK`:**
  ```http
  HTTP/1.1 200 OK
  content-type: application/json

  {"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:32:08.050510+00:00"}
  ```
- **`GET /ready` → `200 OK`:**
  ```http
  HTTP/1.1 200 OK
  content-type: application/json

  {"ready":true}
  ```
- **`POST /ask` (JSON body `{"question": "Hello"}`) → `200 OK`:**
  ```http
  HTTP/1.1 200 OK
  content-type: application/json

  {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
  ```

#### Bảng so sánh chi tiết

| Feature | Basic (`develop`) | Advanced (`production`) | Tại sao quan trọng trong Production? |
| :--- | :--- | :--- | :--- |
| **Config & Secrets** | Hardcode trực tiếp trong `app.py` (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`) | Đọc tập trung qua `os.getenv()` trong `config.py` (`Settings` + `. validate()`), kèm `.env.example` | Tách biệt hoàn toàn code và cấu hình (12-Factor); tránh lộ secret trên Git, cho phép dùng chung 1 image trên dev/staging/prod và fail-fast nếu thiếu biến bắt buộc (`AGENT_API_KEY` ở production). |
| **Network Binding & Port** | Cố định `host="localhost"`, `port=8000`, `reload=True` | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ `PORT`), `reload=settings.debug` | Container Docker và các nền tảng PaaS (Railway, Render, Cloud Run) yêu cầu lắng nghe trên `0.0.0.0` và cổng động `PORT`; tắt `reload` giúp tiết kiệm tài nguyên và chạy ổn định. |
| **Health & Readiness Checks** | ❌ Không có (`GET /health` trả `404`) | ✅ Có `GET /health` (liveness + uptime) và `GET /ready` (readiness trả `503` khi chưa sẵn sàng) | Giúp nền tảng tự động phát hiện và khởi động lại container bị treo (`/health`), đồng thời chỉ điều phối traffic vào instance khi đã nạp xong tài nguyên (`/ready`), đảm bảo zero-downtime deploy. |
| **Logging** | `print()` tự do và in cả `OPENAI_API_KEY` ra màn hình | `logging` chuẩn hóa cấu trúc JSON (`json.dumps`), chỉ ghi metadata (`question_length`, `client_ip`), không ghi secret | Log JSON giúp các hệ thống giám sát (Grafana Loki, Datadog, ELK) parse, đánh chỉ mục, tìm kiếm và cảnh báo tự động mà không làm rò rỉ dữ liệu nhạy cảm. |
| **Shutdown & Lifecycle** | Tắt đột ngột khi nhận tín hiệu dừng, không có lifecycle hook | Quản lý vòng đời qua `@asynccontextmanager def lifespan(app)` kết hợp `signal.signal(signal.SIGTERM, handle_sigterm)` | Khi scale down hoặc rolling deploy, container nhận `SIGTERM`: ứng dụng đặt `is_ready = False` để ngắt nhận traffic mới và chờ xử lý nốt các request đang chạy trước khi thoát êm ái. |
| **CORS & Input Handling** | Không cấu hình CORS; nhận `question` qua query param | Cấu hình `CORSMiddleware` từ `ALLOWED_ORIGINS`; nhận JSON body và trả mã lỗi `422` rõ ràng khi thiếu `question` | Kiểm soát chặt chẽ domain frontend nào được phép gọi API từ trình duyệt và chuẩn hóa giao thức giao tiếp cho client. |

#### Đối chiếu mã nguồn đã khắc phục (`develop` → `production`)

1. **Quản lý Secret & Config:**
   - Bản `develop/app.py` (dòng 17):
     ```python
     OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"
     ```
   - Bản `production/config.py` (dòng 27, 42–43):
     ```python
     openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
     # ...
     if not self.api_key and self.environment == "production":
         raise ValueError("AGENT_API_KEY must be set in production!")
     ```
2. **Cấu hình Host/Port & Reload khi chạy Uvicorn:**
   - Bản `develop/app.py` (dòng 49–54):
     ```python
     uvicorn.run("app:app", host="localhost", port=8000, reload=True)
     ```
   - Bản `production/app.py` (dòng 194–199):
     ```python
     uvicorn.run(
         "app:app" if settings.debug else app,
         host=settings.host,    # 0.0.0.0
         port=settings.port,    # đọc từ biến môi trường PORT
         reload=settings.debug, # chỉ bật khi DEBUG=true
     )
     ```

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` — bản phân phối Python 3.11 đầy đủ trên nền Debian, đi kèm nhiều thư viện hệ thống và công cụ biên dịch (dung lượng giải nén lớn ~1.67 GB).
2. **Working directory là gì?**
   - `/app` (đặt qua chỉ thị `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối bên trong thư mục `/app` của container.
3. **Tại sao `COPY 02-docker/develop/requirements.txt .` và `RUN pip install ...` phải đặt TRƯỚC khi copy mã nguồn (`app.py`)?**
   - Để tối ưu **Docker layer cache**: mỗi chỉ thị trong `Dockerfile` tạo một layer bất biến; khi một layer thay đổi thì toàn bộ các layer đứng sau nó đều bị vô hiệu hóa cache (cache invalidation) và phải chạy lại.
   - Trong quá trình phát triển, `app.py` thay đổi liên tục còn `requirements.txt` ít khi đổi. Đặt `COPY requirements.txt` và `RUN pip install` lên trước giúp Docker tái sử dụng nguyên layer dependencies từ cache mỗi lần sửa code, rút ngắn thời gian build từ hàng chục giây xuống chưa đầy 1 giây. *(Lưu ý: cờ `--no-cache-dir` của `pip` chỉ tắt bộ đệm gói tải về của pip để giảm kích thước layer, không tắt layer cache của Docker).*
4. **`CMD` và `ENTRYPOINT` khác nhau thế nào?**
   - **`ENTRYPOINT`** cố định chương trình thực thi chính của container (biến container hoạt động như một file thực thi); mọi đối số truyền thêm ở cuối lệnh `docker run <image> <args>` sẽ được nối vào làm tham số cho `ENTRYPOINT` (muốn ghi đè phải chỉ định rõ `--entrypoint`).
   - **`CMD`** khai báo lệnh chạy mặc định (hoặc danh sách tham số mặc định cho `ENTRYPOINT`) và sẽ bị **ghi đè hoàn toàn** nếu người dùng truyền lệnh khác khi chạy container (ví dụ `docker run -it my-agent:develop sh`).

---

### Exercise 2.2: Build và chạy container `my-agent:develop`

Build từ thư mục gốc repository và chạy thử container:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name cp2-dev-test -p 8000:8000 my-agent:develop
```

- **Kiểm tra `GET http://127.0.0.1:8000/health`:**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 07:46:08 GMT
  server: uvicorn
  content-length: 53
  content-type: application/json

  {"status":"ok","uptime_seconds":1.2,"container":true}
  ```
- **Kiểm tra `POST "http://127.0.0.1:8000/ask?question=What%20is%20Docker%3F"`:**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 07:46:08 GMT
  server: uvicorn
  content-length: 103
  content-type: application/json

  {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
  ```
- **Log từ `docker logs cp2-dev-test`:**
  ```text
  INFO:     Started server process [1]
  INFO:     Waiting for application startup.
  INFO:     Application startup complete.
  INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
  INFO:     172.17.0.1:43836 - "GET /health HTTP/1.1" 200 OK
  INFO:     172.17.0.1:43842 - "POST /ask?question=What%20is%20Docker%3F HTTP/1.1" 200 OK
  ```

---

### Exercise 2.3: Multi-stage Build (`02-docker/production/Dockerfile`) & So sánh kích thước

#### Phân tích hai giai đoạn (Stages)

- **Stage 1 — `builder` (`FROM python:3.11-slim AS builder`):**
  - Cài đặt các gói biên dịch hệ thống (`gcc`, `libpq-dev`) và chạy `pip install --no-cache-dir --user -r requirements.txt` để biên dịch/cài đặt toàn bộ Python packages vào `/root/.local`. Stage này chỉ dùng lúc build, **không** đưa vào image cuối.
- **Stage 2 — `runtime` (`FROM python:3.11-slim AS runtime`):**
  - Khởi đầu từ một image `python:3.11-slim` sạch hoàn toàn, tạo tài khoản non-root `appuser`, chỉ chép thư mục thư viện đã cài (`COPY --from=builder /root/.local /home/appuser/.local`) cùng mã nguồn thực thi (`main.py`, `utils/mock_llm.py`), thiết lập `HEALTHCHECK` và khởi chạy `uvicorn` với 2 workers dưới quyền `appuser`.
- **Tại sao image nhỏ hơn và tốt hơn cho production?**
  1. Đổi base image từ `python:3.11` (full Debian) sang `python:3.11-slim` (chỉ giữ các gói tối thiểu chạy Python).
  2. Toàn bộ trình biên dịch nặng nề (`gcc`, `cpp`, `libpq-dev`, C headers, build artifacts) bị bỏ lại ở Stage `builder`, không xuất hiện trong image `runtime`.
  3. Giảm mạnh **bề mặt tấn công (attack surface)**: kẻ tấn công dù khai thác được lỗ hổng ứng dụng cũng chỉ ở quyền user thường (`appuser`) và không có sẵn compiler/build tools trong container; đồng thời kéo image lên cloud nhanh hơn đáng kể.

#### Kết quả đo dung lượng thực tế (`docker images my-agent`)

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:advanced   c5caf4608d22        240MB         57.4MB
my-agent:develop    d899c19cbbb0       1.67GB          426MB
```

- **Develop (`my-agent:develop`):** `1,670 MB` (`1.67 GB`) Disk Usage · `426 MB` (`426,319,990` bytes) Content Size.
- **Production (`my-agent:advanced`):** `240 MB` Disk Usage · `57.4 MB` (`57,409,167` bytes) Content Size.
- **Chênh lệch (Mức giảm):**
  - Theo **Disk Usage**: giảm `1,430 MB` — tương đương giảm **85.63%**.
  - Theo **Content Size (OCI image)**: giảm `368.9 MB` — tương đương giảm **86.53%**.

---

### Exercise 2.4: Docker Compose Stack (`02-docker/production/docker-compose.yml`)

#### Sơ đồ kiến trúc (Architecture Diagram)

```text
                        Host / Client
                              │
                   HTTP :80   │  (HTTPS :443)
                              ▼
       ┌──────────────── Docker Bridge Network: internal ────────────────┐
       │                                                                 │
       │   ┌─────────────────────────────────────────────────────────┐   │
       │   │  nginx (nginx:alpine)                                   │   │
       │   │  - Reverse Proxy & Rate Limit (10 req/s, burst 20)      │   │
       │   │  - Security Headers (X-Frame-Options, nosniff, XSS)     │   │
       │   └────────────────────────────┬────────────────────────────┘   │
       │                                │ proxy_pass http://agent:8000   │
       │                                ▼                                │
       │   ┌─────────────────────────────────────────────────────────┐   │
       │   │  agent (FastAPI — uvicorn main:app --workers 2)         │   │
       │   │  - Không mở port trực tiếp ra host (chỉ nghe 8000 nội bộ)│  │
       │   └──────────────┬───────────────────────────┬──────────────┘   │
       │                  │                           │                  │
       │  REDIS_URL       │                           │ QDRANT_URL       │
       │  redis:6379/0    ▼                           ▼ qdrant:6333      │
       │   ┌──────────────────────────┐   ┌──────────────────────────┐   │
       │   │  redis (redis:7-alpine)  │   │  qdrant (v1.9.0)         │   │
       │   │  Volume: redis_data      │   │  Volume: qdrant_data     │   │
       │   └──────────────────────────┘   └──────────────────────────┘   │
       └─────────────────────────────────────────────────────────────────┘
```

#### Cơ chế phối hợp giữa các Services

1. **4 services được khởi chạy:** `redis` (cache & rate limit), `qdrant` (vector database), `agent` (FastAPI backend), và `nginx` (reverse proxy).
2. **Thứ tự khởi động an toàn:** `agent` khai báo `depends_on` với `condition: service_healthy` tới cả `redis` (`redis-cli ping`) và `qdrant` (TCP check cổng `6333`), nên `agent` chỉ bật sau khi cả hai dịch vụ dữ liệu đã sẵn sàng.
3. **Giao tiếp mạng cô lập (`internal` bridge network):** Các container phân giải tên nhau trực tiếp qua Docker DNS nội bộ (`http://agent:8000`, `redis://redis:6379/0`, `http://qdrant:6333`). Chỉ duy nhất `nginx` mở cổng `80`/`443` ra máy host; `agent`, `redis`, `qdrant` hoàn toàn ẩn khỏi truy cập trực tiếp từ bên ngoài.

#### Kết quả chạy thực tế qua Nginx (`docker compose -p k5-day14-part2`)

- **Trạng thái các container (`docker compose -p k5-day14-part2 ps`):**
  ```text
  NAME                      IMAGE                  SERVICE   STATUS
  k5-day14-part2-agent-1    k5-day14-part2-agent   agent     Up (healthy)   8000/tcp
  k5-day14-part2-nginx-1    nginx:alpine           nginx     Up             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
  k5-day14-part2-qdrant-1   qdrant/qdrant:v1.9.0   qdrant    Up (healthy)   6333-6334/tcp
  k5-day14-part2-redis-1    redis:7-alpine         redis     Up (healthy)   6379/tcp
  ```
- **Gọi `GET http://localhost/health` qua Nginx (Port 80):**
  ```http
  HTTP/1.1 200 OK
  Server: nginx
  Content-Type: application/json
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  X-XSS-Protection: 1; mode=block

  {"status":"ok","uptime_seconds":2.2,"version":"2.0.0","timestamp":"2026-11-26T07:53:39.772547"}
  ```
- **Gọi `POST http://localhost/ask` qua Nginx (`{"question": "Explain microservices"}`):**
  ```http
  HTTP/1.1 200 OK
  Server: nginx
  Content-Type: application/json
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  X-XSS-Protection: 1; mode=block

  {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
  ```
- **Structured JSON log ghi nhận trên `agent-1`:**
  ```json
  {"time":"2026-11-26 07:53:40,086","level":"INFO","msg":"{\"event\": \"request\", \"q_len\": 21}"}
  ```
  *(Sau khi kiểm thử đã chạy `docker compose -p k5-day14-part2 down -v` để giải phóng cổng 80).*

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway Deployment (Agent Part 6 + Redis)

- **Nền tảng triển khai:** Railway (`k5-day14-production-agent` gồm 2 services: `agent` build từ multi-stage `Dockerfile` và `Redis` liên kết qua biến tham chiếu `${{Redis.REDIS_URL}}`).
- **Public URL:** https://agent-production-143225b4.up.railway.app
- **Chi tiết triển khai & biến môi trường:** Xem [DEPLOYMENT.md](DEPLOYMENT.md).
- **Ảnh chụp bằng chứng:**
  - Dashboard tổng quan (`agent` + `Redis`): [screenshots/dashboard.png](screenshots/dashboard.png)
  - Trạng thái service đang chạy & logs: [screenshots/running.png](screenshots/running.png)
  - Kết quả kiểm thử API từ bên ngoài: [screenshots/test.png](screenshots/test.png)

#### Kết quả chạy 4 lệnh tự kiểm tra CP6 (không lộ API key)

```text
$ BASE="https://agent-production-143225b4.up.railway.app"
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # -> 200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # -> 200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # -> 401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # -> 200
```

Phản hồi JSON thực tế từ cloud:
- `GET /health`: `{"status":"ok","uptime_seconds":47.23,"environment":"production","timestamp":"2026-11-26T08:58:46.669438+00:00"}`
- `GET /ready`: `{"status":"ready","redis":"ok"}`
- `POST /ask` (có `X-API-Key` hợp lệ): `{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"input_tokens":2,"output_tokens":30,"cost_usd":1.83e-05}}`

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Lý do có sự khác biệt |
| :--- | :--- | :--- | :--- |
| **Phạm vi cấu hình** | **Config-as-Code cho 1 service đơn lẻ** (`[build]`, `[deploy]`). Các dịch vụ phụ trợ như `Redis` được tạo qua Dashboard/CLI ở cấp Project. | **Infrastructure-as-Code (Blueprint) đa dịch vụ**: khai báo toàn bộ kiến trúc (`type: web`, `type: redis`, persistent `disk`, `region`, `plan`) trong cùng 1 file YAML. | Railway hướng tới trải nghiệm triển khai nhanh theo từng thư mục/service linh hoạt trên Project Canvas, còn Render Blueprint hướng tới đồng bộ nguyên trạng toàn bộ hạ tầng từ Git giống Terraform thu nhỏ. |
| **Quản lý Biến môi trường & Secrets** | Không khai báo danh sách `envVars` hay secret trong `railway.toml`; mọi biến và tham chiếu `${{Redis.REDIS_URL}}` được quản lý tách biệt trên Railway Dashboard/CLI. | Khai báo tường minh mục `envVars` ngay trong file: biến thường ghi `value`, còn secret dùng `sync: false` (nhập tay trên UI) hoặc `generateValue: true` (Render tự sinh ngẫu nhiên). | Render cần biết trước schema toàn bộ biến môi trường ngay lúc khởi tạo Blueprint từ GitHub để nhắc người dùng điền các trường `sync: false` trước lần deploy đầu tiên. |
| **Cơ chế Build & Khởi chạy** | Chọn `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"` tự nhận diện ngôn ngữ) và `startCommand` / `CMD` của Dockerfile đọc `$PORT`. | Chọn `runtime: docker` hoặc `runtime: python` (kèm `buildCommand` + `startCommand`), chỉ định rõ `plan` (`free`/`starter`) và `region` (`singapore`). | Railway tự động hóa tối đa việc suy luận cách build (zero-config), trong khi Render yêu cầu định nghĩa tường minh loại runtime, gói tài nguyên và vùng địa lý để cấp phát VM cố định. |
| **Health Check & Tự phục hồi** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, kèm chính sách `restartPolicyType = "ON_FAILURE"` và `restartPolicyMaxRetries = 3`. | `healthCheckPath: /health` tích hợp vào vòng đời zero-downtime deploy (bản mới phải trả `200` ở `/health` thì Render mới chuyển traffic từ bản cũ sang). | Cả hai đều dùng `/health` để đảm bảo độ tin cậy, nhưng Railway cho phép tinh chỉnh trực tiếp chính sách retry khi tiến trình crash ngay trong file cấu hình. |

---

### Exercise 3.3: Mô tả Pipeline CI/CD trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

1. Khi có code mới đẩy lên nhánh `main`, **Google Cloud Build** (`cloudbuild.yaml`) kích hoạt bước **`test`** trên container `python:3.11-slim` để cài dependencies và chạy `pytest tests/`; nếu bất kỳ test nào lỗi, toàn bộ pipeline dừng ngay để ngăn code hỏng lên production.
2. Khi test đạt (`waitFor: [test]`), bước **`build`** dùng `gcr.io/cloud-builders/docker` đóng gói Docker image gắn hai tag (`$COMMIT_SHA` để truy vết phiên bản và `latest`), đồng thời tận dụng `--cache-from` từ image `latest` cũ để tăng tốc build, rồi bước **`push`** đẩy toàn bộ image tags lên Google Container Registry.
3. Cuối cùng, bước **`deploy`** (`waitFor: [push]`) gọi `gcloud run deploy ai-agent` đưa đúng image `:$COMMIT_SHA` lên **Cloud Run** tại vùng `asia-southeast1` với giới hạn tài nguyên (`1 CPU`, `512Mi` RAM, timeout `60s`) và tiêm secret trực tiếp từ **Google Secret Manager** (`--set-secrets=OPENAI_API_KEY=openai-key:latest`) thay vì lộ trong repo.
4. Song song đó, file đặc tả Knative **`service.yaml`** chuẩn hóa vận hành dưới dạng IaC: giữ tối thiểu `minScale: "1"` (tránh cold start), mở rộng tự động tới `maxScale: "10"` với `containerConcurrency: 80` requests/instance, và tách riêng `startupProbe` (`/ready`) với `livenessProbe` (`/health`) để tự phục hồi an toàn.

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

#### Phân tích mã nguồn

1. **API key được kiểm tra ở đâu?**
   - Trong FastAPI dependency `verify_api_key(api_key: str = Security(api_key_header))` (`app.py`, dòng 39–54) đọc header `X-API-Key` (`APIKeyHeader(name="X-API-Key", auto_error=False)`). Dependency này được gắn vào endpoint nhạy cảm `@app.post("/ask")` thông qua `_key: str = Depends(verify_api_key)` (dòng 70), trong khi `/` và `/health` được giữ public để nền tảng cloud gọi health check.
2. **Điều gì xảy ra khi thiếu key hoặc sai key?**
   - **Thiếu header `X-API-Key`:** trả về **`401 Unauthorized`** (`detail: "Missing API key. Include header: X-API-Key: <your-key>"`). *(Nhờ đặt `auto_error=False` nên FastAPI không tự trả `403`/`422` mặc định mà đi vào nhánh trả `401` rõ ràng).*
   - **Sai giá trị key (`api_key != API_KEY`):** trả về **`403 Forbidden`** (`detail: "Invalid API key."`).
3. **Làm thế nào để xoay vòng khóa (Key Rotation) không gây gián đoạn (zero-downtime)?**
   - Trong code cơ bản hiện tại, `API_KEY` chỉ giữ một chuỗi đơn đọc lúc khởi động (`os.getenv("AGENT_API_KEY")`), nên nếu đổi key ngay thì các client chưa kịp cập nhật sẽ lập tức bị lỗi `403`.
   - **Giải pháp zero-downtime:** Hỗ trợ danh sách nhiều key hợp lệ đồng thời (ví dụ `AGENT_API_KEYS="key_new,key_old"` tách thành tập hợp hoặc lưu bản băm SHA-256 kèm thời điểm hết hạn trong Redis/DB, kết hợp `secrets.compare_digest()` chống timing attack). Quy trình: *(1)* Thêm `key_new` song song với `key_old` → *(2)* Cập nhật `key_new` cho toàn bộ client → *(3)* Theo dõi log thấy không còn traffic dùng `key_old` thì xóa `key_old`.

#### Kết quả kiểm thử `curl -i` (`AGENT_API_KEY=secret-key-123`)

- **Không gửi API key (`401 Unauthorized`):**
  ```http
  HTTP/1.1 401 Unauthorized
  date: Thu, 26 Nov 2026 08:08:31 GMT
  server: uvicorn
  content-length: 67
  content-type: application/json

  {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
  ```
- **Gửi sai API key (`403 Forbidden`):**
  ```http
  HTTP/1.1 403 Forbidden
  date: Thu, 26 Nov 2026 08:08:31 GMT
  server: uvicorn
  content-length: 29
  content-type: application/json

  {"detail":"Invalid API key."}
  ```
- **Gửi đúng API key `X-API-Key: secret-key-123` (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:08:31 GMT
  server: uvicorn
  content-length: 145
  content-type: application/json

  {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
  ```

---

### Exercise 4.2: JWT Authentication (`04-api-gateway/production/auth.py` & `app.py`)

#### Luồng xác thực JWT (Stateless Auth)

1. Client đăng nhập tại `POST /auth/token` với `username` và `password` (`student` / `demo123`).
2. Hàm `authenticate_user()` đối chiếu thông tin; nếu hợp lệ, `create_token()` đóng gói payload gồm `sub` (username), `role` (`"user"` hoặc `"admin"`), `iat` và `exp` (hết hạn sau 60 phút), rồi ký số bằng thuật toán `HS256` với `JWT_SECRET`.
3. Ở mỗi request tới `POST /ask`, client gửi header `Authorization: Bearer <token>`. Dependency `verify_token()` xác minh chữ ký và hạn `exp` trực tiếp trên CPU mà không cần tra cứu lại database: thiếu token → `401`, hết hạn → `401`, chữ ký không hợp lệ → `403`.

#### Kết quả kiểm thử `curl -i` (đã che token)

- **Gọi `POST /ask` không có Bearer token (`401 Unauthorized`):**
  ```http
  HTTP/1.1 401 Unauthorized
  date: Thu, 26 Nov 2026 08:08:35 GMT
  www-authenticate: Bearer
  content-length: 76
  content-type: application/json
  x-content-type-options: nosniff
  x-frame-options: DENY
  x-xss-protection: 1; mode=block
  referrer-policy: strict-origin-when-cross-origin

  {"detail":"Authentication required. Include: Authorization: Bearer <token>"}
  ```
- **Lấy token tại `POST /auth/token` với tài khoản `student` (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:08:35 GMT
  content-length: 307
  content-type: application/json
  x-content-type-options: nosniff
  x-frame-options: DENY

  {"access_token":"<REDACTED_JWT_TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <REDACTED_PREFIX>..."}
  ```
- **Gọi `POST /ask` kèm `Authorization: Bearer <REDACTED_JWT_TOKEN>` (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:08:35 GMT
  content-length: 187
  content-type: application/json
  x-content-type-options: nosniff
  x-frame-options: DENY
  x-xss-protection: 1; mode=block
  referrer-policy: strict-origin-when-cross-origin

  {"question":"Test 1","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
  ```

---

### Exercise 4.3: Rate Limiting (`04-api-gateway/production/rate_limiter.py`)

#### Phân tích thuật toán & cấu hình

1. **Algorithm nào được dùng?**
   - **Sliding Window** (cài đặt dưới dạng *Sliding Window Log* bằng `collections.deque` lưu danh sách các mốc thời gian `timestamp` của từng request theo từng `user_id`). Mỗi khi có request mới ở thời điểm `now`, hệ thống loại bỏ các timestamp cũ hơn `now - 60` ở đầu hàng đợi (`window.popleft()`), sau đó đếm số phần tử còn lại trong cửa sổ 60 giây trượt liên tục.
2. **Hạn mức (Limit) là bao nhiêu requests/minute?**
   - Role **`user`** (`student`): **`10` requests / 60 giây** (`rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)`).
   - Role **`admin`** (`teacher`): **`100` requests / 60 giây** (`rate_limiter_admin = RateLimiter(max_requests=100, window_seconds=60)`).
3. **Làm sao nâng hạn mức hoặc bypass limit cho `admin`?**
   - Trong `production/app.py` (dòng 141), sau khi `verify_token` giải mã claim `role` từ JWT, ứng dụng chọn bộ giới hạn theo vai trò: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`. Nếu muốn bypass hoàn toàn cho `admin`, chỉ cần kiểm tra điều kiện `if role != "admin": rate_limiter_user.check(username)` (tuy nhiên trong thực tế vẫn nên đặt một ngưỡng an toàn cao như `100–1000 req/min` cho `admin` để tránh lỗi vòng lặp vô hạn làm sập dịch vụ).

#### Kết quả vòng lặp 20 requests liên tiếp với token `student`

Các request từ `#01` đến `#10` trả về `HTTP 200`, bắt đầu từ **request `#11` trở đi** bị chặn với mã **`429 Too Many Requests`**:

```text
Request #01 -> HTTP 200 (requests_remaining: 9)
Request #02 -> HTTP 200
Request #03 -> HTTP 200
Request #04 -> HTTP 200
Request #05 -> HTTP 200
Request #06 -> HTTP 200
Request #07 -> HTTP 200
Request #08 -> HTTP 200
Request #09 -> HTTP 200
Request #10 -> HTTP 200
Request #11..#20 -> HTTP 429
```

Output đầy đủ `curl -i` tại **Request `#11`** (`429 Too Many Requests`):

```http
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 08:08:37 GMT
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795680578
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

---

### Exercise 4.4: Thiết kế & Triển khai Cost Guard

#### 1. Cơ chế hoạt động trong `production/cost_guard.py` và cách đưa lên Redis

- Trong bản mẫu `production/cost_guard.py`, `CostGuard` quy đổi lượng `input_tokens` (`$0.00015 / 1K`) và `output_tokens` (`$0.0006 / 1K`) ra USD, kiểm tra 2 tầng trước khi gọi LLM:
  1. Ngân sách toàn cục (`global_daily_budget_usd = $10/ngày`) → vượt thì trả `503 Service Unavailable`.
  2. Ngân sách cá nhân (`daily_budget_usd = $1/ngày`) → cảnh báo log `WARNING` khi chạm `80%`, và chặn bằng **`402 Payment Required`** khi đạt `100%`.
- **Triển khai chuẩn Production bằng Redis (Stateless):**
  - Bản lưu trên RAM (`self._records`) sẽ mất dữ liệu khi container khởi động lại và không đồng bộ được giữa nhiều worker/instance.
  - Khi đưa lên Redis (áp dụng cho ngân sách ngày `YYYY-MM-DD` hoặc tháng `YYYY-MM`):
    1. Tạo khóa định danh theo chu kỳ, ví dụ `budget:{user_id}:{YYYY-MM}` (hoặc khóa toàn cục `cost:daily:{YYYY-MM-DD}`).
    2. **Trước khi gọi LLM (`check_budget`):** Đọc tổng tiền hiện tại `current = float(r.get(key) or 0.0)`. Nếu `current + estimated_cost > budget_limit` (hoặc `current >= budget_limit`), lập tức `raise HTTPException(status_code=402, detail="Budget exceeded")`.
    3. **Sau khi gọi LLM (`record_cost`):** Tính chi phí thực tế từ `input_tokens` và `output_tokens`, cộng dồn nguyên tử trên Redis bằng `r.incrbyfloat(key, actual_cost)` và đặt TTL tự dọn dẹp bằng `r.expire(key, 32 * 86400)` (cho chu kỳ tháng) hoặc `2 * 86400` (cho chu kỳ ngày).

#### 2. Tại sao cần đồng thời cả Rate Limiting (`429`) LẪN Cost Guard (`402`)?

- **Rate Limiting bảo vệ tốc độ & hạ tầng (ngắn hạn — mỗi phút):** Ngăn chặn burst traffic / DDoS làm nghẽn CPU/worker, treo event loop hoặc vượt hạn mức RPM của nhà cung cấp LLM — ngay cả khi mỗi câu hỏi rất ngắn và tốn ít tiền.
- **Cost Guard bảo vệ tài chính (dài hạn — mỗi ngày/tháng):** Một người dùng hoặc bot hoàn toàn có thể gửi đều đặn **9 requests/phút** (luôn hợp lệ dưới ngưỡng `10 req/phút` của Rate Limiter), nhưng mỗi request truyền prompt dài hàng chục nghìn token xuyên suốt 24 giờ (`~12,960 requests/ngày`), gây thiệt hại hàng trăm USD nếu không có trần ngân sách `402`. Ngược lại, nếu chỉ có Cost Guard mà thiếu Rate Limiting, kẻ tấn công có thể bắn 500 requests đồng thời trong 1 giây trước khi request đầu tiên kịp trả về để cộng chi phí vào Redis, làm lố ngân sách nặng nề. Hai cơ chế bảo vệ hai chiều (tần suất vs chi phí tích lũy) nên bắt buộc phải đi đôi với nhau.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Liveness (`/health`) vs Readiness (`/ready`) (`05-scaling-reliability/develop/app.py`)

#### Phân biệt vai trò giữa `/health` và `/ready`

| Tiêu chí | Liveness Probe (`GET /health`) | Readiness Probe (`GET /ready`) |
| :--- | :--- | :--- |
| **Câu hỏi cốt lõi** | Tiến trình (process) trong container còn sống và phản hồi không? | Instance này hiện có đủ điều kiện để nhận traffic mới từ user không? |
| **Khi trả mã lỗi (`5xx` / timeout)** | Platform (Railway, Render, Kubernetes) **giết và khởi động lại (restart)** container. | Load Balancer **tạm ngắt điều phối request mới** tới instance này nhưng **không** restart container. |
| **Phụ thuộc bên ngoài (Redis/DB)** | **Không nên phụ thuộc cứng:** Nếu Redis tạm chập chờn mà `/health` trả `503`, toàn bộ dàn agent container sẽ bị restart dây chuyền (*cascading restart*) một cách vô ích. | **Bắt buộc kiểm tra:** Khi chưa nạp xong model (`_is_ready = False`), đang graceful shutdown hoặc mất kết nối Redis (`redis.ping()` lỗi) thì phải trả **`503 Service Unavailable`**. |

#### Kết quả kiểm thử thực tế trên `develop/app.py`

- **`GET /health` (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:18:11 GMT
  server: uvicorn
  content-type: application/json

  {"status":"degraded","uptime_seconds":0.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T08:18:13.328539+00:00","checks":{"memory":{"status":"degraded","used_percent":90.5}}}
  ```
- **`GET /ready` (`200 OK`):**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:18:13 GMT
  server: uvicorn
  content-type: application/json

  {"ready":true,"in_flight_requests":1}
  ```

---

### Exercise 5.2: Graceful Shutdown với `SIGTERM`

#### Cơ chế hoạt động

1. Middleware `track_requests` tăng bộ đếm `_in_flight_requests` khi request bắt đầu và giảm trong khối `finally` khi xử lý xong.
2. Khi nền tảng dừng hoặc cập nhật container (`docker stop`, rolling deploy), hệ điều hành gửi tín hiệu **`SIGTERM`** (khác với `SIGKILL` không thể bắt).
3. Uvicorn nhận `SIGTERM`, ngừng nhận kết nối mới và kích hoạt nhánh thoát của `lifespan()`: đặt `_is_ready = False` (để `/ready` trả `503` cho Load Balancer), chờ vòng lặp `_in_flight_requests > 0` về `0` (tối đa `timeout_graceful_shutdown=30` giây) rồi mới đóng tiến trình với **`exit code 0`**.

#### Kết quả kiểm thử thực tế (`docker stop` gửi `SIGTERM` ngay khi đang xử lý request)

- **Phản hồi của request đang chạy dở (`POST /ask?question=Long%20task`) — không bị ngắt kết nối:**
  ```http
  HTTP/1.1 200 OK
  date: Thu, 26 Nov 2026 08:18:44 GMT
  server: uvicorn
  content-length: 95
  content-type: application/json

  {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
  ```
- **Log tuần tự trong container và mã thoát:**
  ```text
  INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
  INFO:     172.17.0.1:38840 - "GET /ready HTTP/1.1" 200 OK
  INFO:     Shutting down
  INFO:     172.17.0.1:38852 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
  INFO:     Waiting for application shutdown.
  2026-11-26 08:18:49,018 INFO 🔄 Graceful shutdown initiated...
  2026-11-26 08:18:49,018 INFO ✅ Shutdown complete
  INFO:     Application shutdown complete.
  INFO:     Finished server process [1]
  2026-11-26 08:18:49,019 INFO Received signal 15 — uvicorn will handle graceful shutdown
  Container ExitCode: 0
  ```

---

### Exercise 5.3: Thiết kế Stateless với Redis (`05-scaling-reliability/production/app.py`)

- **Tại sao lưu state trong RAM (`dict` toàn cục) hỏng khi chạy nhiều instance?**
  1. **Mất tính nhất quán giữa các replicas/workers:** Mỗi container (hoặc mỗi Uvicorn worker process) có không gian RAM tách biệt hoàn toàn. Khi Load Balancer chia tải Round-Robin, câu hỏi thứ nhất của user đi vào `Instance 1` (lưu vào RAM của `Instance 1`), nhưng câu hỏi thứ hai lại được đẩy sang `Instance 2` (RAM trống) làm agent mất sạch ngữ cảnh hội thoại.
  2. **Mất dữ liệu khi khởi động lại / auto-scale:** Mọi đợt deploy bản mới, restart do lỗi hoặc scale down đều xóa trắng dữ liệu trong RAM.
- **Cách khắc phục trong `production/app.py`:**
  - Chuyển toàn bộ trạng thái phiên ra **Redis** dùng chung: hàm `save_session()` ghi chuỗi JSON vào khóa `session:{session_id}` kèm TTL tự hết hạn sau 1 giờ (`_redis.setex(f"session:{session_id}", 3600, serialized)`), và `load_session()` đọc lại từ Redis ở mỗi lượt `POST /chat`. Nhờ vậy mọi container `agent` đều hoàn toàn **stateless** và có thể thêm/bớt số lượng tùy ý.

---

### Exercise 5.4 & 5.5: Load Balancing 3 Instances qua Nginx & Kiểm thử `test_stateless.py`

Khởi chạy cụm 3 replicas của `agent` sau Nginx Load Balancer (mở cổng `8080`, endpoint `POST /chat`) kết nối chung 1 container Redis:

```bash
cd 05-scaling-reliability/production
docker compose -p k5-day14-scaling up -d --build --scale agent=3
python test_stateless.py
docker compose -p k5-day14-scaling down -v
```

#### 1. Kết quả chạy `python test_stateless.py`

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 12144f33-f309-40d7-b1e0-aed26b8ee287

Request 1: [instance-0e99a7]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-00f49a]
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 3: [instance-e729c1]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-0e99a7]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-00f49a]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-00f49a', 'instance-e729c1', 'instance-0e99a7'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

#### 2. Log đối chiếu trên cả 3 Replicas (`docker compose -p k5-day14-scaling logs agent`)

```text
agent-1  | INFO:app:Starting instance instance-e729c1
agent-1  | INFO:app:Storage: Redis ✅
agent-1  | INFO:     172.19.0.6:42738 - "POST /chat HTTP/1.1" 200 OK
agent-1  | INFO:     172.19.0.6:42738 - "GET /chat/12144f33-f309-40d7-b1e0-aed26b8ee287/history HTTP/1.1" 200 OK
agent-2  | INFO:app:Starting instance instance-0e99a7
agent-2  | INFO:app:Storage: Redis ✅
agent-2  | INFO:     172.19.0.6:50836 - "POST /chat HTTP/1.1" 200 OK
agent-2  | INFO:     172.19.0.6:50836 - "POST /chat HTTP/1.1" 200 OK
agent-3  | INFO:     172.19.0.6:37754 - "POST /chat HTTP/1.1" 200 OK
agent-3  | INFO:     172.19.0.6:37754 - "POST /chat HTTP/1.1" 200 OK
```

#### 3. Giải thích kết quả

- **Phân tải Round-Robin chính xác:** Nginx phân giải DNS nội bộ `agent:8000` ra 3 IP container và xoay vòng đều 5 lượt chat lần lượt qua `instance-0e99a7` (`agent-2`, 2 lượt) → `instance-00f49a` (`agent-3`, 2 lượt) → `instance-e729c1` (`agent-1`, 1 lượt + 1 lượt đọc `/history`). Cấu hình `proxy_next_upstream error timeout http_503` trong `nginx.conf` cũng đảm bảo nếu 1 replica gặp sự cố, request sẽ tự động chuyển tiếp sang replica khỏe mạnh kế tiếp.
- **Bảo toàn trạng thái hội thoại 100%:** Mặc dù 5 câu hỏi cùng chung `session_id = 12144f33-f309-40d7-b1e0-aed26b8ee287` đi qua 3 container vật lý hoàn toàn khác nhau, khi gọi `GET /chat/{session_id}/history` (rơi vào `agent-1`), hệ thống vẫn trả về đầy đủ **`10` messages** (5 cặp `user`/`assistant` đúng thứ tự) nhờ mọi đọc/ghi đều tập trung tại Redis.

---

## Part 6: Production Readiness Check Output

Kết quả chạy chế độ đầy đủ `python check_production_ready.py` trong `06-lab-complete/` (môi trường POSIX + Docker Engine 29.7.2):

```text
================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 85s
     ✅ Docker: image < 500 MB — 56 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.7s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

---

## AI Log

| Thời điểm / Phần | Nội dung hỏi AI | Gợi ý / Kết quả từ AI | Cách tự kiểm tra & chỉnh sửa |
| :--- | :--- | :--- | :--- |
| **CP0 — Setup** | Yêu cầu tổng quan nội dung bài lab và thiết lập môi trường làm việc ban đầu. | Tổng hợp lộ trình CP0–CP8, tạo môi trường ảo `.venv` (Python 3.11.17), cài đặt dependencies và tạo sẵn `.env` / `.env.local` (đã nằm trong `.gitignore`). | Kiểm tra `git status`, xác nhận `.venv`, `.env` và `.env.local` không bị track bởi Git; xác nhận phiên bản Python 3.11.17. |
| **CP1 — Part 1** | Phân tích anti-patterns trong `01-localhost-vs-production/develop/app.py`, chạy thử nghiệm đối chiếu với `production/app.py` và tổng hợp vào `MISSION_ANSWERS.md`. | Liệt kê 7 anti-patterns kèm số dòng code, chạy thực tế hai server để thu output HTTP (`200`, `422`, `404`) và lập bảng so sánh theo chuẩn 12-Factor App. | Đối chiếu từng dòng code trong `develop/app.py`, `production/app.py`, `production/config.py` và kiểm chứng trực tiếp phản hồi `curl` từ cả hai server. |
| **CP2 — Part 2** | Giải phóng cổng 8000, phân tích `Dockerfile` đơn tầng vs multi-stage, đo dung lượng image và kiểm thử stack Docker Compose + Nginx. | Giải thích cơ chế layer cache, `CMD` vs `ENTRYPOINT`, multi-stage build, vẽ sơ đồ 4 services (`nginx`, `agent`, `redis`, `qdrant`) và cập nhật kết quả thực nghiệm vào `MISSION_ANSWERS.md`. | Tự build `my-agent:develop` (`1.67 GB` / `426 MB`) và `my-agent:advanced` (`240 MB` / `57.4 MB`) bằng Docker 29.7.2, kiểm thử trực tiếp qua `curl` ở cổng `8000` và cổng `80` (Nginx), sau đó dọn sạch stack. |
| **CP3 — Part 4** | Phân tích cơ chế API Key, JWT, Sliding Window Rate Limiter và Cost Guard trong `04-api-gateway/`, chạy thực nghiệm và tổng hợp vào `MISSION_ANSWERS.md`. | Giải thích key rotation, JWT stateless flow, Sliding Window `deque`, thiết kế Cost Guard dùng Redis `INCRBYFLOAT` và chạy vòng lặp kiểm thử thu mã HTTP `401`/`403`/`200`/`429`. | Kiểm tra output `curl -i` thực tế với tài khoản `student` (`10 req/min`), xác nhận từ request thứ 11 trả `429` kèm `Retry-After` và đảm bảo toàn bộ JWT token đã được che (`<REDACTED_JWT_TOKEN>`) trước khi lưu vào file. |
| **CP4 — Part 5** | Kiểm thử Liveness/Readiness probes, `SIGTERM` graceful shutdown và kiến trúc Stateless với 3 replicas + Redis + Nginx trong `05-scaling-reliability/`. | Phân biệt `/health` vs `/ready`, kiểm thử `docker stop` khi đang có in-flight request, chạy stack `k5-day14-scaling` (`--scale agent=3`) cùng `test_stateless.py` và ghi nhận kết quả vào `MISSION_ANSWERS.md`. | Xác nhận container thoát với `ExitCode: 0` mà không làm đứt request đang chạy (`200 OK`), kiểm chứng cả 3 instance IDs xuất hiện trong `test_stateless.py` với đủ 10 messages lưu trong Redis và dọn sạch stack cổng `8080`. |
| **CP5 — Part 6 (Final Project)** | Hoàn thiện toàn bộ các `TODO` trong `06-lab-complete/` (`config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, multi-stage `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`, `railway.toml`, `render.yaml`). | Triển khai xác thực `X-API-Key` bằng `secrets.compare_digest` (`401`), Sliding Window Rate Limiter bằng Redis Sorted Set (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` + `Retry-After` → `429`), Cost Guard dùng `INCRBYFLOAT` (`402`), `JsonFormatter`, `/health` tách biệt `/ready` (`503` khi mất Redis), `lifespan` graceful shutdown và `Dockerfile` multi-stage `exec uvicorn` non-root. | Chạy kiểm định đầy đủ bằng `python check_production_ready.py` trong môi trường POSIX + Docker Engine 29.7.2, kiểm tra từng dòng trong 43/43 sub-checks đều đạt (`PASS 12/12`, image `56 MB`, `docker stop` `0.7s` `exit code 0`) và xác nhận `git diff 06-lab-complete/check_production_ready.py` hoàn toàn trống (không chạm tới script chấm). |
| **CP6 — Part 3 (Cloud Deployment)** | Deploy agent Part 6 kèm Redis lên Railway, kiểm thử Public URL, viết `DEPLOYMENT.md` và trả lời Exercise 3.1–3.3 trong `MISSION_ANSWERS.md`. | Sử dụng Railway CLI khởi tạo project `k5-day14-production-agent` + `Redis` (`${{Redis.REDIS_URL}}`), deploy từ `06-lab-complete/`, tạo `DEPLOYMENT.md` (không chứa secret) và đối chiếu `railway.toml`, `render.yaml`, `cloudbuild.yaml`, `service.yaml`. | Tự chạy 4 lệnh `curl` kiểm chứng trực tiếp trên `https://agent-production-143225b4.up.railway.app` xác nhận trả đúng `200`, `200` (`"redis":"ok"`), `401`, `200` và kiểm tra log JSON trên Railway. |
| **CP7 — Part 7 Bước 1 (Benchmark Local)** | Bổ sung Histogram `agent_question_length_chars`, chạy Load Test (`c=1,10,50,100` và `MOCK_SLOW_RATE=0,0.03,0.1`), chạy Eval `v1` vs `v2`, vá `KNOWLEDGE_BASE` và tạo CI workflow `.github/workflows/eval.yml`. | Thêm metric vào `develop/app.py`, thêm 2 mục kiến thức (`jwt`, `hpa`/`kubernetes`) vào `utils/mock_llm.py`, lưu đủ 10 file JSON vào `reports/` và điền Mục 1–3 của `BENCHMARK_REPORT.md`. | Đối chiếu trực tiếp từng con số trong `BENCHMARK_REPORT.md` khớp 100% với 10 file JSON đã xuất, xác nhận `eval_v2_fixed.json` đạt `23/23` (`100%`, `0` regression) và xác nhận `git diff` trên `golden_dataset.jsonl` trống. |
| **CP8 — Part 7 Bước 2 (Observability Stack)** | Bật stack `k5-day14-observability`, chạy Locust headless `scale_1` vs `scale_3`, phân tích Grafana/Jaeger/Prometheus, chạy thí nghiệm Chaos kích hoạt Alerts và hoàn thiện `BENCHMARK_REPORT.md`. | Sửa thiếu biến `PYTHONUSERBASE` trong `production/Dockerfile`, chạy Locust `--no-deps` xuất `scale_1_stats.csv` & `scale_3_stats.csv`, trích xuất `trace_id` chậm/lỗi kèm dòng log JSON và chụp 4 ảnh màn hình qua CDP. | Tự kiểm tra từng ảnh chụp (`grafana-dashboard.png`, `jaeger-slow-trace.png`, `jaeger-error-trace.png`, `prometheus-alert-firing.png` có đủ 4 alerts `FIRING`), đối chiếu khớp 100% số liệu CSV vào Mục 4–6 của `BENCHMARK_REPORT.md` và dọn sạch stack Docker. |
