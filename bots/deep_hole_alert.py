import base64
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib import request as urlrequest


DEEP_HOLE_API_URL = "https://mabimobi.life/d/api/v1/adh"
DEEP_HOLE_CONFIG_API_URL = "https://mabimobi.life/d/api/v1/deep-hole-config"
DEEP_HOLE_TARGET_SERVER = os.getenv("DEEP_HOLE_TARGET_SERVER", "던컨")
DEEP_HOLE_TARGET_AREA = os.getenv("DEEP_HOLE_TARGET_AREA", "창백한 산")
DEEP_HOLE_CHECK_INTERVAL_SECONDS = 30 * 60
DEEP_HOLE_DRIFT_THRESHOLD_SECONDS = 60
DEEP_HOLE_TIME_SYNC_THRESHOLD_SECONDS = 60
DEEP_HOLE_REQUEST_TIMEOUT_SECONDS = 10
DEEP_HOLE_TRACKER_ENABLED = os.getenv("DEEP_HOLE_TRACKER_ENABLED", "1").strip() != "0"
DEEP_HOLE_APPEARANCE_SECONDS = 30 * 60
DEEP_HOLE_REMINDER_SECONDS = 5 * 60
DEEP_HOLE_DH_KEY = "8nvov88uc5k4o4g6apax04783thjo11l"
DEEP_HOLE_SERVER_CODES = {
    "데이안": "01",
    "아이라": "02",
    "던컨": "03",
    "알리사": "04",
    "메이븐": "05",
    "라사": "06",
    "칼릭스": "07",
    "몰리": "08",
}
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


def _decode_interleaved_payload(payload):
    max_header_len = min(16, len(payload))
    for header_len in range(8, max_header_len + 1):
        for split_at in range(4, header_len - 3):
            even_text = payload[:split_at]
            odd_text = payload[split_at:header_len]
            if not (even_text.isdigit() and odd_text.isdigit()):
                continue

            even_count = int(even_text)
            odd_count = int(odd_text)
            expected_header = f"{even_count:04d}{odd_count:04d}"
            if expected_header != payload[:header_len]:
                continue
            if len(payload) - header_len != (even_count + odd_count) * 4:
                continue

            body = payload[header_len:]
            even_chunks = [body[i:i + 4] for i in range(0, even_count * 4, 4)]
            odd_body = body[even_count * 4:]
            odd_chunks = [odd_body[i:i + 4] for i in range(0, odd_count * 4, 4)]

            chunks = []
            even_index = 0
            odd_index = 0
            for index in range(even_count + odd_count):
                if index % 2 == 0 and even_index < len(even_chunks):
                    chunks.append(even_chunks[even_index])
                    even_index += 1
                elif odd_index < len(odd_chunks):
                    chunks.append(odd_chunks[odd_index])
                    odd_index += 1

            encoded = "".join(chunks)
            encoded += "=" * (-len(encoded) % 4)
            return base64.b64decode(encoded)

    raise ValueError("Invalid deep-hole payload header")


def _deep_hole_seed_text(dt, use_utc):
    if use_utc:
        dt = dt.astimezone(timezone.utc)
    return f"{dt.year}{dt.month}{dt.day}{dt.hour}"


def _deep_hole_time_seeds(kst):
    now_utc = datetime.now(timezone.utc)
    now_kst = datetime.now(kst)
    seeds = []

    for hour_offset in (0, -1, 1):
        shifted_utc = now_utc + timedelta(hours=hour_offset)
        shifted_kst = now_kst + timedelta(hours=hour_offset)
        seeds.append(_deep_hole_seed_text(shifted_utc, True))
        seeds.append(_deep_hole_seed_text(shifted_kst, False))

    return list(dict.fromkeys(seeds))


def _deobfuscate_deep_hole_payload(payload, kst):
    decoded_bytes = _decode_interleaved_payload(payload)
    last_error = None

    for seed in _deep_hole_time_seeds(kst):
        key = hashlib.sha256(f"{DEEP_HOLE_DH_KEY}:{seed}".encode("utf-8")).digest()
        output = bytes(value ^ key[index % len(key)] for index, value in enumerate(decoded_bytes))
        try:
            return json.loads(output.decode("utf-8"))
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Failed to decode deep-hole payload: {last_error}")


