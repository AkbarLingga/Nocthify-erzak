"""Now-playing info from Windows' Global System Media Transport Controls (Win10 1809+).

This is the same source the Windows volume flyout uses: Spotify, browsers (YouTube,
Spotify Web, SoundCloud...), VLC, the Media Player... report title, artist, album,
play/pause state and the playback position here.

It needs the small optional ``winrt-Windows.Media.Control`` package (Python 3.9+).
Without it (or on Windows 7/8) Nocthify falls back to reading window titles.
"""
from __future__ import annotations

import threading
import time

try:  # optional dependency
    import asyncio
    from datetime import datetime, timezone

    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as _Manager
    AVAILABLE = True
except Exception:  # ImportError, or the WinRT runtime missing on old Windows
    AVAILABLE = False

PLAYING = 4


def _secs(td):
    try:
        return max(0.0, td.total_seconds())
    except Exception:
        return 0.0


class MediaWatcher:
    """Polls the media session in a worker thread and reports through ``on_update``.

    on_update(info or None) is called from the worker thread; info has
    title, artist, album, aumid, playing, position (s), duration (s) and
    sampled (time.monotonic() when position was valid).
    """

    def __init__(self, on_update, interval=1.0):
        self.on_update = on_update
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._loop = None
        self._session = None
        self._last = None

    def start(self):
        if not AVAILABLE or self._thread is not None:
            return AVAILABLE
        self._thread = threading.Thread(target=self._main, name="nocthify-media", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- worker
    def _main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run())
        except Exception:
            pass

    async def _run(self):
        manager = None
        while not self._stop.is_set():
            info = None
            try:
                if manager is None:
                    manager = await _Manager.request_async()
                info = await self._read(manager)
            except Exception:
                manager = None          # e.g. the media service restarted: reconnect next round
            if info != self._last or (info and info.get("playing")):
                self._last = info
                try:
                    self.on_update(info)
                except Exception:
                    pass
            await asyncio.sleep(self.interval if info and info.get("playing") else self.interval * 1.5)

    async def _read(self, manager):
        sessions = list(manager.get_sessions())
        if not sessions:
            self._session = None
            return None
        session = None
        for s in sessions:                       # prefer whatever is actually playing
            try:
                if s.get_playback_info().playback_status == PLAYING:
                    session = s
                    break
            except Exception:
                continue
        if session is None:
            session = manager.get_current_session() or sessions[0]
        self._session = session
        props = await session.try_get_media_properties_async()
        title = (props.title or "").strip() if props else ""
        if not title:
            return None
        playing = session.get_playback_info().playback_status == PLAYING
        tl = session.get_timeline_properties()
        duration = _secs(tl.end_time) - _secs(tl.start_time)
        position = _secs(tl.position)
        if playing and duration > 0:
            try:   # the position is only refreshed on events: extrapolate to "now"
                age = (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds()
                if 0 < age < 6 * 3600:
                    position += age
            except Exception:
                pass
        if duration > 0:
            position = min(position, duration)
        return {"title": title, "artist": (props.artist or "").strip(),
                "album": (props.album_title or "").strip(),
                "aumid": session.source_app_user_model_id or "",
                "playing": playing, "position": position, "duration": max(0.0, duration),
                "sampled": time.monotonic()}

    # -------------------------------------------------------------- commands
    def command(self, cmd):
        """play | next | prev -> True if sent to the session."""
        session, loop = self._session, self._loop
        if session is None or loop is None:
            return False
        fn = {"play": "try_toggle_play_pause_async", "next": "try_skip_next_async",
              "prev": "try_skip_previous_async"}.get(cmd)
        if not fn:
            return False

        async def go():
            try:
                await getattr(session, fn)()
            except Exception:
                pass
        try:
            asyncio.run_coroutine_threadsafe(go(), loop)
            return True
        except Exception:
            return False
