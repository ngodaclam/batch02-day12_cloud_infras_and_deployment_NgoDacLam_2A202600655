# Hướng dẫn Productionization & Deploy Dự án Travel Agent (Part 6)

Tài liệu này hướng dẫn chi tiết các bước cấu trúc lại mã nguồn (Restructure) để nâng cấp dự án **Travel Agent (BudgetTrip Planner)** đạt chuẩn môi trường Production, cách thức deploy lên Cloud và ghi nhận đường dẫn API URL.

---

## 1. Các bước đã thực hiện để Productionization (Restructure Code)

Chúng tôi đã chuyển đổi dự án Travel Agent ban đầu thành một ứng dụng đạt **100% điểm kiểm tra chất lượng (20/20 Checks)** nhờ áp dụng các nguyên lý sản xuất sau:

### ⚡ Kiến trúc không trạng thái (Stateless Architecture)
- **Vấn đề trước đó**: Lịch sử trò chuyện và thông tin chuyến đi lưu trong biến bộ nhớ `SESSION_CONTEXT` dạng Python dictionary. Nếu chạy nhiều instance, dữ liệu của người dùng sẽ bị thất lạc khi Load Balancer phân tán request sang instance khác.
- **Giải pháp**: Di chuyển toàn bộ session lưu trữ sang **Redis** sử dụng các câu lệnh `r.get(key)`, `r.setex(key, ttl, value)`, và `r.delete(key)`. Mỗi instance agent giờ đây hoàn toàn không lưu trạng thái (Stateless) và có thể đáp ứng request của bất kỳ session nào.

### 🔒 Bảo mật xác thực (API Key Authentication)
- Tích hợp lớp bảo mật FastAPI Dependency bằng header `X-API-Key`. Mọi request gửi tới `/api/chat` hoặc `/api/sessions/{session_id}/reset` đều bắt buộc phải kèm theo khóa API khớp với biến môi trường `AGENT_API_KEY`.

### ⏱️ Giới hạn tần suất gọi (Rate Limiting)
- Triển khai giải thuật **Sliding Window Rate Limiter** bằng Redis Sorted Set pipeline. 
- Giới hạn tối đa **10 requests / phút** cho mỗi phiên chat (`session_id`) để bảo vệ tài nguyên máy chủ trước các cuộc tấn công spam request hoặc vòng lặp vô tận.

### 💰 Kiểm soát chi phí gọi LLM (Cost Guard)
- Theo dõi chi phí gọi LLM thực tế và ghi nhận vào Redis theo từng tháng. 
- Nếu chi tiêu tích lũy vượt quá định mức tháng (`MONTHLY_BUDGET_USD` - mặc định $10.0), hệ thống sẽ lập tức chặn cuộc gọi và trả về mã lỗi `402 Payment Required`.

### 🩺 Thăm dò sức khỏe hệ thống (Health & Readiness Probes)
- **Liveness Probe (`/health`)**: Trả về trạng thái tiến trình FastAPI giúp nền tảng Cloud biết container còn chạy tốt không.
- **Readiness Probe (`/ready`)**: Kiểm tra kết nối thực tế tới Redis. Nếu kết nối Redis bị đứt, endpoint sẽ trả về `503 Service Unavailable`, báo hiệu Load Balancer ngừng điều phối traffic vào container này cho đến khi kết nối phục hồi.

### 🔄 Tắt hệ thống an toàn (Graceful Shutdown)
- Đăng ký bộ xử lý tín hiệu `SIGTERM` và `SIGINT`. Khi nhận lệnh tắt, container sẽ đóng kết nối Redis một cách an toàn và uvicorn sẽ đợi các request đang xử lý dở hoàn thành (tối đa 30 giây) trước khi chính thức kết thúc tiến trình.

### 📊 Log có cấu trúc (Structured Logging)
- Cấu hình thư viện logging chuẩn hóa định dạng JSON: `{"time":"...","level":"...","message":"..."}` giúp dễ dàng đẩy log sang các hệ thống lưu trữ tập trung như ELK, Splunk hay CloudWatch.

### 🐳 Đóng gói Docker tối ưu (Multi-stage Build & Non-root)
- Cấu hình [Dockerfile](file:///c:/Users/LocND/Desktop/api/batch02-day12_cloud_infras_and_deployment_NgoDacLam_2A202600655/06-lab-complete/Dockerfile) phân tách làm 2 Stage:
  - **Stage 1 (Builder)**: Biên dịch requirements.txt bằng các công cụ nặng.
  - **Stage 2 (Runtime)**: Chỉ sao chép thư mục local-packages đã build và mã nguồn vào image `python:3.11-slim` siêu nhẹ.
- Container chạy bằng user thường (`agent` - non-root) để tăng tính bảo mật, tránh lỗ hổng đặc quyền root.
- Cấu hình `HEALTHCHECK` định kỳ gọi curl `/health` nội bộ.

---

## 2. Hướng dẫn Deploy lên Railway

Dự án đã có sẵn file cấu hình [railway.toml](file:///c:/Users/LocND/Desktop/api/batch02-day12_cloud_infras_and_deployment_NgoDacLam_2A202600655/06-lab-complete/railway.toml) bọc lệnh chạy trong trình shell `sh -c` để tự động gán cổng `$PORT` do Railway cấp phát:

1. Di chuyển vào thư mục dự án hoàn chỉnh:
   ```bash
   cd 06-lab-complete
   ```
2. Đăng nhập tài khoản Railway:
   ```bash
   railway login
   ```
3. Khởi tạo một dự án Railway mới:
   ```bash
   railway init
   ```
4. Thiết lập các biến môi trường bắt buộc trên dashboard Railway hoặc bằng CLI:
   ```bash
   railway variables set PORT=8000
   railway variables set AGENT_API_KEY=my-secret-api-key
   railway variables set REDIS_URL=redis://<your-redis-service-host>:<port>
   ```
5. Đẩy code lên deploy:
   ```bash
   railway up
   ```

---

## 🔗 3. Thông tin API URL Link

Sau khi quá trình deploy hoàn tất, Railway sẽ cấp phát một URL công khai. Vui lòng cập nhật đường dẫn API URL thực tế của bạn dưới đây:

* **API URL Public Link**: `https://<ten-dich-vu-cua-ban>.up.railway.app`
* **Health Check Public Link**: `https://<ten-dich-vu-cua-ban>.up.railway.app/health`
