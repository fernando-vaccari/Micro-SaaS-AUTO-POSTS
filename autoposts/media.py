"""Offline, bounded rendering of vertical videos from owned images and text."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import core

WIDTH, HEIGHT = 1080, 1920
MAX_OUTPUT_BYTES = 100 * 1024 * 1024
PALETTES = {
    "violet": {"base": (17, 14, 34), "accent": (171, 131, 255), "glow": (75, 38, 130)},
    "ocean": {"base": (8, 25, 35), "accent": (90, 222, 215), "glow": (9, 86, 112)},
    "ember": {"base": (34, 18, 16), "accent": (255, 172, 112), "glow": (123, 44, 28)},
}


class RenderError(Exception):
    """A safe message that may be shown to the owner of a failed render."""


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation2/LiberationSans{'-Bold' if bold else '-Regular'}.ttf",
    ]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise RenderError("Fonte indisponível. Instale fonts-dejavu-core no servidor.")


def _clean_text(text: str, limit: int) -> str:
    return "".join(c for c in str(text) if c in "\n\t" or ord(c) >= 32)[:limit].strip()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    # Long words are split too, so pasted URLs cannot escape the video bounds.
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if font.getlength(candidate) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            while font.getlength(word) > max_width and len(word) > 1:
                index = 1
                while index < len(word) and font.getlength(word[: index + 1]) <= max_width:
                    index += 1
                lines.append(word[:index])
                word = word[index:]
            line = word
        if line:
            lines.append(line)
        elif not paragraph.strip():
            lines.append("")
    return lines or [""]


def _fit_text(text: str, width: int, height: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(94, 35, -2):
        font = _font(size, bold=True)
        lines = _wrap(text, font, width)
        line_height = math.ceil(size * 1.34)
        if line_height * len(lines) <= height:
            return font, lines, line_height
    raise RenderError("O texto de uma cena é muito longo. Divida-o em mais cenas.")


def _background(theme: dict, image_path: Path | None) -> Image.Image:
    # Gradients are computed at quarter resolution, then scaled for low memory/CPU use.
    small = Image.new("RGB", (270, 480), theme["base"])
    draw = ImageDraw.Draw(small)
    for y in range(480):
        weight = max(0.0, 1.0 - abs(y - 145) / 380) * 0.34
        color = tuple(round(a * (1 - weight) + b * weight) for a, b in zip(theme["base"], theme["glow"]))
        draw.line((0, y, 270, y), fill=color)
    glow = Image.new("RGBA", small.size)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((55, -80, 390, 260), fill=(*theme["glow"], 145))
    gd.ellipse((-130, 270, 150, 520), fill=(*theme["accent"], 35))
    small = Image.alpha_composite(small.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(40)))
    frame = small.resize((WIDTH, HEIGHT), Image.Resampling.BICUBIC).convert("RGB")
    if image_path:
        try:
            with Image.open(image_path) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                photo = ImageOps.fit(source, (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            frame = Image.blend(photo, frame, 0.48)
            overlay = Image.new("RGBA", frame.size)
            od = ImageDraw.Draw(overlay)
            for y in range(HEIGHT):
                alpha = int(70 + 125 * abs(y / HEIGHT - 0.40))
                od.line((0, y, WIDTH, y), fill=(3, 5, 12, alpha))
            frame = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise RenderError("Não foi possível abrir a imagem de uma cena. Envie a imagem novamente.") from exc
    return frame


def _scene_frame(post: dict, scene: dict, index: int, total: int, image_path: Path | None) -> Image.Image:
    palette = PALETTES[post.get("theme", "violet")]
    frame = _background(palette, image_path)
    draw = ImageDraw.Draw(frame)
    accent = palette["accent"]
    draw.rounded_rectangle((82, 116, 140, 174), radius=18, fill=accent)
    draw.polygon(((104, 132), (104, 158), (123, 145)), fill=palette["base"])
    draw.text((160, 128), "AUTOPOSTS", font=_font(28, True), fill=(245, 244, 250))
    marker = f"{index + 1:02d} / {total:02d}"
    draw.text((WIDTH - 84 - draw.textlength(marker, font=_font(26)), 132), marker, font=_font(26), fill=(211, 209, 224))
    # A generous top/bottom safe area leaves text clear of Instagram's overlays.
    text = _clean_text(scene.get("text", ""), 1000)
    if text:
        font, lines, line_height = _fit_text(text, WIDTH - 168, 1000)
        start_y = max(390, (HEIGHT - len(lines) * line_height) // 2 - 45)
        draw.rounded_rectangle((84, start_y - 70, 164, start_y - 61), radius=4, fill=accent)
        for line in lines:
            draw.text((84, start_y), line, font=font, fill=(250, 249, 255), stroke_width=1)
            start_y += line_height
    title_font = _font(28)
    title = _clean_text(post.get("title", ""), 120)
    title_lines = _wrap(title, title_font, WIDTH - 168)[:2]
    for offset, line in enumerate(title_lines):
        draw.text((84, 1640 + offset * 38), line, font=title_font, fill=(224, 222, 235))
    gap = 12
    segment_width = (WIDTH - 168 - gap * (total - 1)) / total
    for position in range(total):
        x = 84 + position * (segment_width + gap)
        draw.rounded_rectangle((round(x), 1770, round(x + segment_width), 1777), radius=3,
                               fill=accent if position <= index else (75, 74, 89))
    return frame


def _owned_image(post: dict, asset_id: str | None) -> Path | None:
    if not asset_id:
        return None
    asset = core.one("SELECT * FROM assets WHERE id = ? AND user_id = ?", (asset_id, post["user_id"]))
    if not asset or asset["kind"] != "image":
        raise RenderError("Uma imagem desta cena não está mais disponível na sua conta.")
    filename = asset["filename"]
    if Path(filename).name != filename:
        raise RenderError("Arquivo de imagem inválido.")
    upload_dir = (core.settings.data_dir / "uploads").resolve()
    path = upload_dir / filename
    if not path.is_file() or path.resolve().parent != upload_dir:
        raise RenderError("Uma imagem desta cena não está mais disponível no servidor.")
    return path


def _validate_output(path: Path, duration: int) -> None:
    try:
        check = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        result = json.loads(check.stdout)
        video = next(stream for stream in result["streams"] if stream["codec_type"] == "video")
        audio = next(stream for stream in result["streams"] if stream["codec_type"] == "audio")
        valid = (video["codec_name"] == "h264" and video["width"] == WIDTH and video["height"] == HEIGHT
                 and video["pix_fmt"] == "yuv420p" and audio["codec_name"] == "aac"
                 and abs(float(result["format"]["duration"]) - duration) < 0.35
                 and 0 < path.stat().st_size <= MAX_OUTPUT_BYTES)
        if not valid:
            raise ValueError("Invalid output")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
        raise RenderError("O arquivo de vídeo não passou na verificação. Tente renderizar novamente.") from exc


def render_post(post: dict) -> str:
    """Render a real H.264/AAC MP4, publishing the file atomically after validation."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("FFmpeg e ffprobe precisam estar instalados no servidor.")
    post_id = str(post.get("id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", post_id):
        raise RenderError("Identificador de vídeo inválido.")
    scenes = post.get("scenes", [])
    if isinstance(scenes, str):
        try:
            scenes = json.loads(scenes)
        except (ValueError, TypeError) as exc:
            raise RenderError("O roteiro do vídeo é inválido.") from exc
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 6:
        raise RenderError("O vídeo precisa ter de uma a seis cenas.")
    if not all(isinstance(scene, dict) and (_clean_text(scene.get("text", ""), 1000) or scene.get("asset_id")) for scene in scenes):
        raise RenderError("Preencha o texto ou selecione uma imagem em cada cena antes de renderizar.")
    duration = post.get("duration", 15)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 6 <= duration <= 60:
        raise RenderError("A duração do vídeo deve estar entre 6 e 60 segundos.")
    if post.get("theme", "violet") not in PALETTES:
        raise RenderError("Selecione um dos temas disponíveis.")
    videos_dir = core.settings.data_dir / "videos"
    temp_dir = core.settings.data_dir / "tmp"
    videos_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"{post_id}.mp4"
    # A per-render directory ensures simultaneous users never share filenames.
    with tempfile.TemporaryDirectory(prefix=f"render-{post_id}-", dir=temp_dir) as staging:
        staging_path = Path(staging)
        for index, scene in enumerate(scenes):
            image = _scene_frame(post, scene, index, len(scenes), _owned_image(post, scene.get("asset_id")))
            image.save(staging_path / f"scene-{index}.png", optimize=False)
            image.close()
        playlist = staging_path / "scenes.txt"
        lines: list[str] = []
        for index in range(len(scenes)):
            lines.extend((f"file 'scene-{index}.png'", f"duration {duration / len(scenes):.8f}"))
        lines.append(f"file 'scene-{len(scenes) - 1}.png'")
        playlist.write_text("\n".join(lines) + "\n", encoding="utf-8")
        staging_output = staging_path / "output.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "1", "-i", str(playlist),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-map", "0:v:0", "-map", "1:a:0", "-vf", "fps=30",
            "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "23",
            "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-movflags", "+faststart", str(staging_output),
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=300, check=True)
        except subprocess.TimeoutExpired as exc:
            raise RenderError("A renderização excedeu o tempo limite. Reduza a duração e tente novamente.") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RenderError("Não foi possível gerar o vídeo. Verifique se o servidor possui o encoder libx264.") from exc
        _validate_output(staging_output, duration)
        os.replace(staging_output, videos_dir / output_name)
    return output_name
