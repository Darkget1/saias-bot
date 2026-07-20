import argparse
import base64
import json
import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib import request as urlrequest


ABYSS_HOLE_API_URL = "https://mabimobi.life/d/api/v1/eab"
ABYSS_HOLE_CHECK_INTERVAL_SECONDS = 30 * 60
ABYSS_HOLE_PRE_ALERT_SECONDS = 10 * 60
ABYSS_HOLE_TIME_SYNC_THRESHOLD_SECONDS = 60
ABYSS_HOLE_REQUEST_TIMEOUT_SECONDS = 10
ABYSS_HOLE_TRACKER_ENABLED = os.getenv("ABYSS_HOLE_TRACKER_ENABLED", "1").strip() != "0"
ABYSS_HOLE_DH_KEY = "8nvov88uc5k4o4g6apax04783thjo11l"
_TRACKER_LOCK = threading.Lock()
_TRACKER_STARTED = False


_SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]
_INV_SBOX = [0] * 256
for _i, _value in enumerate(_SBOX):
    _INV_SBOX[_value] = _i
_RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def create_abyss_hole_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS abyss_hole_rooms (
            room_id TEXT PRIMARY KEY,
            added_by INTEGER,
            added_date TEXT
        )
        """
    )


def _abyss_hole_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://mabimobi.life/",
        "Origin": "https://mabimobi.life",
    }


def _xtime(value):
    value <<= 1
    if value & 0x100:
        value ^= 0x11B
    return value & 0xFF


def _gf_mul(a, b):
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _sub_word(word):
    return [_SBOX[value] for value in word]


def _rot_word(word):
    return word[1:] + word[:1]


def _expand_aes_key(key):
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16, 24, or 32 bytes")

    nk = len(key) // 4
    nr = nk + 6
    words = [list(key[index:index + 4]) for index in range(0, len(key), 4)]

    for index in range(nk, 4 * (nr + 1)):
        temp = words[index - 1][:]
        if index % nk == 0:
            temp = _sub_word(_rot_word(temp))
            temp[0] ^= _RCON[index // nk]
        elif nk > 6 and index % nk == 4:
            temp = _sub_word(temp)
        words.append([words[index - nk][offset] ^ temp[offset] for offset in range(4)])

    return [sum(words[4 * round_index:4 * (round_index + 1)], []) for round_index in range(nr + 1)]


def _add_round_key(state, round_key):
    for index, value in enumerate(round_key):
        state[index] ^= value


def _inv_sub_bytes(state):
    for index, value in enumerate(state):
        state[index] = _INV_SBOX[value]


def _inv_shift_rows(state):
    original = state[:]
    for row in range(4):
        for column in range(4):
            state[row + 4 * column] = original[row + 4 * ((column - row) % 4)]


def _inv_mix_columns(state):
    for column in range(4):
        index = 4 * column
        a0, a1, a2, a3 = state[index:index + 4]
        state[index] = _gf_mul(a0, 0x0E) ^ _gf_mul(a1, 0x0B) ^ _gf_mul(a2, 0x0D) ^ _gf_mul(a3, 0x09)
        state[index + 1] = _gf_mul(a0, 0x09) ^ _gf_mul(a1, 0x0E) ^ _gf_mul(a2, 0x0B) ^ _gf_mul(a3, 0x0D)
        state[index + 2] = _gf_mul(a0, 0x0D) ^ _gf_mul(a1, 0x09) ^ _gf_mul(a2, 0x0E) ^ _gf_mul(a3, 0x0B)
        state[index + 3] = _gf_mul(a0, 0x0B) ^ _gf_mul(a1, 0x0D) ^ _gf_mul(a2, 0x09) ^ _gf_mul(a3, 0x0E)


def _aes_decrypt_block(block, round_keys):
    state = bytearray(block)
    rounds = len(round_keys) - 1

    _add_round_key(state, round_keys[rounds])
    for round_index in range(rounds - 1, 0, -1):
        _inv_shift_rows(state)
        _inv_sub_bytes(state)
        _add_round_key(state, round_keys[round_index])
        _inv_mix_columns(state)

    _inv_shift_rows(state)
    _inv_sub_bytes(state)
    _add_round_key(state, round_keys[0])
    return bytes(state)


def _pkcs7_unpad(data):
    if not data:
        raise ValueError("Empty padded data")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError("Invalid PKCS7 padding")
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("Invalid PKCS7 padding bytes")
    return data[:-pad_len]


def _aes_cbc_decrypt(ciphertext, key, iv):
    if len(iv) != 16:
        raise ValueError("AES-CBC IV must be 16 bytes")
    if len(ciphertext) % 16 != 0:
        raise ValueError("AES-CBC ciphertext must be a multiple of 16 bytes")

    round_keys = _expand_aes_key(key)
    previous = iv
    plaintext = bytearray()
    for index in range(0, len(ciphertext), 16):
        block = ciphertext[index:index + 16]
        decrypted = _aes_decrypt_block(block, round_keys)
        plaintext.extend(value ^ previous[offset] for offset, value in enumerate(decrypted))
        previous = block
    return _pkcs7_unpad(bytes(plaintext))


def _extract_abyss_payload_parts(payload):
    if len(payload) < 12:
        raise ValueError("Input string is too short to extract the IV and encrypted data.")
    encrypted_padding = int(payload[0:1])
    tail_len = int(payload[1:3])
    iv_padding = int(payload[3:4])
    iv_text = payload[4:14][::-1] + payload[len(payload) - tail_len:] + ("=" * iv_padding)
    encrypted_text = payload[14:len(payload) - tail_len] + ("=" * encrypted_padding)
    return iv_text, encrypted_text


def _decrypt_abyss_payload(payload):
    iv_text, encrypted_text = _extract_abyss_payload_parts(payload)
    iv = base64.b64decode(iv_text)
    ciphertext = base64.b64decode(encrypted_text)
    plaintext = _aes_cbc_decrypt(ciphertext, ABYSS_HOLE_DH_KEY.encode("utf-8"), iv)
    return json.loads(plaintext.decode("utf-8"))


def _parse_abyss_events(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, str):
            decoded = _decrypt_abyss_payload(payload)
            return decoded if isinstance(decoded, list) else []
        for key in ("events", "items", "data"):
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
    if abs(offset_seconds) >= ABYSS_HOLE_TIME_SYNC_THRESHOLD_SECONDS:
        return site_now, offset_seconds, True

    return local_now, offset_seconds, False


def _event_key(event):
    if not event:
        return None
    return str(event.get("start_datetime") or event.get("start") or event.get("started") or "")


def _format_datetime(dt):
    if dt is None:
        return "확인불가"
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_seconds(seconds):
    if seconds is None:
        return "확인불가"
    seconds = max(0, int(seconds))
    hours, remain = divmod(seconds, 3600)
    minutes, second = divmod(remain, 60)
    if hours:
        return f"{hours}시간 {minutes:02d}분 {second:02d}초"
    return f"{minutes:02d}:{second:02d}"


def _extract_abyss_status_from_events(events, kst, now):
    parsed_events = []
    for event in events:
        if not isinstance(event, dict):
            continue
        start = _parse_datetime(event.get("start_datetime") or event.get("start") or event.get("started"), kst)
        end = _parse_datetime(event.get("end_datetime") or event.get("end") or event.get("expired"), kst)
        if start is None:
            continue
        parsed_events.append((start, end, event))

    parsed_events.sort(key=lambda item: item[0])
    current = None
    upcoming = None
    for start, end, event in parsed_events:
        if end is not None and start <= now < end:
            current = (start, end, event)
            break
        if start > now and upcoming is None:
            upcoming = (start, end, event)

    selected = current or upcoming
    if selected is None:
        return {
            "is_open": False if parsed_events else None,
            "seconds_to_start": None,
            "target_remaining_seconds": None,
            "start_datetime": None,
            "end_datetime": None,
            "event": None,
            "events": events,
        }

    start, end, event = selected
    is_open = current is not None
    return {
        "is_open": is_open,
        "seconds_to_start": 0 if is_open else max(0, int((start - now).total_seconds())),
        "target_remaining_seconds": None if end is None else max(0, int((end - now).total_seconds())),
        "start_datetime": start,
        "end_datetime": end,
        "event": event,
        "events": events,
        "is_post_maintenance_estimate": bool(event.get("is_post_maintenance_estimate")),
    }


def fetch_abyss_hole_status(kst):
    req = urlrequest.Request(ABYSS_HOLE_API_URL, headers=_abyss_hole_headers())
    with urlrequest.urlopen(req, timeout=ABYSS_HOLE_REQUEST_TIMEOUT_SECONDS) as response:
        date_header = response.headers.get("Date")
        body = response.read().decode("utf-8")
    data = json.loads(body)

    events = _parse_abyss_events(data)
    reference_now, time_offset_seconds, time_sync_applied = _reference_now_from_date_header(date_header, kst)
    status = _extract_abyss_status_from_events(events, kst, reference_now)
    status["time_offset_seconds"] = time_offset_seconds
    status["time_sync_applied"] = time_sync_applied
    status["raw"] = data
    return status


def get_abyss_hole_room_ids(get_db_conn, db_lock):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT room_id FROM abyss_hole_rooms ORDER BY added_date DESC LIMIT 1")
        room_ids = [str(row["room_id"]) for row in cur.fetchall() if row["room_id"]]
        conn.close()

    return room_ids


def select_abyss_hole_room(room_id, added_by, get_db_conn, db_lock, kst):
    now_time = datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM abyss_hole_rooms")
        cur.execute(
            """
            INSERT INTO abyss_hole_rooms (room_id, added_by, added_date)
            VALUES (?, ?, ?)
            """,
            (str(room_id), int(added_by), now_time),
        )
        conn.commit()
        conn.close()


def clear_abyss_hole_room(room_id, get_db_conn, db_lock):
    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM abyss_hole_rooms WHERE room_id = ?", (str(room_id),))
        deleted_count = cur.rowcount
        conn.commit()
        conn.close()

    return deleted_count > 0


def format_abyss_hole_status(status):
    open_text = "출현중" if status.get("is_open") is True else "대기중" if status.get("is_open") is False else "확인불가"
    lines = [
        "어비스 구멍 체크",
        f"상태: {open_text}",
        f"다음 출현: {_format_datetime(status.get('start_datetime'))}",
    ]

    if status.get("is_open") is True:
        lines.append(f"종료까지: {_format_seconds(status.get('target_remaining_seconds'))}")
    else:
        lines.append(f"출현까지: {_format_seconds(status.get('seconds_to_start'))}")

    if status.get("end_datetime") is not None:
        lines.append(f"종료 예정: {_format_datetime(status.get('end_datetime'))}")

    if status.get("is_post_maintenance_estimate"):
        lines.append("비고: 점검 후 추정 시간")

    if status.get("time_sync_applied"):
        offset_seconds = status.get("time_offset_seconds", 0)
        lines.append(f"시간 보정: {offset_seconds:+d}초")

    return "\n".join(lines)


def _format_abyss_hole_alert_message(status, alert_type):
    start = status.get("start_datetime")
    if alert_type == "pre":
        return f"어비스 구멍 출현 10분 전입니다. 출현 예정: {_format_datetime(start)}"

    message = "어비스 구멍이 출현했습니다."
    target_remaining_seconds = status.get("target_remaining_seconds")
    if target_remaining_seconds is not None:
        remaining_minutes = max(0, int((target_remaining_seconds + 59) // 60))
        message += f" 종료까지 {remaining_minutes}분 전"
    return message


def _next_wait_seconds(status, pre_alert_sent=False, spawn_alert_sent=False):
    wait_seconds = ABYSS_HOLE_CHECK_INTERVAL_SECONDS
    seconds_to_start = status.get("seconds_to_start")
    target_remaining_seconds = status.get("target_remaining_seconds")

    if status.get("is_open") is True:
        if target_remaining_seconds is not None:
            wait_seconds = min(wait_seconds, max(5, target_remaining_seconds + 3))
        return wait_seconds

    if seconds_to_start is None:
        return wait_seconds

    if not pre_alert_sent and seconds_to_start > ABYSS_HOLE_PRE_ALERT_SECONDS:
        return min(wait_seconds, max(5, seconds_to_start - ABYSS_HOLE_PRE_ALERT_SECONDS + 1))
    if not pre_alert_sent and seconds_to_start <= ABYSS_HOLE_PRE_ALERT_SECONDS:
        return 5
    if not spawn_alert_sent and seconds_to_start > 0:
        return min(wait_seconds, max(5, seconds_to_start + 1))

    return wait_seconds


def start_abyss_hole_tracker(bot, send_message, get_db_conn, db_lock, kst):
    global _TRACKER_STARTED

    if not ABYSS_HOLE_TRACKER_ENABLED:
        print("[어구알림] 추적 비활성화(ABYSS_HOLE_TRACKER_ENABLED=0)")
        return

    with _TRACKER_LOCK:
        if _TRACKER_STARTED:
            return
        _TRACKER_STARTED = True

    state = {"event_key": None, "pre_alert_sent": False, "spawn_alert_sent": False}

    def send_to_rooms(status, alert_type, room_ids):
        if not room_ids:
            print(f"[어구알림] 지정된 알림 채팅방이 없어 {alert_type} 알림을 전송하지 않습니다.")
            return
        message = _format_abyss_hole_alert_message(status, alert_type)
        for room_id in room_ids:
            send_message(bot, room_id, message)

    def run():
        wait_seconds = 5
        while True:
            time.sleep(max(1, wait_seconds))

            try:
                status = fetch_abyss_hole_status(kst)
                event_key = _event_key(status.get("event"))
                is_open = status.get("is_open")
                seconds_to_start = status.get("seconds_to_start")
                target_remaining_seconds = status.get("target_remaining_seconds")
                time_offset_seconds = status.get("time_offset_seconds", 0)
                time_sync_applied = status.get("time_sync_applied")
                room_ids = get_abyss_hole_room_ids(get_db_conn, db_lock)

                if event_key and event_key != state["event_key"]:
                    state["event_key"] = event_key
                    state["pre_alert_sent"] = False
                    state["spawn_alert_sent"] = False

                print(
                    f"[어구알림] open={is_open} start={seconds_to_start} "
                    f"remaining={target_remaining_seconds} time_offset={time_offset_seconds} "
                    f"sync={time_sync_applied} rooms={len(room_ids)}"
                )

                if (
                    is_open is not True
                    and seconds_to_start is not None
                    and seconds_to_start <= ABYSS_HOLE_PRE_ALERT_SECONDS
                    and not state["pre_alert_sent"]
                ):
                    send_to_rooms(status, "pre", room_ids)
                    state["pre_alert_sent"] = True

                if is_open is True and not state["spawn_alert_sent"]:
                    send_to_rooms(status, "spawn", room_ids)
                    state["spawn_alert_sent"] = True

                wait_seconds = _next_wait_seconds(
                    status,
                    state["pre_alert_sent"],
                    state["spawn_alert_sent"],
                )
                if wait_seconds != ABYSS_HOLE_CHECK_INTERVAL_SECONDS:
                    print(f"[어구알림] 다음 체크 보정: {wait_seconds:.1f}초")

            except Exception as e:
                print(f"[어구알림] 체크 실패: {e}")
                wait_seconds = ABYSS_HOLE_CHECK_INTERVAL_SECONDS

    threading.Thread(target=run, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="어비스 구멍 상태 확인")
    parser.add_argument("--timezone", default="Asia/Seoul", help="표시 타임존. 기본값: Asia/Seoul")
    args = parser.parse_args()

    try:
        from zoneinfo import ZoneInfo
        kst = ZoneInfo(args.timezone)
    except Exception:
        import pytz
        kst = pytz.timezone(args.timezone)

    print(format_abyss_hole_status(fetch_abyss_hole_status(kst)))


if __name__ == "__main__":
    main()
