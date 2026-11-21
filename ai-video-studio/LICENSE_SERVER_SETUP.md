# Cấu hình máy chủ bản quyền

## Cấu hình Neon và web server

Chạy `license_server/schema.sql` trong SQL Editor của Neon. Trong thư mục `ai-video-studio`, tạo hoặc cập nhật `.env.local`:

```env
DATABASE_URL=<chuỗi-kết-nối-Neon>
```

Restart Next.js after updating `.env.local`. The license admin page automatically loads and manages licenses from the database. Admin API routes accept only localhost and private network hosts; do not expose the admin page publicly.

## Xác thực ứng dụng desktop trên cùng máy

Chạy `Run AI Video Studio.bat` trước. Desktop app mặc định kết nối tới API cục bộ:

```text
http://127.0.0.1:3100/api/license/validate
```

HTTP chỉ được cho phép trên loopback của chính máy này để chạy local. Đảm bảo Next.js đã sẵn sàng và `DATABASE_URL` kết nối được Neon. Sau đó chạy `Mo Tool CapCut.bat` và nhập key vừa tạo trong trang quản trị.

## Dùng trên máy khách qua Internet

Khi phát hành desktop app cho máy khác, triển khai Next.js lên host có HTTPS và Neon access. Đặt biến `CAPCUT_LICENSE_API_URL` trên máy khách thành URL HTTPS đầy đủ, ví dụ:

```text
https://ten-mien-cua-ban/api/license/validate
```

API nhận `POST application/json`:

```json
{"app":"capcut-tool","license_key":"<key-da-cap>"}
```

Key hợp lệ trả `valid: true`; key sai, hết hạn hoặc bị thu hồi trả `valid: false` với thông báo chung. API lưu SHA-256 của key và không ghi key thô vào database. Không dùng URL PostgreSQL làm `CAPCUT_LICENSE_API_URL`.

## Khóa key theo một thiết bị

Bản cập nhật schema thêm cột `bound_device_hash`. Chạy lại `license_server/schema.sql` trong Neon trước khi dùng phiên bản desktop mới. Lần xác thực thành công đầu tiên sẽ gắn key vào máy đó; các lần xác thực sau chỉ thành công trên cùng thiết bị. API chỉ nhận mã băm định danh thiết bị, không nhận MachineGuid thô. Không hỗ trợ chuyển key đã kích hoạt sang máy khác; cần cấp key mới cho máy mới.

Trong desktop app, tab **1. Học mẫu** có ô **Hướng dẫn AI khi chọn project để học**. Nội dung lưu cục bộ trong `data/settings.json` và được dùng trong bước AI chọn project. Phần phân tích timeline, beat và ô thay vẫn do bộ học công thức trong app thực hiện. Cần cấu hình model trong chính desktop app nếu muốn AI dùng hướng dẫn này.

## Tạo nội dung bằng prompt trong desktop app

Trong tab **4. Marketing FB / TikTok**, các công cụ được tách riêng:

- **Tạo ảnh từ prompt** dùng OpenAI Images API. Chọn tỷ lệ Facebook/TikTok, nhập prompt và lưu ảnh PNG. Cấu hình OpenAI trong nút **Cấu hình OpenAI** hoặc đặt `OPENAI_API_KEY`.
- **Tạo video từ prompt** dùng Veo trên Vertex AI. Prompt video, nền tảng, tỷ lệ, thời lượng và model Veo nằm trong tab riêng. Cần Google Cloud Project đã bật Vertex AI, quyền gọi model Veo và đăng nhập Application Default Credentials bằng Google Cloud CLI (`gcloud auth application-default login`). Nhập Project ID trong màn hình video; vị trí mặc định là `us-central1`.

Cả hai dịch vụ có thể tính phí theo lượt. App sẽ hỏi xác nhận trước khi gửi prompt. Video Veo được lưu về máy trong `data/marketing`; ảnh OpenAI được ghi ra vị trí người dùng chọn bằng nút **Lưu ảnh PNG**. Veo trên Vertex AI hiện có model `veo-3.1-fast-generate-001` và `veo-3.1-generate-001`; Gemini Developer API không còn là đường dùng Veo, nên luồng này dùng Google Cloud Vertex AI.

## Image provider selection and license footer

The desktop Marketing tab lets the user choose OpenAI or Google Gemini and then choose an image model. The app remembers the last selection. Configure the provider's API key in **AI / API key** or with `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`. Image and video requests may be billed; the app asks before sending each prompt.

The desktop window footer shows the license plan, expiry date (or no-expiry status), and activated-device status. It never displays the license key.

## Quy trình AI soạn nội dung và admin duyệt

Trong Marketing Studio, tab **AI soạn nội dung & duyệt** hỏi sản phẩm, khách hàng, mục tiêu, ưu đãi, nền tảng và giọng điệu. Nội dung, caption, hashtag và prompt ảnh/video được soạn bằng Ollama local, không mất phí API. Cần cài Ollama, chạy `ollama pull qwen2.5`, sau đó để dịch vụ chạy tại `http://localhost:11434` (có thể đổi model/URL trong tab).

Bản nháp không tự tạo media và không tự đăng. Chọn Telegram để gửi bot token, chat ID và user ID của admin; admin duyệt bằng `/approve MA` hay từ chối bằng `/reject MA` (thay `MA` bằng mã hiện trong tin nhắn). Giữ desktop app mở để nhận phản hồi bot. Chọn Zalo để gửi JSON tới webhook HTTPS của OA/automation; admin gửi lại mã duyệt cho người vận hành nhập trong app. Sau khi duyệt, bấm **Áp dụng prompt đã duyệt**; thao tác này chỉ chuyển prompt sang trang ảnh/video, chưa chạy tạo media.

Ảnh có thể tạo local qua ComfyUI API tại `http://127.0.0.1:8188`; cần cài ComfyUI, tải checkpoint SDXL vào thư mục model của ComfyUI và điền đúng tên checkpoint. Tạo ảnh local không cần API key. Video vẫn cần model/dịch vụ video đã cài hoặc cấu hình (luồng Veo hiện tại có thể tính phí). App không đăng nội dung tự động.

Bot token and webhook secret are password fields and are not written to `data/settings.json`; they are cleared when the app exits unless provided with `APPROVAL_TELEGRAM_BOT_TOKEN` or `APPROVAL_ZALO_WEBHOOK_SECRET`. Telegram admin must first open the bot and send `/start`; the bot chat ID and authorized Telegram user ID are configured separately.
