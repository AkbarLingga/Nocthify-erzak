"""Time-synced lyrics from LRCLIB (https://lrclib.net) - a free, open lyrics database.

Only the song title, artist, album and length are sent.  Results (including
"not found") are cached on disk so a song is looked up once.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://lrclib.net/api"
UA = "Nocthify/1.2 (desktop shell)"
MISS_TTL = 3 * 24 * 3600            # retry songs without lyrics after a few days

_TS = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_NOISE = [
    r"\s*[\(\[][^)\]]*\b(official|lyrics?|video|audio|visuali[sz]er|mv|m/v|hd|4k|live|remaster(ed)?)\b[^)\]]*[\)\]]",
    r"\s*[\(\[]\s*(feat|ft|with)\.?\s[^)\]]*[\)\]]",
    r"\s+-\s+(\d{4}\s+)?remaster(ed)?(\s+\d{4})?.*$",
    r"\s+-\s+(single|radio|album)\s+(version|edit).*$",
    r"\s*\|.*$",
]


def clean_title(title: str) -> str:
    t = title or ""
    for pat in _NOISE:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)
    return t.strip(" -–—\t") or (title or "").strip()


def guess_from_video_title(title: str, channel: str):
    """'Artist - Song (Official Video)' on YouTube -> (artist, song)."""
    t = clean_title(title)
    for sep in (" - ", " – ", " — "):
        if sep in t:
            a, s = t.split(sep, 1)
            return a.strip(), s.strip()
    return (channel or "").replace(" - Topic", "").replace("VEVO", "").strip(), t


def parse_lrc(text: str):
    """LRC text -> [(seconds, line)] sorted by time."""
    out = []
    for raw in (text or "").splitlines():
        stamps = _TS.findall(raw)
        if not stamps:
            continue
        line = _TS.sub("", raw).strip()
        for m, s in stamps:
            out.append((int(m) * 60 + float(s), line))
    out.sort(key=lambda x: x[0])
    return out


def _get(path, params, timeout=7):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _result(rec):
    synced = parse_lrc(rec.get("syncedLyrics") or "")
    plain = [ln.strip() for ln in (rec.get("plainLyrics") or "").splitlines()]
    if rec.get("instrumental"):
        return {"instrumental": True}
    if synced:
        return {"synced": synced}
    if any(plain):
        return {"plain": plain}
    return None


class LyricsStore:
    def __init__(self, cache_dir: str):
        self.dir = cache_dir
        self.mem = {}

    def _path(self, key):
        return os.path.join(self.dir, hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + ".json")

    def _load(self, key):
        if key in self.mem:
            return self.mem[key]
        try:
            with open(self._path(key), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if data.get("miss") and time.time() - data.get("at", 0) > MISS_TTL:
            return None
        if "synced" in data:
            data["synced"] = [tuple(x) for x in data["synced"]]
        self.mem[key] = data
        return data

    def _save(self, key, data):
        self.mem[key] = data
        if len(self.mem) > 40:
            self.mem.pop(next(iter(self.mem)))
        try:
            os.makedirs(self.dir, exist_ok=True)
            files = sorted((os.path.join(self.dir, f) for f in os.listdir(self.dir)), key=os.path.getmtime)
            for old in files[:-300]:                      # keep the cache small
                os.remove(old)
            with open(self._path(key), "w", encoding="utf-8") as fh:
                json.dump(dict(data, at=time.time()), fh)
        except OSError:
            pass

    def fetch(self, title, artist="", album="", duration=0.0, video=False):
        """Blocking (call from a worker thread). Returns
        {"synced": [(t, line)]} | {"plain": [lines]} | {"instrumental": True} | {"miss": True},
        or None when offline (not cached, so it is retried later)."""
        if video:
            artist, title = guess_from_video_title(title, artist)
        else:
            title = clean_title(title)
        artist = (artist or "").split(",")[0].strip()
        key = f"{artist.lower()}|{title.lower()}"
        cached = self._load(key)
        if cached is not None:
            return cached
        try:
            res = None
            if artist:
                params = {"track_name": title, "artist_name": artist}
                if album and not video:
                    params["album_name"] = album
                if duration and duration > 1:
                    params["duration"] = int(round(duration))
                rec = _get("get", params)
                res = _result(rec) if rec else None
            if res is None:
                q = {"track_name": title}
                if artist:
                    q["artist_name"] = artist
                hits = _get("search", q) or []
                if not hits and artist:
                    hits = _get("search", {"q": f"{artist} {title}"}) or []
                best = None
                for h in hits[:15]:
                    near = not duration or abs((h.get("duration") or 0) - duration) <= 4
                    if h.get("syncedLyrics") and near:
                        best = h
                        break
                    if best is None and (h.get("plainLyrics") or h.get("syncedLyrics")):
                        best = h
                res = _result(best) if best else None
        except (OSError, ValueError):
            return None                                     # offline / server trouble
        res = res or {"miss": True}
        self._save(key, res)
        return res
