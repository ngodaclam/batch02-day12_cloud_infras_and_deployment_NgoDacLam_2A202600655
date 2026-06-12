# Solution: Cloud Infrastructure & Deployment (Day 12 Lab)

Dưới đây là đáp án chi tiết cho các bài tập codelab từ Part 1 đến Part 5.

---

## Part 1: Localhost vs Production

### 1. Các vấn đề (anti-patterns) phát hiện trong basic `app.py`:
- **Hardcoded secrets**: API key (`AGENT_API_KEY`) được viết cứng trong mã nguồn.
- **Cấu hình Port cố định**: Port `8000` bị cố định trong code, không lấy từ biến môi trường.
- **Bật Debug Mode**: Bật `debug=True` trong môi trường sản xuất có thể lộ thông tin nhạy cảm.
- **Thiếu Health check**: Không có endpoint `/health` hay `/ready` để cloud orchestrator kiểm tra trạng thái container.
- **Không xử lý Graceful shutdown**: Ứng dụng tắt đột ngột khi nhận tín hiệu SIGTERM/SIGINT, làm gián đoạn các request đang xử lý.

### 2. So sánh Basic vs Advanced version:

| Feature | Basic | Advanced | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| **Config** | Hardcode | Env vars (`.env`) | Bảo mật secrets, dễ dàng cấu hình ứng dụng linh hoạt theo từng môi trường mà không cần sửa code. |
| **Health check** | Không có | `/health` | Cloud platform biết khi nào container gặp lỗi để tự động restart (Liveness Probe). |
| **Logging** | `print()` | JSON logs | Log có cấu trúc dễ thu thập, lưu trữ và phân tích bằng các công cụ tập trung như ELK, Datadog. |
| **Shutdown** | Đột ngột | Graceful | Hoàn thành nốt các request đang chạy dở trước khi dừng container, tránh mất mát dữ liệu của user. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Dockerfile cơ bản
1. **Base image là gì?**
   - `python:3.11` (Ubuntu-based Python image đầy đủ).
2. **Working directory là gì?**
   - `/app` (thư mục làm việc mặc định trong container).
3. **Tại sao COPY requirements.txt trước?**
   - Để tận dụng cơ chế cache layer của Docker. Nếu file `requirements.txt` không thay đổi, Docker sẽ bỏ qua bước chạy `pip install` ở các lần build sau, giúp tăng tốc build đáng kể.
4. **CMD vs ENTRYPOINT khác nhau thế nào?**
   - `ENTRYPOINT` định nghĩa câu lệnh mặc định luôn chạy khi khởi động container.
   - `CMD` định nghĩa tham số mặc định cho `ENTRYPOINT` và có thể dễ dàng bị ghi đè khi chạy container từ command line (ví dụ: `docker run my-image python alternate_script.py`).

### Exercise 2.3: Multi-stage build
- **Stage 1 (Builder)**: Cài đặt các công cụ build nâng cao (`gcc`, `libpq-dev`), tải và biên dịch các dependencies vào thư mục tạm `/root/.local`.
- **Stage 2 (Runtime)**: Chỉ sử dụng image `python:3.11-slim` tối giản, copy các packages đã cài đặt từ Stage 1 sang và chạy ứng dụng dưới quyền user thường (`appuser`).
- **Tại sao image nhỏ hơn?** Vì Stage 2 hoàn toàn loại bỏ các compiler, công cụ build và cache của pip vốn chỉ dùng lúc build, giúp kích thước image giảm mạnh (từ ~1GB xuống < 150MB) và tăng tính bảo mật.

---

## Part 3: Cloud Deployment

### So sánh `render.yaml` với `railway.toml`:
- `render.yaml` (Render Blueprint): Định nghĩa toàn bộ hạ tầng gồm các service, môi trường, biến env và database đi kèm dưới dạng Infrastructure as Code (IaC).
- `railway.toml`: Chỉ chứa các cấu hình chạy cục bộ cho Railway CLI như cách build, kiểm tra healthcheck và watch patterns khi deploy code.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication
- **API key được check ở đâu?** Tại dependency `verify_api_key` bằng cách đọc header `X-API-Key`.
- **Điều gì xảy ra nếu sai key?** Trả về `403 Forbidden` nếu key sai, hoặc `401 Unauthorized` nếu thiếu header.
- **Làm sao rotate key?** Cập nhật giá trị biến môi trường `AGENT_API_KEY` mà không cần deploy lại code.

### Exercise 4.3: Rate limiting
- **Algorithm nào được dùng?** Sliding Window Counter (sử dụng `deque` lưu timestamp).
- **Limit là bao nhiêu?** Normal User: 10 req/phút; Admin: 100 req/phút.
- **Bypass limit cho admin bằng cách nào?** Sử dụng instance RateLimiter riêng có cấu hình giới hạn cao hơn nhiều (`rate_limiter_admin`).

### Exercise 4.4: Cost Guard
- Quản lý chi phí LLM bằng cách tính toán token tiêu thụ của mỗi request dựa theo đơn giá của nhà cung cấp.
- Giới hạn budget cho mỗi user ($1.0/ngày) và giới hạn budget toàn cục ($10.0/ngày) để tránh bill tăng đột biến.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health check & Graceful Shutdown
- `/health` (Liveness probe) kiểm tra tiến trình có sống không để orchestrator restart nếu treo.
- `/ready` (Readiness probe) kiểm tra kết nối với Redis/DB. Nếu lỗi, Load Balancer sẽ ngắt traffic đến instance đó.
- Graceful shutdown lắng nghe `SIGTERM`/`SIGINT`, chuyển trạng thái `_is_ready = False` để LB ngừng đẩy traffic vào, sau đó chờ các request in-flight hoàn tất trước khi dừng.

### Exercise 5.3 & 5.4: Stateless Design & Load Balancing
- Để scale lên nhiều instances phía sau Load Balancer (Nginx), dữ liệu session lịch sử chat phải được lưu trữ tập trung ở **Redis** thay vì lưu trong bộ nhớ RAM cục bộ của từng instance.
- Kết quả test thực tế với 3 instance và Nginx cho thấy các request được load balance lần lượt qua các instance khác nhau nhưng lịch sử trò chuyện vẫn hoàn toàn liền mạch và chính xác.
