# SummarySound

Dự án dùng để xử lý audio/video dài:

```text
YouTube / Video / Audio
→ Convert WAV 16k mono
→ Silero VAD
→ Cắt thành các segment đẹp
→ Batch nhiều segment
→ Gemini transcript + summary
```

---

## 1. Cấu trúc thư mục hiện tại

```text
SummarySound/
│
├── segments/(thư mục test)
│   └── <file_name>/
│       ├── _converted_16k_mono.wav
│       ├── segment_001.wav
│       ├── segment_002.wav
│       ├── ...
│       ├── batches/
│       │   ├── batch_001.wav
│       │   └── ...
│       ├── batch_001_result.txt
│       └── all_batch_results.json
│
├── segments1/(thư mục test, cấu trúc tương tự segments)
│   
│
├── youtube_downloads/
│   └── file tải từ YouTube
│
├── 18t4 BC công nghệ.m4a
│   └── audio input hiện tại
│
├── input_16k.wav
│   └── file WAV test
│
├── create_segments.py
│   └── script cắt audio bằng Silero VAD
│
├── summary_speech.py
│   └── script gửi segment/batch lên Gemini để transcript + summary
│
└── README.md
```

---

## 2. Mục đích từng file chính

### `create_segments.py`

File này dùng để:

```text
Input audio/video gốc
→ convert sang WAV 16k mono
→ chạy Silero VAD
→ cắt audio thành các đoạn segment_001.wav, segment_002.wav...
```

Output mặc định nên được lưu theo dạng:

```text
segments/<file_name>/
```

Ví dụ input:

```text
18t4 BC công nghệ.m4a
```

thì output nên là:

```text
segments/18t4 BC công nghệ/
├── _converted_16k_mono.wav
├── segment_001.wav
├── segment_002.wav
└── ...
```

---

### `summary_speech.py`

File này dùng để:

```text
Đọc các file segment_*.wav
→ gom nhiều segment thành batch
→ gửi batch lên Gemini
→ lưu transcript + summary
```

Output:

```text
segments/<file_name>/
├── batches/
│   ├── batch_001.wav
│   └── ...
├── batch_001_result.txt
├── batch_002_result.txt
└── all_batch_results.json
```

---

## 3. Logic chia segment bằng Silero VAD

Silero VAD trả về nhiều đoạn speech nhỏ:

```python
[
    {"start": 10.2, "end": 15.5},
    {"start": 16.0, "end": 20.0},
]
```

Các đoạn này chưa phải đoạn cuối cùng để gửi Gemini. Sau khi lấy timestamp, script xử lý thêm.

### Bước 1: bỏ speech quá ngắn

```python
MIN_SPEECH_DURATION = 0.30
```

Mục đích: bỏ nhiễu, tiếng click, tiếng động ngắn.

---

### Bước 2: padding đầu/cuối

```python
PADDING = 0.20
```

Ví dụ:

```text
Gốc:      10.0s → 15.0s
Sau pad:   9.8s → 15.2s
```

Mục đích: tránh mất âm đầu/cuối câu.

---

### Bước 3: merge speech gần nhau

```python
MERGE_SMALL_GAP = 0.50
```

Nếu hai đoạn speech cách nhau dưới `0.5s` thì gộp lại.

Ví dụ:

```text
[10.0 - 15.0] gap 0.3s [15.3 - 20.0]
```

sẽ thành:

```text
[10.0 - 20.0]
```

---

### Bước 4: tạo segment đẹp

Config hiện tại:

```python
MIN_GAP_TO_CUT = 10.0

MIN_LENGTH_OF_SEGMENT = 45 * 60
TARGET_LENGTH_OF_SEGMENT = 52 * 60
MAX_LENGTH_OF_SEGMENT = 60 * 60
```

Ý nghĩa:

```text
- Chỉ ưu tiên cắt ở khoảng lặng >= 10 giây
- Segment tối thiểu khoảng 45 phút
- Ưu tiên segment gần 52 phút
- Không để segment vượt 60 phút
```

Logic:

```text
Bắt đầu từ speech đầu tiên
→ cộng dần speech tiếp theo
→ nếu chưa đủ 45 phút thì chưa cắt
→ nếu đã đủ 45 phút thì tìm silence >= 10 giây để cắt
→ nếu có nhiều điểm cắt thì chọn điểm gần 52 phút nhất
→ nếu sắp vượt 60 phút thì buộc cắt ở boundary gần nhất trước max
```

Lưu ý quan trọng:

```text
Không được gộp đoạn cuối nếu việc gộp làm vượt MAX_LENGTH_OF_SEGMENT+60.0*10.
```
=> Không làm cho file lên quá dài >70p, cũng không có file quá ngắn <25p

---

## 4. Logic batch Gemini

