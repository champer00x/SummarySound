import os
from pathlib import Path
import subprocess
from silero_vad import load_silero_vad, read_audio, get_speech_timestamps, save_audio
# =========================
# CONFIG
# =========================
SAMPLING_RATE = 16000
INPUT_PATH = r"C:\Users\ADMIN\RAG_TEST\input.mp4"

BASE_OUTPUT_DIR = r"C:\Users\ADMIN\RAG_TEST\segments"

FILE_NAME = Path(INPUT_PATH).stem
OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, FILE_NAME)
MIN_SPEECH_DURATION = 0.30
PADDING = 0.20
MERGE_SMALL_GAP = 0.50
MIN_GAP_TO_CUT = 10.0
MIN_LENGTH_OF_SEGMENT = 45 * 60
TARGET_LENGTH_OF_SEGMENT = 52 * 60
MAX_LENGTH_OF_SEGMENT = 60 * 60
# =========================
# CONVERT INPUT
# =========================

def ensure_wav_16k_mono(input_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    converted_path = os.path.join(output_dir, "_converted_16k_mono.wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", str(SAMPLING_RATE),
        converted_path,
    ]

    subprocess.run(cmd, check=True)
    return converted_path


# =========================
# VAD CLEANING
# =========================

def preprocess_vad_timestamps(
    timestamps,
    total_duration,
    min_speech_duration=MIN_SPEECH_DURATION,
    padding=PADDING,
    merge_small_gap=MERGE_SMALL_GAP,
):
    if not timestamps:
        return []

    cleaned = []

    for ts in timestamps:
        start = float(ts["start"])
        end = float(ts["end"])

        if end - start < min_speech_duration:
            continue

        start = max(0.0, start - padding)
        end = min(total_duration, end + padding)

        cleaned.append({"start": start, "end": end})

    if not cleaned:
        return []

    cleaned.sort(key=lambda x: x["start"])

    merged = [cleaned[0].copy()]

    for ts in cleaned[1:]:
        prev = merged[-1]
        gap = ts["start"] - prev["end"]

        if gap <= merge_small_gap:
            prev["end"] = max(prev["end"], ts["end"])
        else:
            merged.append(ts.copy())

    return merged


# =========================
# BUILD BEAUTIFUL SEGMENTS
# =========================

def build_beautiful_segments(
    timestamps,
    min_segment_duration=MIN_LENGTH_OF_SEGMENT,
    target_segment_duration=TARGET_LENGTH_OF_SEGMENT,
    max_segment_duration=MAX_LENGTH_OF_SEGMENT,
    min_gap_to_cut=MIN_GAP_TO_CUT,
):
    if not timestamps:
        return []

    segments = []
    n = len(timestamps)
    start_idx = 0

    while start_idx < n:
        chunk_start = timestamps[start_idx]["start"]

        best_cut_idx = None
        best_score = None
        fallback_cut_idx = None

        for i in range(start_idx, n):
            chunk_end = timestamps[i]["end"]
            duration = chunk_end - chunk_start

            if duration <= max_segment_duration:
                fallback_cut_idx = i

            if duration >= min_segment_duration:
                is_last = i == n - 1

                if is_last:
                    gap = 999999
                else:
                    gap = timestamps[i + 1]["start"] - timestamps[i]["end"]

                if gap >= min_gap_to_cut or is_last:
                    score = abs(duration - target_segment_duration)

                    if not is_last:
                        score -= min(gap, 60.0) * 0.05

                    if best_score is None or score < best_score:
                        best_score = score
                        best_cut_idx = i

            if duration > max_segment_duration:
                break

        if best_cut_idx is not None:
            cut_idx = best_cut_idx
        elif fallback_cut_idx is not None:
            cut_idx = fallback_cut_idx
        else:
            cut_idx = start_idx

        segments.append({
            "start": chunk_start,
            "end": timestamps[cut_idx]["end"],
        })

        start_idx = cut_idx + 1

    # Chỉ gộp đoạn cuối nếu không vượt max
    if len(segments) >= 2:
        last_duration = segments[-1]["end"] - segments[-1]["start"]
        merged_duration = segments[-1]["end"] - segments[-2]["start"]

        if last_duration < min_segment_duration and merged_duration <= max_segment_duration+60.0*10:
            segments[-2]["end"] = segments[-1]["end"]
            segments.pop()

    return segments


# =========================
# SAVE SEGMENTS
# =========================

def save_segments(wav, segments, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    output_paths = []

    for i, seg in enumerate(segments, start=1):
        start_sample = int(seg["start"] * SAMPLING_RATE)
        end_sample = int(seg["end"] * SAMPLING_RATE)

        audio_segment = wav[start_sample:end_sample]

        output_path = os.path.join(output_dir, f"segment_{i:03d}.wav")

        save_audio(
            output_path,
            audio_segment,
            sampling_rate=SAMPLING_RATE,
        )

        duration = seg["end"] - seg["start"]

        print(
            f"Saved: {output_path} | "
            f"{seg['start']:.2f}s -> {seg['end']:.2f}s | "
            f"{duration / 60:.2f} min"
        )

        output_paths.append(output_path)

    return output_paths


# =========================
# MAIN
# =========================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Input:", INPUT_PATH)
    print("Output dir:", OUTPUT_DIR)

    print("\nConverting input to WAV 16k mono...")
    wav_path = ensure_wav_16k_mono(INPUT_PATH, OUTPUT_DIR)

    print("\nReading WAV...")
    wav = read_audio(wav_path, sampling_rate=SAMPLING_RATE)

    total_duration = len(wav) / SAMPLING_RATE

    print(f"Total duration: {total_duration / 60:.2f} min")

    print("\nLoading Silero VAD...")
    model = load_silero_vad()

    print("\nRunning VAD...")
    raw_timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=SAMPLING_RATE,
        return_seconds=True,
    )

    print(f"Raw VAD segments: {len(raw_timestamps)}")

    clean_timestamps = preprocess_vad_timestamps(
        raw_timestamps,
        total_duration=total_duration,
    )

    print(f"Cleaned VAD segments: {len(clean_timestamps)}")

    final_segments = build_beautiful_segments(clean_timestamps)

    print("\nFinal segments:")
    for i, seg in enumerate(final_segments, start=1):
        duration = seg["end"] - seg["start"]
        print(
            f"{i:03d}: "
            f"{seg['start']:.2f}s -> {seg['end']:.2f}s | "
            f"{duration / 60:.2f} min"
        )

    print("\nSaving segments...")
    save_segments(wav, final_segments, OUTPUT_DIR)

    print("\nDone.")


if __name__ == "__main__":
    main()