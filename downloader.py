"""Асинхронный загрузчик видео через yt-dlp и ffmpeg.

Вся работа с yt-dlp выполняется через asyncio.subprocess, поэтому основной
event loop бота не блокируется. Также здесь реализована загрузка файла на
бесплатный файлообменник transfer.sh (через curl) для файлов больше лимита
Telegram Bot API.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from config import DOWNLOAD_DIR, FFMPEG_PATH, YTDLP_PATH

logger = logging.getLogger(__name__)

# Регулярки для определения платформы по ссылке
PLATFORM_PATTERNS = {
    "youtube": re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE),
    "tiktok": re.compile(r"tiktok\.com|vm\.tiktok\.com", re.IGNORECASE),
    "instagram": re.compile(r"instagram\.com|instagr\.am", re.IGNORECASE),
    "vk": re.compile(r"vk\.com|vkvideo\.ru|vkrb\.ru|m\.vk\.com", re.IGNORECASE),
}

SUPPORTED_PLATFORMS = tuple(PLATFORM_PATTERNS.keys())


class DownloadError(Exception):
    """Общая ошибка загрузки/обработки видео."""


class VideoUnavailableError(DownloadError):
    """Видео недоступно (приватное, удалено, ошибка сети и т.п.)."""


@dataclass
class VideoInfo:
    id: str
    title: str
    platform: str
    url: str
    duration: float
    thumbnail: str
    filesize: int
    formats: int


def detect_platform(url: str) -> str | None:
    """Возвращает имя платформы по ссылке или None, если не поддерживается."""
    for name, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return None


class VideoDownloader:
    def __init__(self) -> None:
        Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

    async def _run(self, *args: str, timeout: float = 300.0):
        """Выполняет yt-dlp с указанными аргументами, возвращает (code, stdout, stderr)."""
        cmd = [YTDLP_PATH, "--no-warnings", "--no-playlist", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise DownloadError(
                "yt-dlp не установлен на сервере. Установите его через `pip install yt-dlp`."
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except Exception:
                pass
            raise DownloadError("Таймаут при обращении к сервису. Попробуйте позже.") from exc

        return proc.returncode, stdout.decode("utf-8", "ignore"), stderr.decode("utf-8", "ignore")

    @staticmethod
    def _clean_error(stderr: str) -> str:
        """Извлекает человекочитаемое сообщение об ошибке yt-dlp."""
        m = re.search(r"ERROR:\s*(.+)", stderr, re.IGNORECASE)
        msg = m.group(1) if m else stderr.strip()
        msg = re.sub(r"\s+", " ", msg)
        return msg[:400] or "Неизвестная ошибка"

    async def get_info(self, url: str) -> VideoInfo:
        """Проверяет доступность видео и возвращает информацию о нём."""
        platform = detect_platform(url)
        if not platform:
            raise DownloadError("Платформа не поддерживается.")

        code, out, err = await self._run("--dump-single-json", url)
        if code != 0 or not out:
            reason = self._clean_error(err)
            raise VideoUnavailableError(reason or "Не удалось получить информацию о видео.")

        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise VideoUnavailableError("Сервис вернул некорректный ответ.") from exc

        # Определяем максимальный доступный размер файла среди всех форматов
        best_size = 0
        for fmt in data.get("formats", []):
            size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            if size and size > best_size:
                best_size = size

        return VideoInfo(
            id=str(data.get("id") or ""),
            title=data.get("title") or "Видео",
            platform=platform,
            url=url,
            duration=data.get("duration") or 0.0,
            thumbnail=data.get("thumbnail") or "",
            filesize=best_size,
            formats=len(data.get("formats", [])),
        )

    @staticmethod
    def _parse_progress(line: str) -> float | None:
        """Парсит процент прогресса из строки yt-dlp вида `[download]  45.3% of ...`."""
        if "[download]" not in line:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)%", line)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    def _find_output(self, video_id: str, outtmpl: str) -> Path | None:
        pattern = Path(outtmpl).name.replace("%(id)s", video_id).replace("%(ext)s", "*")
        matches = list(Path(DOWNLOAD_DIR).glob(pattern))
        # Отдаём самый свежий по времени
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        videos = [p for p in matches if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".avi")]
        if videos:
            return videos[0]
        return matches[0] if matches else None

    async def download(
        self,
        url: str,
        video_id: str,
        title: str,
        progress_cb=None,
    ) -> Path:
        """Скачивает видео в максимально доступном качестве, возвращает путь к файлу.

        progress_cb: асинхронный callable, вызывается с процентом (0..100).
        """
        safe = re.sub(r'[\\/:*?"<>|\r\n]+', "_", title)[:80].strip() or "video"
        outtmpl = str(Path(DOWNLOAD_DIR) / f"%(id)s_{safe}.%(ext)s")

        # Лучший mp4 с видео+аудио, при недоступности — любой лучший формат.
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        cmd = [
            YTDLP_PATH, "--no-warnings", "--no-playlist",
            "-f", fmt,
            "--merge-output-format", "mp4",
            "--ffmpeg-location", FFMPEG_PATH,
            "-o", outtmpl,
            "--newline", "--progress",
            url,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise DownloadError(
                "yt-dlp или ffmpeg не установлены на сервере."
            ) from exc

        async def drain(stream, is_progress: bool):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").strip()
                if not text:
                    continue
                if is_progress:
                    percent = self._parse_progress(text)
                    if percent is not None and progress_cb:
                        try:
                            await progress_cb(percent)
                        except Exception:
                            logger.exception("Ошибка в progress_cb")
                else:
                    logger.debug("yt-dlp[stdout]: %s", text)

        await asyncio.gather(
            drain(proc.stdout, is_progress=False),
            drain(proc.stderr, is_progress=True),
        )
        code = await proc.wait()

        if code != 0:
            raise DownloadError("Произошла ошибка при скачивании видео.")

        filepath = self._find_output(video_id, outtmpl)
        if filepath is None:
            raise DownloadError("Файл не найден после загрузки.")
        return filepath


async def upload_to_transfer_sh(filepath: Path) -> str:
    """Загружает файл на бесплатный файлообменник transfer.sh, возвращает ссылку."""
    name = Path(filepath).name
    cmd = ["curl", "-s", "--upload-file", str(filepath), "https://transfer.sh/" + name]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise DownloadError("curl не установлен на сервере.") from exc

    try:
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=240)
    except asyncio.TimeoutError as exc:
        try:
            proc.kill()
        except Exception:
            pass
        raise DownloadError("Таймаут при загрузке на файлообменник.") from exc

    url = out.decode("utf-8", "ignore").strip()
    if not url.startswith("http"):
        raise DownloadError("Не удалось загрузить файл на файлообменник.")
    return url

