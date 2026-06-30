import json
import os
import re
import threading
import time
from datetime import datetime
from urllib import request as urlrequest


DEEP_HOLE_API_URL = "https://mabimobi.life/d/api/v1/deep-hole-config"
DEEP_HOLE_TARGET_SERVER = os.getenv("DEEP_HOLE_TARGET_SERVER", "던컨")
DEEP_HOLE_TARGET_AREA = os.getenv("DEEP_HOLE_TARGET_AREA", "창백한 산")
DEEP_HOLE_CHECK_INTERVAL_SECONDS = 30 * 60
DEEP_HOLE_DRIFT_THRESHOLD_SECONDS = 60
DEEP_HOLE_REQUEST_TIMEOUT_SECONDS = 10
DEEP_HOLE_TRACKER_ENABLED = os.getenv("DEEP_HOLE_TRACKER_ENABLED", "1").strip() != "0"
_TRACKER_LOCK = threading.Lock()
_TRACKER_STARTED = False


def create_deep_hole_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS deep_hole_rooms (
            room_id TEXT PRIMARY KEY,
            added_by INTEGER,
            added_date TEXT
        )
        """
    )


def _deep_hole_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://mabimobi.life/",
        "Origin": "https://mabimobi.life",
    }


def _walk_values(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _coerce_open_status(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"open", "opened", "active", "true", "1", "yes", "y", "on", "available", "spawn"}:
            return True
        if text in {"열림", "출현", "진행", "활성", "가능", "o"}:
            return True
        if text in {"closed", "inactive", "false", "0", "no", "n", "off", "none", "unavailable"}:
            return False
        if text in {"닫힘", "미출현", "종료", "비활성", "불가", "x"}:
            return False
    return None


def _parse_reset_seconds_from_value(value, kst):
    if isinstance(value, (int, float)) and 0 <= value <= 24 * 60 * 60:
        return int(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if match:
        parts = [int(p) for p in match.groups(default="0")]
        if match.group(3) is None:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    try:
        iso_text = text.replace("Z", "+00:00")
        target = datetime.fromisoformat(iso_text)
        if target.tzinfo is None:
            target = kst.localize(target)
        return max(0, int((target.astimezone(kst) - datetime.now(kst)).total_seconds()))
    except Exception:
        return None


def _extract_deep_hole_reset_seconds(data, kst):
    key_patterns = ("reset", "remain", "remaining", "left", "next", "ttl", "seconds", "countdown")

    for item in _iter_dicts(data):
        for key, value in item.items():
            key_text = str(key).lower()
            if any(pattern in key_text for pattern in key_patterns):
                seconds = _parse_reset_seconds_from_value(value, kst)
                if seconds is not None:
                    return seconds

    for value in _walk_values(data):
        seconds = _parse_reset_seconds_from_value(value, kst)
        if seconds is not None:
            return seconds

    return None


def _dict_text_contains(item, target):
    return any(target in str(value) for value in item.values())


def _extract_deep_hole_open_status(data):
    for item in _iter_dicts(data):
        if not (_dict_text_contains(item, DEEP_HOLE_TARGET_SERVER) and _dict_text_contains(item, DEEP_HOLE_TARGET_AREA)):
            continue

        for key in ("is_open", "isOpened", "opened", "open", "active", "available", "status", "state", "value", "count"):
            if key in item:
                status = _coerce_open_status(item[key])
                if status is not None:
                    return status

        for value in item.values():
            status = _coerce_open_status(value)
            if status is not None:
                return status

    for item in _iter_dicts(data):
        if DEEP_HOLE_TARGET_AREA in item:
            value = item[DEEP_HOLE_TARGET_AREA]
            if isinstance(value, dict) and DEEP_HOLE_TARGET_SERVER in value:
                return _coerce_open_status(value[DEEP_HOLE_TARGET_SERVER])
        if DEEP_HOLE_TARGET_SERVER in item:
            value = item[DEEP_HOLE_TARGET_SERVER]
            if isinstance(value, dict) and DEEP_HOLE_TARGET_AREA in value:
                return _coerce_open_status(value[DEEP_HOLE_TARGET_AREA])

    return None


def fetch_deep_hole_status(kst):
    req = urlrequest.Request(
        DEEP_HOLE_API_URL,
        headers=_deep_hole_headers(),
    )
    with urlrequest.urlopen(req, timeout=DEEP_HOLE_REQUEST_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)

    return {
        "is_open": _extract_deep_hole_open_status(data),
        "reset_seconds": _extract_deep_hole_reset_seconds(data, kst),
        "raw": data,
    }


def get_deep_hole_room_ids(get_db_conn, db_lock):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT room_id FROM deep_hole_rooms ORDER BY added_date DESC LIMIT 1")
        room_ids = [str(row["room_id"]) for row in cur.fetchall() if row["room_id"]]
        conn.close()

    return room_ids


def select_deep_hole_room(room_id, added_by, get_db_conn, db_lock, kst):
    now_time = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM deep_hole_rooms")
        cur.execute(
            """
            INSERT INTO deep_hole_rooms (room_id, added_by, added_date)
            VALUES (?, ?, ?)
            """,
            (str(room_id), int(added_by), now_time),
        )
        conn.commit()
        conn.close()


def format_deep_hole_status(status):
    open_text = "열림" if status.get("is_open") is True else "닫힘" if status.get("is_open") is False else "확인불가"
    reset_seconds = status.get("reset_seconds")
    if reset_seconds is None:
        reset_text = "확인불가"
    else:
        reset_text = f"{reset_seconds // 60:02d}:{reset_seconds % 60:02d}"

    return (
        f"심층 구멍 체크\n"
        f"대상: {DEEP_HOLE_TARGET_SERVER} / {DEEP_HOLE_TARGET_AREA}\n"
        f"상태: {open_text}\n"
        f"리셋까지: {reset_text}"
    )


def _next_wait_seconds(reset_seconds):
    wait_seconds = DEEP_HOLE_CHECK_INTERVAL_SECONDS
    if reset_seconds is None:
        return wait_seconds

    aligned_wait = max(5, reset_seconds + 3)
    if abs(aligned_wait - DEEP_HOLE_CHECK_INTERVAL_SECONDS) > DEEP_HOLE_DRIFT_THRESHOLD_SECONDS:
        return aligned_wait
    return wait_seconds


def start_deep_hole_tracker(bot, send_message, get_db_conn, db_lock, kst):
    global _TRACKER_STARTED

    if not DEEP_HOLE_TRACKER_ENABLED:
        print("[심구알림] 추적 비활성화(DEEP_HOLE_TRACKER_ENABLED=0)")
        return

    with _TRACKER_LOCK:
        if _TRACKER_STARTED:
            return
        _TRACKER_STARTED = True

    state = {"last_is_open": None}

    def run():
        wait_seconds = 3
        while True:
            time.sleep(max(1, wait_seconds))

            try:
                status = fetch_deep_hole_status(kst)
                is_open = status.get("is_open")
                reset_seconds = status.get("reset_seconds")
                room_ids = get_deep_hole_room_ids(get_db_conn, db_lock)
                print(
                    f"[심구알림] {DEEP_HOLE_TARGET_SERVER}/{DEEP_HOLE_TARGET_AREA} "
                    f"open={is_open} reset={reset_seconds} rooms={len(room_ids)}"
                )

                if is_open is True and state["last_is_open"] is not True:
                    if not room_ids:
                        print("[심구알림] 지정된 알림 채팅방이 없어 전송하지 않습니다.")
                    else:
                        message = (
                            f"심층 구멍 열림\n"
                            f"{DEEP_HOLE_TARGET_SERVER} / {DEEP_HOLE_TARGET_AREA}"
                        )
                        for room_id in room_ids:
                            send_message(bot, room_id, message)

                state["last_is_open"] = is_open

                wait_seconds = _next_wait_seconds(reset_seconds)
                if wait_seconds != DEEP_HOLE_CHECK_INTERVAL_SECONDS:
                    print(f"[심구알림] 사이트 리셋 타이머 기준으로 다음 체크 보정: {wait_seconds:.1f}초")

            except Exception as e:
                print(f"[심구알림] 체크 실패: {e}")
                wait_seconds = DEEP_HOLE_CHECK_INTERVAL_SECONDS

    threading.Thread(target=run, daemon=True).start()