def _parse_deep_hole_reports(data, kst):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, str):
            decoded = _deobfuscate_deep_hole_payload(payload, kst)
            return decoded if isinstance(decoded, list) else []
        for key in ("reports", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_datetime(value, kst):
    if not value:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(kst)
    if not isinstance(value, str):
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = kst.localize(parsed) if hasattr(kst, "localize") else parsed.replace(tzinfo=kst)
    return parsed.astimezone(kst)


def _server_code(value):
    text = str(value).strip()
    if text in DEEP_HOLE_SERVER_CODES:
        return DEEP_HOLE_SERVER_CODES[text]
    if text.isdigit():
        return f"{int(text):02d}"
    return text


def _server_matches(value, target_server):
    return _server_code(value) == _server_code(target_server) or str(value).strip() == str(target_server).strip()


def _calculate_deep_hole_reset_seconds(reports, now):
    if not reports or len(reports) < 5:
        minute = now.minute
        return ((30 if minute < 30 else 60) - minute - 1) * 60 + (60 - now.second)

    minute_counts = {}
    for report in reports:
        expired = _parse_datetime(report.get("expired"), now.tzinfo)
        if expired is None:
            continue
        minute_counts[expired.minute] = minute_counts.get(expired.minute, 0) + 1

    top_minutes = [
        minute for minute, _ in sorted(minute_counts.items(), key=lambda item: item[1], reverse=True)[:2]
    ]
    if not top_minutes:
        minute = now.minute
        return ((30 if minute < 30 else 60) - minute - 1) * 60 + (60 - now.second)

    candidates = []
    for minute in top_minutes:
        candidate = now.replace(minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        candidates.append(candidate)

    seconds = int((min(candidates) - now).total_seconds())
    if seconds > DEEP_HOLE_CHECK_INTERVAL_SECONDS:
        seconds -= DEEP_HOLE_CHECK_INTERVAL_SECONDS
    return max(0, seconds)


def _reference_now_from_date_header(date_header, kst):
    local_now = datetime.now(kst)
    if not date_header:
        return local_now, 0, False

    try:
        site_now = parsedate_to_datetime(date_header)
    except Exception:
        return local_now, 0, False

    if site_now.tzinfo is None:
        site_now = site_now.replace(tzinfo=timezone.utc)
    site_now = site_now.astimezone(kst)

    offset_seconds = int((site_now - local_now).total_seconds())
    if abs(offset_seconds) >= DEEP_HOLE_TIME_SYNC_THRESHOLD_SECONDS:
        return site_now, offset_seconds, True

    return local_now, offset_seconds, False


def _extract_target_status_from_reports(reports, kst, now=None):
    if now is None:
        now = datetime.now(kst)
    target_reports = []

    for report in reports:
        if not isinstance(report, dict):
            continue
        if not _server_matches(report.get("server"), DEEP_HOLE_TARGET_SERVER):
            continue
        if str(report.get("area", "")).strip() != DEEP_HOLE_TARGET_AREA:
            continue

        expired = _parse_datetime(report.get("expired"), kst)
        if expired is None:
            continue

        started = expired - timedelta(seconds=DEEP_HOLE_APPEARANCE_SECONDS)
        target_reports.append((started, expired, report))

    reset_seconds = _calculate_deep_hole_reset_seconds(reports, now)

    for started, expired, report in target_reports:
        if started <= now < expired:
            return {
                "is_open": True,
                "reset_seconds": reset_seconds,
                "target_remaining_seconds": max(0, int((expired - now).total_seconds())),
                "count": report.get("count") or 1,
                "report": report,
                "reports": reports,
            }

    return {
        "is_open": False if reports else None,
        "reset_seconds": reset_seconds,
        "target_remaining_seconds": None,
        "count": 0,
        "report": None,
        "reports": reports,
    }


def fetch_deep_hole_status(kst):
    req = urlrequest.Request(
        DEEP_HOLE_API_URL,
        headers=_deep_hole_headers(),
    )
    with urlrequest.urlopen(req, timeout=DEEP_HOLE_REQUEST_TIMEOUT_SECONDS) as response:
        date_header = response.headers.get("Date")
        body = response.read().decode("utf-8")
    data = json.loads(body)

    reports = _parse_deep_hole_reports(data, kst)
    reference_now, time_offset_seconds, time_sync_applied = _reference_now_from_date_header(date_header, kst)
    status = _extract_target_status_from_reports(reports, kst, reference_now)
    status["time_offset_seconds"] = time_offset_seconds
    status["time_sync_applied"] = time_sync_applied
    status["raw"] = data
    return status


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


def clear_deep_hole_room(room_id, get_db_conn, db_lock):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM deep_hole_rooms WHERE room_id = ?", (str(room_id),))
        deleted_count = cur.rowcount
        conn.commit()
        conn.close()

    return deleted_count > 0


def format_deep_hole_status(status):
    open_text = "열림" if status.get("is_open") is True else "닫힘" if status.get("is_open") is False else "확인불가"
    reset_seconds = status.get("reset_seconds")
    if reset_seconds is None:
        reset_text = "확인불가"
    else:
        reset_text = f"{reset_seconds // 60:02d}:{reset_seconds % 60:02d}"

    lines = [
        "심층 구멍 체크",
        f"대상: {DEEP_HOLE_TARGET_SERVER} / {DEEP_HOLE_TARGET_AREA}",
        f"상태: {open_text}",
        f"리셋까지: {reset_text}",
    ]

    target_remaining_seconds = status.get("target_remaining_seconds")
    if target_remaining_seconds is not None:
        lines.append(f"대상 종료까지: {target_remaining_seconds // 60:02d}:{target_remaining_seconds % 60:02d}")

    if status.get("count"):
        lines.append(f"출현 수: {status['count']}")

    if status.get("time_sync_applied"):
        offset_seconds = status.get("time_offset_seconds", 0)
        lines.append(f"시간 보정: {offset_seconds:+d}초")

    return "\n".join(lines)


def _format_deep_hole_alert_message(status):
    count = status.get("count") or 1
    message = f"{DEEP_HOLE_TARGET_AREA} 지역에 심층 구멍 {count}개 출현하였습니다."

    target_remaining_seconds = status.get("target_remaining_seconds")
    if target_remaining_seconds is not None:
        remaining_minutes = max(0, int((target_remaining_seconds + 59) // 60))
        message += f" 종료까지 {remaining_minutes}분 전"

    return message


def _next_wait_seconds(reset_seconds, target_remaining_seconds=None, reminder_sent=False):
    wait_seconds = DEEP_HOLE_CHECK_INTERVAL_SECONDS

    if reset_seconds is not None:
        aligned_wait = max(5, reset_seconds + 3)
        if abs(aligned_wait - DEEP_HOLE_CHECK_INTERVAL_SECONDS) > DEEP_HOLE_DRIFT_THRESHOLD_SECONDS:
            wait_seconds = min(wait_seconds, aligned_wait)

    if target_remaining_seconds is not None and not reminder_sent:
        reminder_wait = target_remaining_seconds - DEEP_HOLE_REMINDER_SECONDS
        if reminder_wait > 0:
            wait_seconds = min(wait_seconds, max(5, reminder_wait + 1))

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

    state = {"last_is_open": None, "five_min_alert_sent": False}

    def run():
        wait_seconds = 3
        while True:
            time.sleep(max(1, wait_seconds))

            try:
                status = fetch_deep_hole_status(kst)
                is_open = status.get("is_open")
                reset_seconds = status.get("reset_seconds")
                target_remaining_seconds = status.get("target_remaining_seconds")
                time_offset_seconds = status.get("time_offset_seconds", 0)
                time_sync_applied = status.get("time_sync_applied")
                room_ids = get_deep_hole_room_ids(get_db_conn, db_lock)
                print(
                    f"[심구알림] {DEEP_HOLE_TARGET_SERVER}/{DEEP_HOLE_TARGET_AREA} "
                    f"open={is_open} reset={reset_seconds} target_remaining={target_remaining_seconds} "
                    f"time_offset={time_offset_seconds} sync={time_sync_applied} rooms={len(room_ids)}"
                )

                if is_open is not True:
                    state["five_min_alert_sent"] = False

                if is_open is True and state["last_is_open"] is not True:
                    if not room_ids:
                        print("[심구알림] 지정된 알림 채팅방이 없어 전송하지 않습니다.")
                    else:
                        message = _format_deep_hole_alert_message(status)
                        for room_id in room_ids:
                            send_message(bot, room_id, message)
                    if (
                        target_remaining_seconds is not None
                        and target_remaining_seconds <= DEEP_HOLE_REMINDER_SECONDS
                    ):
                        state["five_min_alert_sent"] = True

                elif (
                    is_open is True
                    and not state["five_min_alert_sent"]
                    and target_remaining_seconds is not None
                    and target_remaining_seconds <= DEEP_HOLE_REMINDER_SECONDS
                ):
                    if not room_ids:
                        print("[심구알림] 지정된 알림 채팅방이 없어 5분 전 알림을 전송하지 않습니다.")
                    else:
                        message = _format_deep_hole_alert_message(status)
                        for room_id in room_ids:
                            send_message(bot, room_id, message)
                    state["five_min_alert_sent"] = True

                state["last_is_open"] = is_open

                wait_seconds = _next_wait_seconds(
                    reset_seconds,
                    target_remaining_seconds,
                    state["five_min_alert_sent"],
                )
                if wait_seconds != DEEP_HOLE_CHECK_INTERVAL_SECONDS:
                    print(f"[심구알림] 사이트 리셋 타이머 기준으로 다음 체크 보정: {wait_seconds:.1f}초")

            except Exception as e:
                print(f"[심구알림] 체크 실패: {e}")
                wait_seconds = DEEP_HOLE_CHECK_INTERVAL_SECONDS

    threading.Thread(target=run, daemon=True).start()
