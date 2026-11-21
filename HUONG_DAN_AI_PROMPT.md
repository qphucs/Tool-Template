# Hướng dẫn prompt AI

App có 3 chỗ dùng prompt mới:

## 1. Tạo nhiều mẫu khác nhau (tab **2. Tạo mẫu**)

Khung **Prompt tạo nhiều mẫu**:

- **Prompt**: mô tả bạn muốn gì. Ví dụ:
  - `tạo 8 mẫu cho ảnh couple: 3 tone tối giản, 2 neon, 2 retro, 1 điện ảnh`
  - `ưu tiên nhịp nhanh, chữ to, ảnh đường phố, tone tối`
  - `mỗi mẫu một kiểu, tiêu đề ngắn, nhiều hashtag TikTok`
- **Số mẫu**: 1–30.
- **Biến tấu công thức**: cắt bớt vài beat ở đầu và/hoặc giữ lại một phần ô thay, để các mẫu không giống hệt nhau.
- **Tạo nhiều mẫu theo prompt**: sinh đủ số project trong CapCut.
- **Chạy thử prompt**: chỉ tính toán và in tiêu đề/hashtag, không ghi vào CapCut.

Cách chạy:

1. Chọn **Khung mẫu** đã học.
2. Chọn nhạc và ảnh/clip như bình thường.
3. Nhập prompt, chọn số mẫu.
4. Bấm **Chạy thử prompt** trước nếu muốn xem kế hoạch.
5. Tắt CapCut rồi bấm **Tạo nhiều mẫu theo prompt**.

Nếu có nhiều bài nhạc, các biến thể tự chia nhau dùng nhạc. Nếu chọn ảnh theo thứ tự, mỗi biến thể xoay thứ tự ảnh để ra bố cục khác.

## 2. Tự học hàng loạt (tab **1. Học mẫu**)

Ô **Prompt tự học** lọc project CapCut trước khi học:

- Để trống: học tất cả project đang hiện (theo ô tìm kiếm và bộ lọc độ dài).
- `project dưới 15 giây`
- `tên có remix`
- `"couple" dưới 20 giây`
- `từ 10 đến 20 giây`
- `học các mẫu tone neon, bỏ project quá dài`

Tick **Học lại project đã học** nếu muốn học lại. App tự bỏ qua project đã có công thức.

Có cấu hình AI thì AI đọc tên + độ dài để chọn project theo nghĩa câu prompt; không có AI thì dùng bộ lọc từ khóa/độ dài.

> Tự học hàng loạt chỉ áp dụng cho **project đã có trong CapCut**. Video mẫu tải trên mạng vẫn cần làm theo tab **0. Từ video mẫu** để edit thành project CapCut trước, rồi mới học được thành công thức.

## 3. Biến tấu công thức

Nằm trong phần **Biến tấu công thức** của tab Tạo mẫu. Các thay đổi được giới hạn để không làm hỏng project CapCut:

- Dịch điểm bắt đầu thêm 0–3 beat (cắt bớt phần đầu, mẫu dồn hơn).
- Giữ lại 60–100% ô thay để bố cục khác bản gốc (khi dùng thư mục nguyên liệu; chế độ chọn ảnh theo thứ tự vẫn giữ đủ số ảnh).
- Đổi seed chọn ảnh và đổi phong cách tiêu đề/hashtag.

App không sửa hiệu ứng gốc, không đổi tốc độ clip, không đổi cấu trúc track — những thay đổi sâu như vậy dễ làm CapCut mở lỗi.

## Cấu hình AI

Bấm **Cấu hình AI…** ở tab Tạo mẫu.

Trong hộp thoại, có thể nhập **Prompt hướng dẫn AI** để đặt tiêu chí riêng, ví dụ ngôn ngữ, độ dài video hoặc phong cách mong muốn. Prompt này được thêm vào các yêu cầu AI của tool và lưu trong `data/settings.json` trên máy.

Có thể chọn thêm **Model 2** và **Model 3** để phối hợp tối đa ba model. Các model chạy lần lượt: model đầu tạo kết quả, model sau rà soát và chỉnh JSON trước đó. Mỗi model bổ sung có provider, tên model và API key riêng; Ollama chạy local không cần key. Chỉ bật một model nếu muốn dùng đơn lẻ.

### Model trả phí

- **Claude (Anthropic)**: đặt `ANTHROPIC_API_KEY` hoặc nhập key trong hộp thoại.
- **OpenAI**: đặt `OPENAI_API_KEY`, model mặc định `gpt-4.1-mini`.

### Model miễn phí / hạn mức miễn phí

- **OpenRouter**: các model có đuôi `:free`, key `OPENROUTER_API_KEY`.
- **Groq**: hạn mức miễn phí, key `GROQ_API_KEY`.
- **Google Gemini**: hạn mức miễn phí, key `GEMINI_API_KEY` hoặc `GOOGLE_API_KEY`.
- **Ollama**: chạy local, không cần key, không cần mạng. Cài Ollama rồi chạy `ollama pull llama3.1`.

Tên model free thay đổi theo thời gian. Ô **Model** có danh sách gợi ý nhưng vẫn cho gõ tay; nếu báo lỗi model không tồn tại, sửa theo tên mới trên trang của nhà cung cấp.

### Biến môi trường

Có thể đặt trước khi mở app:

```bat
set ANTHROPIC_API_KEY=...
set OPENROUTER_API_KEY=...
set GROQ_API_KEY=...
set GEMINI_API_KEY=...
```

Hoặc chọn provider trong hộp thoại và nhập key. Key nhập trong app được lưu ở `data/settings.json` trên máy — đừng chia sẻ file này.

### Kiểm tra kết nối

Bấm **Kiểm tra kết nối** trong hộp thoại Cấu hình AI. Nếu OK, model trả về JSON hợp lệ.

## Không có AI thì sao?

App vẫn chạy bình thường:

- Tạo nhiều mẫu dùng bộ phong cách có sẵn (Tối giản, Neon, Retro, Couple, Dark, Trend, Clean, Cinematic, Anime, Street).
- Tự học hàng loạt dùng bộ lọc từ khóa/độ dài.
- Caption dùng câu mẫu dự phòng trong `capcut_tool/caption/templates.py`.

## Về Veo 3

Veo 3 là model **tạo video**, không viết được kế hoạch project CapCut. Cách dùng hợp lý:

1. Dùng Veo 3 tạo clip riêng (nếu cần).
2. Đưa clip vào CapCut làm nguyên liệu.
3. Học công thức từ project CapCut như bình thường.
4. Dùng prompt ở tab Tạo mẫu để sinh nhiều biến thể.

## Mẹo prompt hiệu quả

- Nêu rõ **số mẫu** và **tỉ lệ phong cách**, ví dụ `6 mẫu: 3 tối giản, 2 neon, 1 retro`.
- Nêu **đối tượng ảnh**: couple, du lịch, thú cưng, đồ ăn, street…
- Nêu **tone màu** và **tốc độ**: tối giản, neon, retro, điện ảnh, nhịp nhanh/chậm.
- Tránh yêu cầu bịa tên bài hát/ca sĩ; app không có thông tin đó.
- Prompt càng ngắn và cụ thể thì tiêu đề càng dễ dùng ngay.
