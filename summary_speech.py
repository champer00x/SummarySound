import os
import time
import json
import wave
from anyio import Path
from google import genai
# =========================
# GEMINI BATCH CONFIG
# =========================
GEMINI_MODEL = "gemini-3-flash-preview"
# Free API 5 requests/phút => tối thiểu 12 giây/request.
# Để an toàn, dùng 60 giây.
REQUEST_INTERVAL_SECONDS = 60
# Càng lớn thì càng ít request.
# Khuyên bắt đầu 1 giờ/request. Chạy ổn có thể tăng lên 2-4 giờ/request.
MAX_BATCH_DURATION_SECONDS = 60*60
# Nếu muốn cực ít request hơn, đổi thành:
# MAX_BATCH_DURATION_SECONDS = 4 * 60 * 60
# =========================
# WAV HELPERS
# =========================
def get_wav_duration_seconds(audio_path: str) -> float:
    with wave.open(audio_path, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)
def concat_wav_files(input_paths, output_path):
    """
    Ghép nhiều file WAV thành 1 file WAV.
    Các segment của bạn đều save từ cùng wav gốc nên format thường khớp.
    """
    if not input_paths:
        raise ValueError("Không có file WAV để ghép.")
    with wave.open(input_paths[0], "rb") as first_wav:
        params = first_wav.getparams()
    with wave.open(output_path, "wb") as output_wav:
        output_wav.setparams(params)
        for path in input_paths:
            with wave.open(path, "rb") as input_wav:
                current_params = input_wav.getparams()
                # So sánh channels, sample width, sample rate
                if current_params[:3] != params[:3]:
                    raise ValueError(
                        f"File WAV không cùng format: {path}\n"
                        f"Expected: {params[:3]}\n"
                        f"Got: {current_params[:3]}"
                    )
                frames = input_wav.readframes(input_wav.getnframes())
                output_wav.writeframes(frames)
    return output_path
def make_batches_by_duration(segment_paths, max_batch_duration_seconds):
    """
    Gom nhiều segment thành batch để giảm số request Gemini.
    Ví dụ:
    - Có 10 segment, mỗi segment 30 phút.
    - max_batch = 2 giờ.
    - Kết quả khoảng 3 batch thay vì 10 request.
    """
    batches = []
    current_batch = []
    current_duration = 0.0
    for path in segment_paths:
        duration = get_wav_duration_seconds(path)

        if current_batch and current_duration + duration > max_batch_duration_seconds:
            batches.append(current_batch)
            current_batch = [path]
            current_duration = duration
        else:
            current_batch.append(path)
            current_duration += duration

    if current_batch:
        batches.append(current_batch)

    return batches
# =========================
# GEMINI BATCH PROCESSING
# =========================
def transcribe_and_summarize_batch_with_gemini(
    client,
    batch_audio_path: str,
    batch_index: int,
    batch_segment_paths,
):
    """
    1 request Gemini cho cả batch audio.
    """
    segment_names = "\n".join(
        [
            f"- {idx + 1}. {os.path.basename(path)}"
            for idx, path in enumerate(batch_segment_paths)
        ]
    )
    print(f"\nUploading batch {batch_index}: {batch_audio_path}")
    print(f"Batch has {len(batch_segment_paths)} segment(s)")
    uploaded_file = client.files.upload(file=batch_audio_path)
    prompt = f"""
Bạn là trợ lý tiếng Việt chính xác.

File âm thanh này là batch #{batch_index}.
Nó được ghép tuần tự từ các segment sau:

{segment_names}

Nhiệm vụ:
1. Nghe và chép lại nội dung chính của audio.
2. Tóm tắt chi tiết nội dung.
3. Chia ý theo thứ tự xuất hiện trong audio.
4. Trích ra tên người, địa điểm, số liệu, deadline, nhiệm vụ, quyết định nếu có.
5. Nếu có đoạn nghe không rõ, ghi là [không rõ].
6. Không bịa nội dung không có trong audio.

Trả về đúng format sau:

BATCH_INDEX:
{batch_index}

TRANSCRIPT:
...

SUMMARY:
...

KEY_POINTS:
- ...

ACTION_ITEMS_OR_DECISIONS:
- ...

IMPORTANT_NAMES_NUMBERS_DATES:
- ...
"""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[prompt, uploaded_file],
    )

    return response.text


