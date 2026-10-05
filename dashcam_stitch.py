#!/usr/bin/env python3
"""Group front dash-cam clips and render music-reactive, branded MP4 drives."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FRONT_NAME = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2})_f\.ts$", re.IGNORECASE
)
SUPPORTED_AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg"}
DRAW_FONT = r"fontfile='C\:/Windows/Fonts/arial.ttf':" if os.name == "nt" else "font=Sans:"


@dataclass(frozen=True)
class Clip:
    path: Path
    started: dt.datetime


@dataclass(frozen=True)
class Track:
    path: Path
    duration: float
    title: str
    artist: str


def find_ffmpeg(explicit: Path | None) -> str:
    if explicit:
        if not explicit.is_file():
            raise RuntimeError(f"FFmpeg not found: {explicit}")
        return str(explicit)
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    matches = sorted(winget_root.glob("Gyan.FFmpeg_*/*/bin/ffmpeg.exe"), reverse=True)
    if matches:
        return str(matches[0])
    raise RuntimeError(
        "FFmpeg is not installed or not on PATH. Install it with: "
        "winget install --id Gyan.FFmpeg --exact"
    )


def probe_duration(ffmpeg: str, path: Path) -> float | None:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    completed = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        value = float(completed.stdout.strip())
        return value if completed.returncode == 0 and value > 0 else None
    except ValueError:
        return None


def probe_track(ffmpeg: str, path: Path) -> Track | None:
    """Read duration and common title/artist tags, with useful filename fallbacks."""
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    completed = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            "format=duration:format_tags=title,artist,album_artist",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        info = json.loads(completed.stdout)["format"]
        duration = float(info["duration"])
        tags = {str(k).lower(): str(v).strip() for k, v in info.get("tags", {}).items()}
        if completed.returncode or duration <= 0:
            return None
        fallback_title, separator, fallback_artist = path.stem.rpartition(" - ")
        title = tags.get("title") or (fallback_title if separator else path.stem)
        artist = (
            tags.get("artist") or tags.get("album_artist")
            or (fallback_artist if separator else "Unknown artist")
        )
        return Track(path, duration, title, artist)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def build_music_playlist(
    ffmpeg: str, music_dir: Path, crossfade: float, temporary_dir: Path, token: str, runner=None
) -> tuple[Path, list[Track], float, float]:
    """Build one shuffled, crossfaded playlist. The final mux loops this exact order."""
    candidates = sorted(
        path for path in music_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO
    )
    if not candidates:
        raise RuntimeError(f"No supported music files found in {music_dir}")
    random.SystemRandom().shuffle(candidates)
    valid: list[Track] = []
    for path in candidates:
        track = probe_track(ffmpeg, path)
        if track is None:
            print(f"WARNING: skipping unreadable music track: {path.name}", file=sys.stderr)
        else:
            valid.append(track)
    if not valid:
        raise RuntimeError(f"No readable music files found in {music_dir}")

    fade = min(crossfade, min(track.duration for track in valid) / 2)
    fade = max(fade, 0.1)
    filter_lines: list[str] = []
    for index, track in enumerate(valid):
        fade_in = f",afade=t=in:st=0:d={fade:.3f}" if index == 0 else ""
        filter_lines.append(
            f"[{index}:a:0]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo{fade_in}[a{index}]"
        )
    current = "a0"
    for index in range(1, len(valid)):
        output = f"mix{index}"
        filter_lines.append(
            f"[{current}][a{index}]acrossfade=d={fade:.3f}:c1=tri:c2=tri[{output}]"
        )
        current = output
    playlist_duration = sum(track.duration for track in valid) - fade * (len(valid) - 1)
    fade_start = max(playlist_duration - fade, 0)
    filter_lines.append(f"[{current}]afade=t=out:st={fade_start:.3f}:d={fade:.3f}[outa]")

    filter_graph = ";".join(filter_lines)
    playlist_path = temporary_dir / f".{token}.shuffled_playlist.m4a"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    for track in valid:
        command.extend(["-i", str(track.path)])
    command.extend(
        [
            "-filter_complex", filter_graph, "-map", "[outa]",
            "-c:a", "aac", "-b:a", "192k", "-y", str(playlist_path),
        ]
    )
    print(f"MUSIC SHUFFLE ({len(valid)} tracks; repeats in this order if needed):")
    for number, track in enumerate(valid, 1):
        print(f"  {number:02}. {track.artist} — {track.title} ({track.path.name})")
    completed = (runner or subprocess.run)(command)
    if completed.returncode or not playlist_path.is_file():
        raise RuntimeError(f"Music playlist creation failed with exit code {completed.returncode}")
    return playlist_path, valid, fade, playlist_duration


def filter_text(value: str) -> str:
    """Escape literal text for FFmpeg's drawtext filter."""
    return (
        value.replace("\\", r"\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace("[", r"\[")
        .replace("]", r"\]")
    )


def filter_path(path: Path) -> str:
    """Escape an absolute filename used as an FFmpeg filter option."""
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def video_duration(ffmpeg: str, drive: list[Clip]) -> float:
    durations = [probe_duration(ffmpeg, clip.path) for clip in drive]
    if any(value is None for value in durations):
        raise RuntimeError("Could not determine the duration of every dashcam clip")
    return sum(value for value in durations if value is not None)


def probe_dimensions(ffmpeg: str, path: Path) -> tuple[int, int]:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                             "stream=width,height", "-of", "json", str(path)], capture_output=True, timeout=15)
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        if result.returncode or width <= 0 or height <= 0:
            raise ValueError
        return width, height
    except (KeyError, IndexError, ValueError):
        raise RuntimeError("Could not determine source video dimensions") from None


TARGET_2GB_BYTES = 1_920_000_000  # 1.92 GB (~1.788 GiB) provides a safe ~80 MB buffer under 2.00 GB


def choose_video_encoder(ffmpeg: str, requested: str) -> tuple[str, list[str]]:
    if requested == "libx264":
        return requested, ["-preset", "fast", "-crf", "19"]
    if requested == "h264_nvenc":
        return requested, ["-preset", "p5", "-cq", "19", "-b:v", "0"]
    # CPU encoding is slower but avoids driver-level 4K NVENC memory/access crashes.
    return "libx264", ["-preset", "fast", "-crf", "19"]


def calculate_target_encoding(
    duration: float, encoder: str, max_bytes: int = TARGET_2GB_BYTES
) -> tuple[int | None, int, list[str]]:
    """Calculate optimal resolution (height), audio bitrate (kbps), and encoder flags

    to maximize quality while strictly keeping the file size under max_bytes.
    """
    dur = max(duration, 1.0)
    total_bitrate_bps = (max_bytes * 8) / dur
    total_kbps = int(total_bitrate_bps / 1000)

    if total_kbps >= 1500:
        audio_kbps = 192
    else:
        audio_kbps = 128
    video_kbps = max(total_kbps - audio_kbps, 300)

    # Resolution ladder based on available video bitrate
    if video_kbps >= 16000:
        scale_height = None  # Full 4K (3840x2160)
    elif video_kbps >= 8000:
        scale_height = 1440  # 1440p (2560x1440)
    elif video_kbps >= 1600:
        scale_height = 1080  # 1080p (1920x1080)
    else:
        scale_height = 720   # 720p (1280x720)

    # If bitrate budget is generous enough that CRF 19 naturally fits well under 2 GB,
    # use CRF 19 with a maxrate cap to avoid unnecessary file bloating.
    if scale_height is None and video_kbps >= 22000:
        capped_maxrate = min(video_kbps, 60000)
        bufsize = min(capped_maxrate * 2, 120000)
        if encoder == "h264_nvenc":
            encoder_options = [
                "-preset", "p5", "-cq", "19",
                "-maxrate", f"{capped_maxrate}k", "-bufsize", f"{bufsize}k"
            ]
        else:
            encoder_options = [
                "-preset", "fast", "-crf", "19",
                "-maxrate", f"{capped_maxrate}k", "-bufsize", f"{bufsize}k"
            ]
    else:
        maxrate = min(int(video_kbps * 1.25), 60000)
        bufsize = min(video_kbps * 2, 120000)
        if encoder == "h264_nvenc":
            encoder_options = [
                "-preset", "p5", "-b:v", f"{video_kbps}k",
                "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"
            ]
        else:
            encoder_options = [
                "-preset", "fast", "-b:v", f"{video_kbps}k",
                "-maxrate", f"{maxrate}k", "-bufsize", f"{bufsize}k"
            ]

    return scale_height, audio_kbps, encoder_options


def presentation_filter(
    tracks: list[Track], crossfade: float, playlist_duration: float,
    duration: float, label_paths: list[Path], route_path: Path | None,
    channel_path: Path, end_card: float,
    scale_height: int | None = None,
    source_dimensions: tuple[int, int] = (3840, 2160),
    timeline_offset: float = 0,
    final_segment: bool = True,
) -> str:
    """Create branding, a music-driven EQ, timed track labels, and route text."""
    outro_start = max(duration - end_card, 0.0)
    ratio = min(source_dimensions[0] / 3840, source_dimensions[1] / 2160)
    def px(value: int) -> int:
        return max(1, round(value * ratio))
    eq_width, eq_height = px(1100), px(280)
    opening = "between(t,0,3)" if timeline_offset == 0 else "0"
    ending = f"gte(t,{outro_start:.3f})" if final_segment else "0"
    fade_in = ",fade=t=in:st=0:d=3" if timeline_offset == 0 else ""
    graph: list[str] = [
        # One 4K video branch keeps peak RAM bounded. The opening fades up while blurred;
        # the end-card blur turns on for the standard 20-second closing window.
        f"[0:v:0]setpts=PTS-STARTPTS,gblur=sigma={px(24)}:steps=1:"
        f"enable='{opening}+{ending}'{fade_in}[vblur]",
        "[1:a:0]asplit=2[aout][visualaudio]",
        f"[visualaudio]showfreqs=s={eq_width}x{eq_height}:mode=bar:ascale=cbrt:fscale=log:"
        "colors=0x00e5ff|0xff2bd6:win_size=4096:overlap=0.8,"
        "format=rgba,colorchannelmixer=aa=0.82[eq]",
        f"[vblur][eq]overlay=x={px(70)}:y=H-h-{px(150)}:shortest=1[v0]",
    ]
    current = "v0"
    start = 0.0
    for index, track in enumerate(tracks):
        # Switch the label halfway through a crossfade, where the incoming song takes over.
        label_start = max(start - (crossfade / 2 if index else 0), 0)
        next_start = start + track.duration - (crossfade if index < len(tracks) - 1 else 0)
        label_end = next_start - (crossfade / 2 if index < len(tracks) - 1 else 0)
        output = f"v{index + 1}"
        graph.append(
            f"[{current}]drawtext={DRAW_FONT}textfile='{filter_path(label_paths[index])}':"
            f"reload=0:expansion=none:fontcolor=white:fontsize={px(48)}:"
            f"borderw={px(3)}:bordercolor=black@0.8:x={px(80)}:y=h-{px(125)}:"
            f"enable='between(mod(t{f'+{timeline_offset:.3f}' if timeline_offset else ''},{playlist_duration:.3f}),{label_start:.3f},{label_end:.3f})'[{output}]"
        )
        current = output
        start = next_start
    if route_path:
        output = "vroute"
        graph.append(
            f"[{current}]drawtext={DRAW_FONT}textfile='{filter_path(route_path)}':"
            "reload=0:expansion=none:"
            f"fontcolor=white:fontsize={px(46)}:borderw={px(3)}:bordercolor=black@0.8:"
            f"x=w-tw-{px(80)}:y=h-th-{px(70)}[{output}]"
        )
        current = output
    final_out = "vout" if scale_height is None else "vpre_scale"
    graph.append(
        f"[{current}]drawtext={DRAW_FONT}textfile='{filter_path(channel_path)}':"
        f"reload=0:expansion=none:fontcolor=white:fontsize={px(104)}:"
        f"borderw={px(5)}:bordercolor=black@0.65:x=(w-tw)/2:y=(h-th)/2:"
        f"enable='{opening}+{ending}'[{final_out}]"
    )
    if scale_height is not None:
        graph.append(f"[vpre_scale]scale=-2:{scale_height}:flags=lanczos[vout]")
    return ";".join(graph)


def scan_clips(source: Path) -> list[Clip]:
    clips: list[Clip] = []
    for path in source.glob("*_f.ts"):
        match = FRONT_NAME.match(path.name)
        if match:
            clips.append(
                Clip(path.resolve(), dt.datetime.strptime(match.group("stamp"), "%Y-%m-%d_%H_%M_%S"))
            )
    return sorted(clips, key=lambda clip: (clip.started, clip.path.name))


def group_drives(clips: list[Clip], gap: dt.timedelta) -> list[list[Clip]]:
    drives: list[list[Clip]] = []
    for clip in clips:
        if not drives or clip.started - drives[-1][-1].started > gap:
            drives.append([clip])
        else:
            drives[-1].append(clip)
    return drives


def ffconcat_quote(path: Path) -> str:
    # FFmpeg concat files use single-quoted strings; backslash escapes a quote.
    return "'" + str(path).replace("\\", "/").replace("'", "'\\''") + "'"


def output_name(drive: list[Clip], target_mode: str = "original") -> str:
    start = drive[0].started.strftime("%Y-%m-%d_%H-%M-%S")
    if target_mode == "2gb":
        return f"Drive_{start}_2GB.mp4"
    return f"Drive_{start}.mp4"


def stitch(
    ffmpeg: str,
    drive: list[Clip],
    destination: Path,
    overwrite: bool,
    music_dir: Path,
    crossfade: float,
    route_info: str,
    channel_title: str,
    end_card: float,
    video_encoder: str,
    target_size: str = "original",
) -> str:
    output = destination / output_name(drive, target_size)
    if output.exists() and not overwrite:
        newest_source = max(clip.path.stat().st_mtime for clip in drive)
        if output.stat().st_mtime >= newest_source:
            print(f"SKIP up-to-date {output.name}")
            return "existing"
        print(f"REFRESH {output.name}: newer clips are present")
    partial = output.with_name(output.name + ".part.mp4")
    token = f"{output.stem}.{os.getpid()}"
    manifest_path = destination / f".{token}.drive.ffconcat"
    playlist_path = destination / f".{token}.shuffled_playlist.m4a"
    text_paths: list[Path] = []
    try:
        with manifest_path.open("w", encoding="utf-8") as manifest:
            manifest.write("ffconcat version 1.0\n")
            for clip in drive:
                manifest.write(f"file {ffconcat_quote(clip.path)}\n")
        playlist_path, tracks, actual_fade, playlist_duration = build_music_playlist(
            ffmpeg, music_dir, crossfade, destination, token
        )
        duration = video_duration(ffmpeg, drive)
        source_dimensions = probe_dimensions(ffmpeg, drive[0].path)
        encoder, default_encoder_options = choose_video_encoder(ffmpeg, video_encoder)
        if target_size == "2gb":
            scale_height, audio_kbps, encoder_options = calculate_target_encoding(
                duration, encoder, TARGET_2GB_BYTES
            )
            if scale_height is not None and scale_height >= source_dimensions[1]:
                scale_height = None  # A size target must never upscale the source.
            res_label = f"scaled to {scale_height}p" if scale_height else "4K unscaled"
            print(
                f"TARGET < 2 GB: duration {duration:.1f}s, resolution {res_label}, "
                f"audio {audio_kbps}k, encoder options {encoder_options}"
            )
        else:
            scale_height = None
            audio_kbps = 192
            encoder_options = default_encoder_options

        label_paths: list[Path] = []
        for index, track in enumerate(tracks):
            label_path = destination / f".{token}.track-{index}.txt"
            label_path.write_text(f"{track.title}  •  {track.artist}", encoding="utf-8")
            label_paths.append(label_path)
        channel_path = destination / f".{token}.channel.txt"
        channel_path.write_text(channel_title, encoding="utf-8")
        route_path = None
        if route_info:
            route_path = destination / f".{token}.route.txt"
            route_path.write_text(route_info, encoding="utf-8")
        text_paths = [*label_paths, channel_path, *([route_path] if route_path else [])]
        filter_graph = presentation_filter(
            tracks, actual_fade, playlist_duration, duration,
            label_paths, route_path, channel_path, min(end_card, duration),
            scale_height=scale_height,
            source_dimensions=source_dimensions,
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-stats",
            "-f", "concat", "-safe", "0", "-i", str(manifest_path),
            "-stream_loop", "-1", "-i", str(playlist_path),
            "-filter_complex", filter_graph,
            "-map", "[vout]", "-map", "[aout]", "-c:v", encoder,
            *encoder_options, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-shortest", "-movflags", "+faststart",
            "-y", str(partial),
        ]
        print(f"STITCH {len(drive)} clips -> {output.name}")
        completed = subprocess.run(command)
        if completed.returncode:
            raise RuntimeError(f"FFmpeg failed with exit code {completed.returncode}")
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg produced no usable output for {output.name}")
        output_size = partial.stat().st_size
        print(
            f"FINISHED {output.name}: {output_size} bytes "
            f"({output_size / (1024 * 1024):.1f} MiB / {output_size / 1_000_000_000:.2f} GB)"
        )
        if target_size == "2gb" and output_size > 2_000_000_000:
            print(f"WARNING: output size {output_size} bytes exceeded 2 GB!", file=sys.stderr)
        partial.replace(output)
        return "created"
    finally:
        manifest_path.unlink(missing_ok=True)
        playlist_path.unlink(missing_ok=True)
        for text_path in text_paths:
            text_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parent / "Transfers",
        help="directory containing downloaded *_f.ts clips (default: %(default)s)"
    )
    parser.add_argument("--route-info", default="", help="optional persistent bottom-right route caption")
    parser.add_argument("--channel-title", default="My Drive", help="intro/outro title")
    parser.add_argument(
        "--end-card-seconds", type=float, default=20.0,
        help="blurred YouTube-style ending duration (default: 20)"
    )
    parser.add_argument(
        "--video-encoder", choices=("auto", "h264_nvenc", "libx264"), default="auto",
        help="overlay rendering encoder (default: auto uses reliable CPU H.264)"
    )
    parser.add_argument(
        "--target-size", choices=("original", "2gb"), default="original",
        help="output size profile: original (4K CRF 19) or 2gb (highest quality under 2 GB; default: %(default)s)"
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parent / "Transfers" / "Drives",
        help="MP4 output directory (default: %(default)s)"
    )
    parser.add_argument(
        "--gap-minutes", type=float, default=5.0,
        help="start a new drive when timestamps are farther apart (default: 5)"
    )
    parser.add_argument("--ffmpeg", type=Path, help="explicit path to ffmpeg.exe")
    parser.add_argument(
        "--music-dir", type=Path, default=Path(__file__).resolve().parent / "Music",
        help="music folder rescanned for every MP4 (default: %(default)s)"
    )
    parser.add_argument(
        "--crossfade-seconds", type=float, default=3.0,
        help="music fade/crossfade duration (default: 3)"
    )
    parser.add_argument("--stitch", action="store_true", help="create MP4s; default previews groups")
    parser.add_argument("--overwrite", action="store_true", help="replace matching local MP4s")
    parser.add_argument(
        "--drive-start",
        help="process only the drive starting at YYYY-MM-DD_HH-MM-SS"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.gap_minutes <= 0:
        raise SystemExit("--gap-minutes must be positive")
    if args.crossfade_seconds <= 0:
        raise SystemExit("--crossfade-seconds must be positive")
    if args.end_card_seconds <= 0:
        raise SystemExit("--end-card-seconds must be positive")
    clips = scan_clips(args.source)
    if not clips:
        print(f"No front-camera clips found in {args.source}", file=sys.stderr)
        return 1
    drives = group_drives(clips, dt.timedelta(minutes=args.gap_minutes))
    if args.drive_start:
        drives = [
            drive for drive in drives
            if drive[0].started.strftime("%Y-%m-%d_%H-%M-%S") == args.drive_start
        ]
        if not drives:
            print(f"No local drive starts at {args.drive_start}", file=sys.stderr)
            return 1
    print(f"Found {len(clips)} front clips in {len(drives)} drives:")
    for number, drive in enumerate(drives, 1):
        span = drive[-1].started - drive[0].started
        print(
            f"  {number:3}: {drive[0].started} through {drive[-1].started}; "
            f"{len(drive)} clips; timestamp span {span}"
        )
    if not args.stitch:
        print("Preview only. Add --stitch to create MP4 files.")
        return 0
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
        args.output.mkdir(parents=True, exist_ok=True)
        counts = {"created": 0, "existing": 0, "failed": 0}
        for drive in drives:
            try:
                counts[
                    stitch(
                        ffmpeg, drive, args.output, args.overwrite,
                        args.music_dir, args.crossfade_seconds,
                        args.route_info, args.channel_title,
                        args.end_card_seconds, args.video_encoder,
                        args.target_size,
                    )
                ] += 1
            except (OSError, RuntimeError) as exc:
                counts["failed"] += 1
                print(f"ERROR: {exc}", file=sys.stderr)
        print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
        return 1 if counts["failed"] else 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
