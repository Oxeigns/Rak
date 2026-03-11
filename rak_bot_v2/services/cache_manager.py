"""Disk-backed cache for illegal text, images, and word lists."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import unicodedata
import time
from pathlib import Path

import imagehash
from PIL import Image

LOGGER = logging.getLogger(__name__)


class CacheManager:
    """Manage moderation cache with on-disk persistence."""

    def __init__(self, cache_dir: str = "cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.illegal_text_dir = self.cache_dir / "illegal_text"
        self.illegal_images_dir = self.cache_dir / "illegal_images"
        self.blacklist_file = self.cache_dir / "blacklist_words.txt"
        self.whitelist_file = self.cache_dir / "whitelist_words.txt"

        self._memory_cache: set[str] = set()
        self._access_times: dict[str, float] = {}
        self._max_memory_items = 10_000
        self._image_hashes: set[str] = set()

        # Word lists stored as frozen snapshots for lock-free reads
        self._blacklist: frozenset[str] = frozenset()
        self._whitelist: frozenset[str] = frozenset()

        self._lock = asyncio.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Create folders and load cache state into memory."""
        self.illegal_text_dir.mkdir(parents=True, exist_ok=True)
        self.illegal_images_dir.mkdir(parents=True, exist_ok=True)
        self.blacklist_file.touch(exist_ok=True)
        self.whitelist_file.touch(exist_ok=True)
        await self._load_memory_cache()
        await self._load_word_lists()

    # ── Public Stats ───────────────────────────────────────────────────────

    @property
    def cached_text_count(self) -> int:
        """Number of illegal text hashes held in memory."""
        return len(self._memory_cache)

    @property
    def cached_image_count(self) -> int:
        """Number of illegal image hashes held in memory."""
        return len(self._image_hashes)

    # ── Text Cache ─────────────────────────────────────────────────────────

    def _normalize_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).lower().strip()
        return re.sub(r"\s+", " ", normalized)

    def _get_text_hash(self, text: str) -> str:
        normalized = self._normalize_text(text)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def is_text_cached_illegal(self, text: str) -> bool:
        """Return True if normalized text hash is in the illegal cache."""
        text_hash = self._get_text_hash(text)
        async with self._lock:
            if text_hash in self._memory_cache:
                self._access_times[text_hash] = time.time()
                return True
        return False

    async def save_illegal_text(self, text: str) -> None:
        """Persist illegal text hash; evict oldest entry when at capacity."""
        text_hash = self._get_text_hash(text)
        file_path = self.illegal_text_dir / f"{text_hash}.txt"
        async with self._lock:
            if text_hash in self._memory_cache:
                self._access_times[text_hash] = time.time()
                return
            # LRU eviction
            if len(self._memory_cache) >= self._max_memory_items and self._access_times:
                oldest = min(self._access_times, key=self._access_times.__getitem__)
                self._memory_cache.discard(oldest)
                self._access_times.pop(oldest, None)
                # Also remove from disk
                old_file = self.illegal_text_dir / f"{oldest}.txt"
                await asyncio.to_thread(self._safe_unlink, old_file)
            self._memory_cache.add(text_hash)
            self._access_times[text_hash] = time.time()
        await asyncio.to_thread(self._write_file, file_path, text)

    # ── Image Cache ────────────────────────────────────────────────────────

    def _get_image_hash(self, image_bytes: bytes) -> str:
        """Compute perceptual pHash for an image."""
        image = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(image))

    async def is_image_cached_illegal(self, image_bytes: bytes, max_hamming: int = 2) -> bool:
        """Return True if image is a near-duplicate of a cached illegal image."""
        target_hash = imagehash.hex_to_hash(self._get_image_hash(image_bytes))
        # Snapshot to avoid holding lock during comparison loop
        async with self._lock:
            snapshot = frozenset(self._image_hashes)
        for cached in snapshot:
            if target_hash - imagehash.hex_to_hash(cached) <= max_hamming:
                return True
        return False

    async def save_illegal_image(self, image_bytes: bytes) -> None:
        """Persist illegal image phash to disk and memory."""
        image_hash = self._get_image_hash(image_bytes)
        path = self.illegal_images_dir / f"{image_hash}.txt"
        async with self._lock:
            if image_hash in self._image_hashes:
                return
            self._image_hashes.add(image_hash)
        await asyncio.to_thread(self._write_file, path, "illegal")

    # ── Word Lists (lock-free reads) ───────────────────────────────────────

    async def contains_blacklist_word(self, text: str) -> bool:
        """
        Return True if a blacklisted word appears (whole-word match).
        Uses a local snapshot so the lock is NOT held during regex scanning.
        """
        blacklist = self._blacklist          # atomic reference read – no lock needed
        text_lower = text.lower()
        for word in blacklist:
            if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
                return True
        return False

    async def contains_whitelist_word(self, text: str) -> bool:
        """Return True when normalized text matches a whitelist entry exactly."""
        value = self._normalize_text(text)
        return value in self._whitelist      # frozenset read – no lock needed

    async def reload_word_lists(self) -> None:
        """Reload word list files from disk (hot-reload without restart)."""
        await self._load_word_lists()

    # ── Cache Cleanup ──────────────────────────────────────────────────────

    async def cleanup_old_cache(self) -> None:
        """
        Remove entries not accessed in the last 24 hours from BOTH
        memory AND disk.
        """
        cutoff = time.time() - 86400
        async with self._lock:
            to_remove = [h for h, ts in self._access_times.items() if ts < cutoff]
            for h in to_remove:
                self._memory_cache.discard(h)
                self._access_times.pop(h, None)

        # Delete disk files outside the lock
        for h in to_remove:
            disk_file = self.illegal_text_dir / f"{h}.txt"
            await asyncio.to_thread(self._safe_unlink, disk_file)

        LOGGER.info("cache_cleanup_removed: %s entries", len(to_remove))

    # ── Internal Loaders ───────────────────────────────────────────────────

    async def _load_memory_cache(self) -> None:
        """Load text and image hash file stems into memory sets."""
        def _load() -> tuple[set[str], set[str]]:
            texts = {f.stem for f in self.illegal_text_dir.glob("*.txt")}
            images = {f.stem for f in self.illegal_images_dir.glob("*.txt")}
            return texts, images

        text_hashes, image_hashes = await asyncio.to_thread(_load)
        now = time.time()
        async with self._lock:
            self._memory_cache = text_hashes
            self._image_hashes = image_hashes
            self._access_times = {h: now for h in text_hashes}

    async def _load_word_lists(self) -> None:
        """Load blacklist and whitelist entries; replace atomically."""
        def _load_file(path: Path) -> frozenset[str]:
            words: set[str] = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                raw = line.strip()
                if raw and not raw.startswith("#"):
                    # normalise the word so matching is case/space insensitive
                    words.add(self._normalize_text(raw))
            return frozenset(words)

        blacklist = await asyncio.to_thread(_load_file, self.blacklist_file)
        whitelist = await asyncio.to_thread(_load_file, self.whitelist_file)
        # Atomic swap – no lock needed for reads after this point
        self._blacklist = blacklist
        self._whitelist = whitelist
        LOGGER.info(
            "word_lists_loaded blacklist=%s whitelist=%s", len(blacklist), len(whitelist)
        )

    # ── Disk Helpers ───────────────────────────────────────────────────────

    def _write_file(self, path: Path, content: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cache_write_failed path=%s err=%s", path, exc)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("cache_unlink_failed path=%s err=%s", path, exc)