def process_segments_with_gemini(segment_paths, output_dir: str):
    """
    Thay thế hàm process_segments_withp_gemini cũ bằng hàm này.

    Mục tiêu:
    - Không gửi từng segment riêng lẻ.
    - Gom nhiều segment thành 1 batch WAV.
    - Mỗi batch chỉ tốn 1 request Gemini.
    - Có sleep 60s để tránh vượt 5 requests/phút.
    """

    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Không tìm thấy GOOGLE_API_KEY. "
            "Hãy tạo file .env có dòng: GOOGLE_API_KEY=your_key"
        )

    client = genai.Client(api_key=api_key)

    batch_dir = os.path.join(output_dir, "batches")
    os.makedirs(batch_dir, exist_ok=True)

    batches = make_batches_by_duration(
        segment_paths=segment_paths,
        max_batch_duration_seconds=MAX_BATCH_DURATION_SECONDS,
    )

    print("\n" + "=" * 80)
    print(f"Total segment files: {len(segment_paths)}")
    print(f"Total Gemini requests after batching: {len(batches)}")
    print(f"Max batch duration: {MAX_BATCH_DURATION_SECONDS / 3600:.2f} hours")
    print("=" * 80)

    all_results = []

    for batch_index, batch_segment_paths in enumerate(batches, start=1):
        try:
            batch_audio_path = os.path.join(
                batch_dir,
                f"batch_{batch_index:03d}.wav"
            )

            concat_wav_files(
                input_paths=batch_segment_paths,
                output_path=batch_audio_path,
            )

            batch_duration = get_wav_duration_seconds(batch_audio_path)

            print("\n" + "-" * 80)
            print(f"Batch {batch_index}/{len(batches)}")
            print(f"Segments in batch: {len(batch_segment_paths)}")
            print(f"Batch duration: {batch_duration / 60:.2f} minutes")
            print(f"Batch file: {batch_audio_path}")
            print("-" * 80)

            result_text = transcribe_and_summarize_batch_with_gemini(
                client=client,
                batch_audio_path=batch_audio_path,
                batch_index=batch_index,
                batch_segment_paths=batch_segment_paths,
            )

            result_path = os.path.join(
                output_dir,
                f"batch_{batch_index:03d}_result.txt"
            )

            with open(result_path, "w", encoding="utf-8") as f:
                f.write(result_text)

            print(f"\nSaved result: {result_path}")
            print("\nPreview:")
            print(result_text[:1500])
            print("\n" + "=" * 80)

            all_results.append({
                "batch": batch_index,
                "batch_audio_path": batch_audio_path,
                "batch_duration_seconds": batch_duration,
                "segments": batch_segment_paths,
                "result_path": result_path,
                "text": result_text,
            })

        except Exception as e:
            print(f"\nERROR batch {batch_index}: {e}")

            all_results.append({
                "batch": batch_index,
                "segments": batch_segment_paths,
                "error": str(e),
            })

        # Tránh quá 5 request/phút
        if batch_index < len(batches):
            print(
                f"\nSleeping {REQUEST_INTERVAL_SECONDS}s "
                "to avoid Gemini free API rate limit..."
            )
            time.sleep(REQUEST_INTERVAL_SECONDS)

    combined_json_path = os.path.join(output_dir, "all_batch_results.json")

    with open(combined_json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\nAll batch results saved to: {combined_json_path}")

    return all_results
from dotenv import load_dotenv
import glob

load_dotenv()
INPUT_PATH = r"C:\Users\ADMIN\RAG_TEST\input.mp4"
FILE_NAME = Path(INPUT_PATH).stem
OUTPUT_DIR = os.path.join(r"C:\Users\ADMIN\RAG_TEST\segments", FILE_NAME)
#OUTPUT_DIR = r"C:\Users\ADMIN\RAG_TEST\SummarySound\segments" #bỏ comment nếu muốn dùng segments để test với batches có sẵn

if __name__ == "__main__":
    segment_paths = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "segment_*.wav"))
    )

    # Bỏ qua file không phải segment gốc nếu có
    segment_paths = [
        p for p in segment_paths
        if "_result" not in os.path.basename(p)
        and "batch_" not in os.path.basename(p)
        and "_converted" not in os.path.basename(p)
    ]

    print(f"Found {len(segment_paths)} segment file(s).")

    if not segment_paths:
        raise RuntimeError(
            "Không tìm thấy file segment_*.wav trong thư mục segments. "
            "Bạn cần chạy bước cắt audio trước."
            "Hãy kiểm tra lại thư mục input xem đã có file output tương ứng chưa."
        )

    process_segments_with_gemini(
        segment_paths=segment_paths,
        output_dir=OUTPUT_DIR
    )