"""Now-playing info from Windows' Global System Media Transport Controls (Win10 1809+).

This is the same source the Windows volume flyout uses: Spotify, browsers (YouTube,
Spotify Web, SoundCloud...), VLC, the Media Player... report title, artist, album,
play/pause state and the playback position here.

Event driven: the worker thread sleeps until Windows reports a change (new song,
play/pause, seek, player opened/closed) with only a slow safety re-check, so it
costs nothing while music simply plays.

Needs the small optional ``winrt-Windows.Media.Control`` package (Python 3.9+).
Without it (or on Windows 7/8) Nocthify falls back to reading window titles.
"""
from __future__ import annotations

import threading
import time

try:  # optional dependency
    from datetime import datetime, timezone

    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as _Manager
    AVAILABLE = True
except Exception:  # ImportError, or the WinRT runtime missing on old Windows
    AVAILABLE = False

PLAYING = 4
SAFETY_RECHECK = 15.0


def _secs(td):
    try:
        return max(0.0, td.total_seconds())
    except Exception:
        return 0.0


class MediaWatcher:
    """on_update(info or None) is called from the worker thread; info has
    title, artist, album, aumid, playing, position (s), duration (s) and
    sampled (time.monotonic() when position was valid)."""

    def __init__(self, on_update):
        self.on_update = on_update
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._manager = None
        self._session = None
        self._tokens = []          # (session, [(remove_fn_name, token)])
        self._mgr_tokens = []
        self._last = None

    def start(self):
        if not AVAILABLE or self._thread is not None:
            return AVAILABLE
        self._thread = threading.Thread(target=self._main, name="nocthify-media", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self._wake.set()

    def poke(self):
        self._wake.set()

    # ---------------------------------------------------------------- worker
    def _main(self):
        while not self._stop.is_set():
            try:
                if self._manager is None:
                    self._manager = _Manager.request_async().get()
                    for name in ("sessions_changed", "current_session_changed"):
                        tok = getattr(self._manager, "add_" + name)(lambda *_: self._wake.set())
                        self._mgr_tokens.append((name, tok))
                info = self._read()
            except Exception:
                info = None
                self._drop_manager()
            if self._changed(info):
                self._last = info
                try:
                    self.on_update(info)
                except Exception:
                    pass
            self._wake.wait(SAFETY_RECHECK)
            self._wake.clear()
            time.sleep(0.05)               # coalesce bursts of events into one read
        self._unsubscribe()
        self._drop_manager()

    def _changed(self, info):
        last = self._last
        if (info is None) != (last is None):
            return True
        if info is None:
            return False
        keys = ("title", "artist", "album", "aumid", "playing", "duration")
        if any(info[k] != last[k] for k in keys):
            return True
        # report a position that disagrees with the extrapolated one (seek / buffering)
        expected = last["position"] + ((info["sampled"] - last["sampled"]) if last["playing"] else 0)
        return abs(info["position"] - expected) > 1.5

    def _drop_manager(self):
        mgr, self._manager = self._manager, None
        for name, tok in self._mgr_tokens:
            try:
                getattr(mgr, "remove_" + name)(tok)
            except Exception:
                pass
        self._mgr_tokens = []

    def _subscribe(self, session):
        if self._tokens and self._tokens[0] is session:
            return
        self._unsubscribe()
        regs = []
        for name in ("media_properties_changed", "playback_info_changed", "timeline_properties_changed"):
            try:
                regs.append((name, getattr(session, "add_" + name)(lambda *_: self._wake.set())))
            except Exception:
                pass
        self._tokens = [session, regs]

    def _unsubscribe(self):
        if not self._tokens:
            return
        session, regs = self._tokens
        for name, tok in regs:
            try:
                getattr(session, "remove_" + name)(tok)
            except Exception:
                pass
        self._tokens = []

    def _read(self):
        manager = self._manager
        sessions = list(manager.get_sessions())
        if not sessions:
            self._session = None
            self._unsubscribe()
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
        self._subscribe(session)
        props = session.try_get_media_properties_async().get()
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
        session = self._session
        if session is None:
            return False
        fn = {"play": "try_toggle_play_pause_async", "next": "try_skip_next_async",
              "prev": "try_skip_previous_async"}.get(cmd)
        if not fn:
            return False

        def go():
            try:
                getattr(session, fn)().get()
            except Exception:
                pass
            self._wake.set()
        threading.Thread(target=go, daemon=True).start()
        return True