Gemini free API có giới hạn request, nên không nên gửi từng segment riêng lẻ.
Thay vì:
```text
segment_001.wav → request 1
segment_002.wav → request 2
segment_003.wav → request 3
```
script sẽ gom batch:
```text
segment_001.wav + segment_002.wav → batch_001.wav → request 1
segment_003.wav + segment_004.wav → batch_002.wav → request 2
```
Config hiện tại:
```python
MAX_BATCH_DURATION_SECONDS = 60 * 60
REQUEST_INTERVAL_SECONDS = 60
```
Ý nghĩa:
```text
- Mỗi batch tối đa 60 phút audio
- Nghỉ 60 giây giữa mỗi request
```
Nếu muốn ít request hơn:
```python
MAX_BATCH_DURATION_SECONDS = 2 * 60 * 60
```
hoặc:
```python
MAX_BATCH_DURATION_SECONDS = 4 * 60 * 60
```
Nhưng batch càng dài thì request càng nặng, dễ timeout hơn và output rất dài, đặt biệt độ chính xác của model giảm khi input quá dài.
---
## 5. Cách dùng
### Bước 1: tạo virtual environment
```powershell
cd C:\Users\ADMIN\SummarySound
python -m venv .venv
```
Kích hoạt:
```powershell
.\.venv\Scripts\Activate.ps1
```
Nếu PowerShell báo lỗi policy:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
rồi chạy lại:
```powershell
.\.venv\Scripts\Activate.ps1
```
---
### Bước 2: cài thư viện
```powershell
python -m pip install -U pip
python -m pip install silero-vad google-genai python-dotenv yt-dlp ffmpeg-python
```
Cần cài FFmpeg trên máy và đảm bảo chạy được:

```powershell
ffmpeg -version
```

---

### Bước 3: tạo file `.env`
Tạo file `.env` trong thư mục project:
```env
GOOGLE_API_KEY=YOUR_API_KEY
```
---
### Bước 4: chạy cắt audio bằng VAD
Mở `create_segments.py`, sửa input:
```python
INPUT_PATH = r"C:\Users\ADMIN\SummarySound\18t4 BC công nghệ.m4a"
```
Nên lưu output theo tên file:
```python
from pathlib import Path
BASE_OUTPUT_DIR = r"C:\Users\ADMIN\SummarySound\segments"
FILE_NAME = Path(INPUT_PATH).stem
OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, FILE_NAME)
```
Chạy:
```powershell
python create_segments.py
```
Sau khi chạy xong sẽ có:

```text
segments/<file_name>/
├── _converted_16k_mono.wav
├── segment_001.wav
├── segment_002.wav
└── ...
```
---
### Bước 5: chạy Gemini summary

Mở `summary_speech.py`, sửa:

```python
OUTPUT_DIR = r"C:\Users\ADMIN\SummarySound\segments\<file_name>"
`
Ví dụ:

```python
OUTPUT_DIR = r"C:\Users\ADMIN\SummarySound\segments\18t4 BC công nghệ"
```

Chạy:

```powershell
python summary_speech.py
```

Kết quả:

```text
segments/<file_name>/
├── batches/
│   ├── batch_001.wav
│   └── ...
├── batch_001_result.txt
├── batch_002_result.txt
└── all_batch_results.json
```

---

## 6. Workflow chuẩn

```text
1. Đặt file audio/video gốc vào thư mục project
2. Sửa INPUT_PATH trong create_segments.py
3. Chạy: python create_segments.py
4. Kiểm tra thư mục segments/<file_name>/
5. Sửa OUTPUT_DIR trong summary_speech.py
6. Chạy: python summary_speech.py
7. Đọc kết quả trong batch_001_result.txt hoặc all_batch_results.json
```

---

## 7. Gợi ý cấu hình
### Cấu hình tối ưu chính xác
```python
MIN_GAP_TO_CUT = 10.0

MIN_LENGTH_OF_SEGMENT = 20 * 60
TARGET_LENGTH_OF_SEGMENT = 27 * 60
MAX_LENGTH_OF_SEGMENT = 35 * 60

MAX_BATCH_DURATION_SECONDS = 60 * 60
REQUEST_INTERVAL_SECONDS = 60
```

### Cấu hình an toàn

```python
MIN_GAP_TO_CUT = 10.0

MIN_LENGTH_OF_SEGMENT = 45 * 60
TARGET_LENGTH_OF_SEGMENT = 52 * 60
MAX_LENGTH_OF_SEGMENT = 60 * 60

MAX_BATCH_DURATION_SECONDS = 60 * 60
REQUEST_INTERVAL_SECONDS = 60
```

### Cấu hình ít request Gemini hơn

```python
MAX_BATCH_DURATION_SECONDS = 2 * 60 * 60
REQUEST_INTERVAL_SECONDS = 60
```
---

## 8. Lỗi thường gặp

### Không tìm thấy `segment_*.wav`

Nghĩa là chưa chạy `create_segments.py` hoặc sai `OUTPUT_DIR`.

Kiểm tra:

```text
segments/<file_name>/segment_001.wav
```

---

### `ffmpeg` không chạy

Kiểm tra:

```powershell
ffmpeg -version
```

Nếu lỗi, cần cài FFmpeg và thêm vào PATH.

---

### Không tìm thấy `GOOGLE_API_KEY`

Kiểm tra file `.env`:

```env
GOOGLE_API_KEY=YOUR_API_KEY
```

---

### Gemini bị rate limit
Tăng:
```python
REQUEST_INTERVAL_SECONDS = 60
```
hoặc giảm số request bằng cách tăng:
```python
MAX_BATCH_DURATION_SECONDS = 2 * 60 * 60
```
---
### Batch quá dài, request dễ lỗi
Giảm:

```python
MAX_BATCH_DURATION_SECONDS = 60 * 60
```

hoặc:

```python
MAX_BATCH_DURATION_SECONDS = 30 * 60
```
