import sqlite3
import random
import threading
import time
import traceback
from datetime import datetime, date, timedelta
import pytz
from iris import ChatContext, PyKV
import re
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from bots.barter_info import (
    create_barter_tables,
    handle_barter_commands,
    seed_barter_data,
)
from bots.rune_info import (
    create_rune_tables,
    handle_rune_commands,
    seed_rune_data,
)
from bots.abyss_hole_alert import (
    ABYSS_HOLE_CHECK_INTERVAL_SECONDS,
    clear_abyss_hole_room,
    create_abyss_hole_tables,
    fetch_abyss_hole_status,
    format_abyss_hole_status,
    get_abyss_hole_room_ids,
    select_abyss_hole_room,
    start_abyss_hole_tracker,
)
from bots.deep_hole_alert import (
    DEEP_HOLE_CHECK_INTERVAL_SECONDS,
    DEEP_HOLE_TARGET_AREA,
    DEEP_HOLE_TARGET_SERVER,
    clear_deep_hole_room,
    create_deep_hole_tables,
    fetch_deep_hole_status,
    format_deep_hole_status,
    get_deep_hole_room_ids,
    select_deep_hole_room,
    start_deep_hole_tracker,
)

# ─────────────────────────────
# 관리자 설정
# 초기 관리자는 .env의 ADMIN_IDS에 강제 등록
# 이후 관리자는 /관리자추가 명령어로 DB에 저장
# ─────────────────────────────

def load_env_admin_ids():
    """
    .env의 ADMIN_IDS 값을 읽어서 관리자 ID 리스트로 변환합니다.
    예: ADMIN_IDS=12345,67890
    """
    admin_raw = os.getenv("ADMIN_IDS", "")
    admin_ids = []

    for aid in admin_raw.split(","):
        aid = aid.strip()
        if not aid:
            continue

        try:
            admin_ids.append(int(aid))
        except ValueError:
            print(f"[관리자 설정 오류] ADMIN_IDS에 숫자가 아닌 값이 있습니다: {aid}")

    return admin_ids

# ─────────────────────────────
# 설정 및 DB 연결
# ─────────────────────────────
DB_FILE = "iris.db"
DB_LOCK = threading.RLock()
KST = pytz.timezone('Asia/Seoul')
pending_deletions = {}

def get_db_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                job TEXT DEFAULT '초보자',
                join_date TEXT,
                total_checkin INTEGER DEFAULT 0,
                consecutive_checkin INTEGER DEFAULT 0,
                last_checkin_date TEXT,
                total_chat INTEGER DEFAULT 0,
                today_chat INTEGER DEFAULT 0,
                last_chat_date TEXT,
                points INTEGER DEFAULT 0,
                spent_points INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lotto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                lotto_date TEXT,
                numbers TEXT,
                is_drawn INTEGER DEFAULT 0,
                room_id TEXT
            )
        """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS name_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        old_name TEXT,
                        new_name TEXT,
                        change_date TEXT
                    )
                """)

        # ✅ 아이템 정의 테이블
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS items (
                        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_name TEXT UNIQUE,
                        price INTEGER,
                        description TEXT
                    )
                """)

        # ✅ 유저 인벤토리 테이블
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS inventory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        item_id INTEGER,
                        quantity INTEGER DEFAULT 1,
                        purchase_date TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(user_id),
                        FOREIGN KEY(item_id) REFERENCES items(item_id)
                    )
                """)

        # ✅ 아이템 사용 처리 로그 테이블
        # 관리자가 /사용처리 로 차감한 기록을 남깁니다.
        # item_name을 함께 저장하는 이유: /상점삭제 로 items에서 사라져도 내역은 남아야 합니다.
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS item_usage_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        item_id INTEGER,
                        item_name TEXT,
                        quantity INTEGER,
                        processed_by INTEGER,
                        processed_date TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(user_id)
                    )
                """)

        # ✅ 상점 활동 통합 로그 테이블
        # 구매(/구매)와 사용 처리(/사용처리)를 한 테이블에 모아 /상점로그 로 조회합니다.
        # user_name / item_name 을 함께 저장하는 이유:
        #   유저가 닉네임을 바꾸거나 /유저삭제 되어도, 아이템이 /상점삭제 되어도
        #   "그 시점에 누가 무엇을" 했는지가 그대로 읽혀야 하기 때문입니다.
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS shop_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        action TEXT NOT NULL,
                        user_id INTEGER,
                        user_name TEXT,
                        item_id INTEGER,
                        item_name TEXT,
                        quantity INTEGER,
                        price INTEGER,
                        points_after INTEGER,
                        processed_by INTEGER,
                        log_date TEXT
                    )
                """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_shop_logs_action ON shop_logs(action, id DESC)")

        # ✅ 기존 item_usage_logs 를 shop_logs 로 1회 이관합니다.
        # 원본은 지우지 않고 복사만 하므로, 문제가 생겨도 되돌릴 수 있습니다.
        # shop_logs 가 비어 있을 때만 수행되어 재시작마다 중복 적재되지 않습니다.
        cur.execute("SELECT COUNT(*) AS count FROM shop_logs")
        if cur.fetchone()["count"] == 0:
            cur.execute("""
                        INSERT INTO shop_logs
                            (action, user_id, user_name, item_id, item_name,
                             quantity, price, points_after, processed_by, log_date)
                        SELECT '사용', old.user_id, u.name, old.item_id, old.item_name,
                               old.quantity, NULL, NULL, old.processed_by, old.processed_date
                        FROM item_usage_logs old
                        LEFT JOIN users u ON old.user_id = u.user_id
                        ORDER BY old.id ASC
                    """)

        # ✅ 복권 추첨 회차 로그
        # 당첨자가 없어도 1행 남깁니다. 당첨번호는 지금까지 채팅으로만 흘러가고
        # 어디에도 남지 않아, 지난 회차를 되짚을 방법이 없었습니다.
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS lotto_draws (
                        draw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT,
                        winning_number TEXT,
                        ticket_count INTEGER,
                        invalid_count INTEGER,
                        first_count INTEGER,
                        second_count INTEGER,
                        total_payout INTEGER,
                        draw_date TEXT
                    )
                """)

        # ✅ 복권 당첨자 로그
        # user_name / ticket_number 를 함께 저장하는 이유는 shop_logs 와 같습니다.
        # 닉네임이 바뀌거나 /유저삭제 된 뒤에도 "누가 무엇으로 탔는지"가 읽혀야 합니다.
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS lotto_wins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        draw_id INTEGER,
                        user_id INTEGER,
                        user_name TEXT,
                        ticket_number TEXT,
                        win_rank INTEGER,
                        prize INTEGER,
                        draw_date TEXT,
                        FOREIGN KEY(draw_id) REFERENCES lotto_draws(draw_id)
                    )
                """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lotto_wins_draw ON lotto_wins(draw_id)")

        # ✅ 관리자 테이블
        # .env에 들어있는 초기 관리자와 명령어로 추가한 관리자를 모두 저장합니다.
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        admin_id INTEGER PRIMARY KEY,
                        added_by INTEGER,
                        added_date TEXT,
                        memo TEXT
                    )
                """)
        create_deep_hole_tables(cur)
        create_abyss_hole_tables(cur)
        create_barter_tables(cur)
        create_rune_tables(cur)
        seed_barter_data(cur)
        seed_rune_data(cur)


        cur.execute("PRAGMA table_info(lotto)")
        if 'room_id' not in [c[1] for c in cur.fetchall()]:
            cur.execute("ALTER TABLE lotto ADD COLUMN room_id TEXT")

        # ✅ .env 초기 관리자 DB 동기화
        # 최초 관리자는 .env에 ADMIN_IDS=123,456 형태로 강제 등록합니다.
        # 봇 재시작 시 .env 관리자가 DB admins 테이블에 자동 반영됩니다.
        env_admin_ids = load_env_admin_ids()
        now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        for env_admin_id in env_admin_ids:
            cur.execute("""
                        INSERT OR IGNORE INTO admins (admin_id, added_by, added_date, memo)
                        VALUES (?, ?, ?, ?)
                    """, (env_admin_id, 0, now_time, "ENV_INITIAL_ADMIN"))

        conn.commit()
        conn.close()


init_db()


# ─────────────────────────────
# 관리자 유틸리티
# ─────────────────────────────

def is_admin(user_id):
    """
    관리자 여부 확인.
    .env 관리자 + DB admins 테이블 관리자 모두 허용합니다.
    """
    try:
        user_id = int(user_id)
    except Exception:
        return False

    # 1차: .env 관리자 확인
    if user_id in load_env_admin_ids():
        return True

    # 2차: DB 관리자 확인
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()

    return row is not None


def add_admin(admin_id, added_by, memo="COMMAND_ADDED"):
    """
    관리자 추가.
    반환값: (성공 여부, 메시지)
    """
    try:
        admin_id = int(admin_id)
        added_by = int(added_by)
    except ValueError:
        return False, "관리자 ID는 숫자여야 합니다."

    now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (admin_id,))
        exists = cur.fetchone()

        if exists:
            conn.close()
            return False, "이미 등록된 관리자입니다."

        cur.execute("""
                    INSERT INTO admins (admin_id, added_by, added_date, memo)
                    VALUES (?, ?, ?, ?)
                """, (admin_id, added_by, now_time, memo))

        conn.commit()
        conn.close()

    return True, "관리자로 추가되었습니다."


def get_admin_list():
    """
    관리자 목록 조회.
    """
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
                    SELECT admin_id, added_by, added_date, memo
                    FROM admins
                    ORDER BY added_date ASC
                """)
        rows = cur.fetchall()
        conn.close()

    return rows


def remove_admin(admin_id):
    """
    관리자 삭제.
    단, .env에 들어있는 초기 관리자는 DB에서 삭제해도 다시 동기화될 수 있으므로 삭제를 막습니다.
    반환값: (성공 여부, 메시지)
    """
    try:
        admin_id = int(admin_id)
    except ValueError:
        return False, "관리자 ID는 숫자여야 합니다."

    if admin_id in load_env_admin_ids():
        return False, ".env에 등록된 초기 관리자는 명령어로 삭제할 수 없습니다."

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT admin_id FROM admins WHERE admin_id = ?", (admin_id,))
        exists = cur.fetchone()

        if not exists:
            conn.close()
            return False, "등록되지 않은 관리자입니다."

        cur.execute("DELETE FROM admins WHERE admin_id = ?", (admin_id,))
        conn.commit()
        conn.close()

    return True, "관리자에서 삭제되었습니다."


# ─────────────────────────────
# 유틸리티
# ─────────────────────────────

TAGGED_USER_SQL_CONDITION = "name LIKE '%[%' AND name LIKE '%]%'"

CHECKIN_REWARD_POINT = 10        # 출석체크 1회 적립 포인트
LOTTO_DRAW_HOUR = 6              # 복권 추첨 시각(시). 스케줄러와 안내 문구가 함께 씁니다.
LOTTO_MIN_NUMBER = 111
LOTTO_MAX_NUMBER = 222
LOTTO_FIRST_PRIZE = 300
LOTTO_SECOND_PRIZE = 150
USE_LEGACY_PROBABILITY_LOTTO_DRAW = False

# 티켓 1장이 2등에 당첨될 목표 확률.
# 발행 번호 범위(111~222)를 그대로 둔 채 당첨번호 추첨만 조작해 이 값에 맞춥니다.
# 범위를 손대지 않는 이유: 유저가 받는 번호의 생김새가 바뀌지 않아야 하기 때문입니다.
# None 을 넣으면 조작 없이 균등 추첨(2등 약 13.9%)으로 돌아갑니다.
LOTTO_TARGET_SECOND_RATE = 0.05


def _lotto_info_lines():
    """
    복권 안내 문구.

    상금과 추첨 시각을 상수에서 그대로 읽으므로,
    설정을 바꾸면 유저에게 나가는 안내도 같이 바뀝니다.
    """
    return [
        "────────",
        f"⏰ 매일 오전 {LOTTO_DRAW_HOUR}시 추첨",
        f"🥇 1등 🅟{LOTTO_FIRST_PRIZE:,}  ·  🥈 2등 🅟{LOTTO_SECOND_PRIZE:,}",
        "💡 모은 포인트는 /상점 에서 사용할 수 있어요",
    ]


def _format_lotto_number(number):
    return f"{int(number):03d}"


def _generate_lotto_number():
    return _format_lotto_number(random.randint(LOTTO_MIN_NUMBER, LOTTO_MAX_NUMBER))


def _is_valid_lotto_number(number):
    try:
        lotto_number = int(str(number).strip())
    except (TypeError, ValueError):
        return False

    return LOTTO_MIN_NUMBER <= lotto_number <= LOTTO_MAX_NUMBER


def _count_lotto_digit_matches(user_number, winning_number):
    user_number = _format_lotto_number(user_number)
    winning_number = _format_lotto_number(winning_number)
    return sum(1 for i in range(3) if user_number[i] == winning_number[i])


def _pick_legacy_probability_lotto_number(tickets):
    """기존 확률식 산출 로직. 재활용 가능성을 위해 보관하고 기본값에서는 사용하지 않습니다."""
    taken_numbers = {str(t['numbers']).strip() for t in tickets if _is_valid_lotto_number(t['numbers'])}

    for t in tickets:
        if not _is_valid_lotto_number(t['numbers']):
            continue
        if random.randint(1, 100) == 1:
            return _format_lotto_number(t['numbers'])

    for _ in range(1000):
        temp_num = _generate_lotto_number()
        if temp_num not in taken_numbers:
            return temp_num

    return _generate_lotto_number()


def _lotto_candidate_rates(ticket_numbers):
    """
    후보 당첨번호(111~222) 각각에 대해 이번 티켓 풀의 1등/2등 당첨 비율을 계산합니다.

    당첨번호는 하나뿐이므로 그 하나를 무엇으로 고르느냐가 당첨자 수를 전부 결정합니다.
    즉 후보별 결과를 미리 알 수 있고, 그래서 확률 통제가 가능합니다.
    """
    total = len(ticket_numbers)
    rates = []

    for candidate in range(LOTTO_MIN_NUMBER, LOTTO_MAX_NUMBER + 1):
        candidate_text = _format_lotto_number(candidate)
        first = 0
        second = 0

        for ticket_number in ticket_numbers:
            match_cnt = _count_lotto_digit_matches(ticket_number, candidate_text)
            if match_cnt == 3:
                first += 1
            elif match_cnt == 2:
                second += 1

        rates.append((candidate_text, first / total, second / total))

    return rates


def _pick_controlled_lotto_number(tickets):
    """
    2등 당첨률이 LOTTO_TARGET_SECOND_RATE 에 수렴하도록 당첨번호를 고릅니다.

    후보를 '목표 이하'와 '목표 초과' 두 무리로 나누고,
    두 무리의 평균 당첨률이 정확히 목표가 되는 비율 alpha 로 무리를 먼저 뽑습니다.
    무리 안에서는 균등 추첨하므로 당첨번호가 한 값에 고정되지 않습니다.
    """
    numbers = [
        _format_lotto_number(t['numbers'])
        for t in tickets
        if _is_valid_lotto_number(t['numbers'])
    ]
    if not numbers:
        return _generate_lotto_number()

    target = LOTTO_TARGET_SECOND_RATE
    rates = _lotto_candidate_rates(numbers)

    low = [r for r in rates if r[2] <= target]
    high = [r for r in rates if r[2] > target]

    # 어떤 번호를 골라도 목표 이하면 그냥 균등 추첨해도 목표를 넘지 않습니다.
    if not high:
        return random.choice(rates)[0]

    # 반대로 전부 목표 초과면 가장 당첨자가 적은 쪽으로 붙입니다.
    if not low:
        floor = min(r[2] for r in rates)
        return random.choice([r for r in rates if r[2] == floor])[0]

    mean_low = sum(r[2] for r in low) / len(low)
    mean_high = sum(r[2] for r in high) / len(high)
    if mean_high <= mean_low:
        return random.choice(low)[0]

    alpha = (target - mean_low) / (mean_high - mean_low)
    alpha = min(max(alpha, 0.0), 1.0)

    group = high if random.random() < alpha else low
    return random.choice(group)[0]


# 스케줄러 생존 상태. /복권상태 로 조회합니다.
# 데몬 스레드가 조용히 죽으면 추첨이 영구 정지하는데 지금까지는 알 방법이 없었습니다.
LOTTO_SCHEDULER_STATE = {
    "started_at": None,
    "next_run": None,
    "last_run": None,
    "last_result": None,
    "last_error": None,
    "run_count": 0,
    "error_count": 0,
    "alive": False,
}

LOTTO_LOG_DEFAULT_LIMIT = 10
LOTTO_LOG_MAX_LIMIT = 30


def _lotto_now_text():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _write_lotto_log(cur, room_id, winning_number, ticket_count, invalid_count, winner_rows):
    """
    추첨 회차 1건과 그 회차의 당첨자들을 기록합니다.

    당첨자가 없어도 회차 행은 남깁니다. "그날 당첨번호가 뭐였나"는
    당첨자 유무와 무관하게 답할 수 있어야 하기 때문입니다.
    호출부의 트랜잭션에 얹히므로 여기서 commit 하지 않습니다.
    """
    draw_date = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    total_payout = sum(row[4] for row in winner_rows)
    first_count = sum(1 for row in winner_rows if row[3] == 1)
    second_count = sum(1 for row in winner_rows if row[3] == 2)

    cur.execute("""
                INSERT INTO lotto_draws
                    (room_id, winning_number, ticket_count, invalid_count,
                     first_count, second_count, total_payout, draw_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (room_id, winning_number, ticket_count, invalid_count,
                  first_count, second_count, total_payout, draw_date))
    draw_id = cur.lastrowid

    for user_id, user_name, ticket_number, win_rank, prize in winner_rows:
        cur.execute("""
                    INSERT INTO lotto_wins
                        (draw_id, user_id, user_name, ticket_number, win_rank, prize, draw_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (draw_id, user_id, user_name, ticket_number, win_rank, prize, draw_date))

    return draw_id


def _pick_lotto_winning_number(tickets):
    if USE_LEGACY_PROBABILITY_LOTTO_DRAW:
        return _pick_legacy_probability_lotto_number(tickets)

    if LOTTO_TARGET_SECOND_RATE is None:
        return _generate_lotto_number()

    return _pick_controlled_lotto_number(tickets)


def _safe_debug_text(value, limit=120):
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _sender_debug_snapshot(sender):
    values = {}
    for attr_name in (
        "id",
        "name",
        "nickname",
        "profile_name",
        "open_profile_name",
        "display_name",
        "user_name",
    ):
        if hasattr(sender, attr_name):
            try:
                values[attr_name] = getattr(sender, attr_name)
            except Exception as exc:
                values[attr_name] = f"<error:{exc}>"

    raw_dict = getattr(sender, "__dict__", None)
    if isinstance(raw_dict, dict):
        for key, value in raw_dict.items():
            if key.startswith("_") or key in values:
                continue
            values[key] = value

    return ", ".join(f"{key}={_safe_debug_text(value)}" for key, value in values.items())


def _get_chat_room_id(chat):
    room = getattr(chat, "room", None)
    room_id = getattr(room, "id", None)
    if room_id is not None:
        return str(room_id)

    message = getattr(chat, "message", None)
    for attr_name in ("room_id", "chat_id", "involved_chat_id"):
        value = getattr(message, attr_name, None)
        if value is not None:
            return str(value)

    return None


def _command_param(chat):
    """
    명령어 뒤에 붙은 인자를 안전하게 꺼냅니다.

    getattr(msg, "param", "") 는 속성이 '없을 때만' 기본값을 돌려줍니다.
    Iris는 인자 없이 온 명령에 param=None 을 채워 넣으므로 속성은 존재하고,
    그대로 .strip() 을 부르면 AttributeError 로 명령 전체가 죽습니다.
    """
    return str(getattr(getattr(chat, "message", None), "param", "") or "").strip()


def _latest_open_chat_nickname(user_id, room_id=None):
    try:
        history = PyKV().get("user_history")
    except Exception as exc:
        print(f"[닉네임소스] PyKV user_history 조회 실패: {exc}", flush=True)
        return None

    if not isinstance(history, dict):
        return None

    user_history = None
    for key in (user_id, str(user_id)):
        if key in history:
            user_history = history[key]
            break

    if user_history is None:
        for key, value in history.items():
            if str(key) == str(user_id):
                user_history = value
                break

    if not isinstance(user_history, dict):
        return None

    entries = user_history.get("history")
    if not isinstance(entries, list):
        return None

    candidates = list(reversed(entries))
    if room_id:
        room_candidates = [
            entry for entry in candidates
            if isinstance(entry, dict) and str(entry.get("involved_chat_id")) == str(room_id)
        ]
        if room_candidates:
            candidates = room_candidates

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        nickname = str(entry.get("nickname") or "").strip()
        if nickname:
            return nickname

    return None


SHOP_LOG_ACTIONS = ("구매", "사용")
SHOP_LOG_DEFAULT_LIMIT = 15
SHOP_LOG_MAX_LIMIT = 30


def _write_shop_log(cur, action, user_id, user_name, item_id, item_name, quantity,
                    price=None, points_after=None, processed_by=None, log_date=None):
    """
    상점 활동 로그 1건 기록.

    호출한 쪽의 트랜잭션에 얹히므로 여기서 commit 하지 않습니다.
    실패 시 호출부의 rollback 으로 본 처리와 함께 되돌아가야 하기 때문입니다.
    """
    if log_date is None:
        log_date = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
                INSERT INTO shop_logs
                    (action, user_id, user_name, item_id, item_name,
                     quantity, price, points_after, processed_by, log_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (action, user_id, user_name, item_id, item_name,
                  quantity, price, points_after, processed_by, log_date))


def _format_shop_log_lines(rows):
    """/상점로그 · /사용내역 공용 출력 포맷."""
    lines = []
    for row in rows:
        icon = "🛍️" if row["action"] == "구매" else "✅"
        user_name = row["user_name"] or "(알 수 없음)"
        # log_date 는 'YYYY-MM-DD HH:MM:SS' 형식. 연도와 초는 잘라 한 줄에 담습니다.
        stamp = str(row["log_date"] or "")[5:16]

        detail = f"📦 {row['item_name']} x{row['quantity']}"
        if row["action"] == "구매" and row["price"] is not None:
            detail += f" · 🅟{row['price']:,}"
            if row["points_after"] is not None:
                detail += f" → 잔액 🅟{row['points_after']:,}"

        lines.append(f"{icon} {row['action']} | 👤 {user_name}")
        lines.append(f"   ㄴ {detail} · 🕒 {stamp}")
    return lines


def _fetch_owned_items():
    """
    보유 수량이 남아있는 (유저 × 아이템) 목록.

    /구매목록 과 /사용처리 가 이 함수를 공유해야 번호가 서로 어긋나지 않습니다.
    items는 LEFT JOIN 입니다. /상점삭제 로 아이템이 지워져도 인벤토리 행은 남기 때문에,
    INNER JOIN이면 그 행이 목록에서 사라져 영영 정리할 수 없게 됩니다.
    """
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
                    SELECT inv.id        AS inv_id,
                           inv.user_id   AS user_id,
                           inv.item_id   AS item_id,
                           inv.quantity  AS quantity,
                           u.name        AS user_name,
                           COALESCE(i.item_name, '(삭제된 아이템 #' || inv.item_id || ')') AS item_name
                    FROM inventory inv
                    JOIN users u ON inv.user_id = u.user_id
                    LEFT JOIN items i ON inv.item_id = i.item_id
                    WHERE inv.quantity > 0
                    ORDER BY u.name ASC, item_name ASC
                """)
        rows = cur.fetchall()
        conn.close()

    return rows


def _get_or_create_user(chat: ChatContext):
    uid = chat.sender.id
    cmd = getattr(chat.message, "command", "")
    sender_name = str(chat.sender.name or f"User{uid}").strip()
    room_id = _get_chat_room_id(chat)
    open_chat_name = _latest_open_chat_nickname(uid, room_id)
    current_name = open_chat_name or sender_name
    name_source = "open_chat_member" if open_chat_name else "sender.name"
    today = datetime.now(KST).date().isoformat()
    now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    # ✅ 직업 추출 로직 (대괄호 [] 또는 소괄호 () 안의 텍스트 추출)
    # 예: "홍길동 [전사]" -> "전사" / "임꺽정(궁수)" -> "궁수"
    job_match = re.search(r'[\[\(](.+?)[\]\)]', current_name)
    extracted_job = job_match.group(1) if job_match else None

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        row = cur.fetchone()

        if row is None:
            # 신규 유저 등록 (추출된 직업이 있으면 넣고, 없으면 기본값 '초보자')
            job_to_save = extracted_job if extracted_job else '초보자'
            cur.execute(
                "INSERT INTO users (user_id, name, job, join_date) VALUES (?, ?, ?, ?)",
                (uid, current_name, job_to_save, datetime.now(KST).strftime("%Y-%m-%d"))
            )
            conn.commit()
            row = cur.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()

        user = dict(row)
        db_name_before = str(user.get('name') or "")
        nickname_debug_enabled = os.getenv("NICKNAME_DEBUG_LOG", "0").strip() == "1"
        should_log_nickname_check = cmd == "/내정보" or db_name_before != current_name or nickname_debug_enabled
        if should_log_nickname_check:
            print(
                f"[닉네임체크] cmd={cmd or '-'} user_id={uid} "
                f"name.source={name_source} current.name={current_name!r} "
                f"sender.name={sender_name!r} open_chat.nickname={open_chat_name!r} "
                f"db.name={db_name_before!r} room_id={room_id!r} "
                f"sender=({_sender_debug_snapshot(chat.sender)})",
                flush=True,
            )

        # ✅ 닉네임 변경 감지 및 직업 업데이트
        updates = []
        params = []

        # 1. 닉네임 변경 확인
        if str(user['name']) != current_name:
            old_name = user['name']
            cur.execute("INSERT INTO name_logs (user_id, old_name, new_name, change_date) VALUES (?, ?, ?, ?)",
                        (uid, old_name, current_name, now_time))

            updates.append("name = ?")
            params.append(current_name)

            print(
                f"[닉네임변경] user_id={uid} old={old_name!r} new={current_name!r} "
                f"change_date={now_time}",
                flush=True,
            )
            chat.reply(
                f"닉네임 변경 감지\n"
                f"{old_name} -> {current_name}\n"
                f"닉네임이 수정되었습니다."
            )
            user['name'] = current_name

        # 2. 직업 업데이트 확인 (추출된 직업이 있고, 기존과 다를 때만)
        if extracted_job and user.get('job') != extracted_job:
            updates.append("job = ?")
            params.append(extracted_job)
            user['job'] = extracted_job
            # (선택 사항) 직업 변경 알림을 띄우고 싶다면 아래 주석 해제
            # chat.reply(f"⚔️ 직업 변경: [{extracted_job}]")

        # DB 업데이트 실행
        if updates:
            params.append(uid)
            cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
            conn.commit()
            if should_log_nickname_check:
                print(
                    f"[닉네임체크완료] user_id={uid} saved.name={user.get('name')!r} "
                    f"saved.job={user.get('job')!r}",
                    flush=True,
                )

        # 채팅 카운트 업데이트
        total_chat = int(user.get('total_chat') or 0)
        today_chat = int(user.get('today_chat') or 0)
        new_cnt = 1 if user['last_chat_date'] != today else today_chat + 1
        cur.execute("UPDATE users SET total_chat=total_chat+1, today_chat=?, last_chat_date=? WHERE user_id=?",
                    (new_cnt, today, uid))
        user['total_chat'] = total_chat + 1
        user['today_chat'] = new_cnt
        user['last_chat_date'] = today
        conn.commit()
        conn.close()

        return user


def safe_send_message(bot, room_id, text):
    """Bot.api 객체를 정밀 탐색하여 메시지 전송 시도"""
    try:
        if hasattr(bot, 'api'):
            api = bot.api

            if hasattr(api, 'send_text'):
                return api.send_text(room_id, text)
            elif hasattr(api, 'send_message'):
                return api.send_message(room_id, text)
            elif hasattr(api, 'send'):
                return api.send(room_id, text)
            elif hasattr(api, 'chat'):
                return api.chat(room_id, text)
            elif hasattr(api, 'reply'):
                return api.reply(room_id, text)

        if hasattr(bot, 'send_text'):
            return bot.send_text(room_id, text)
        if hasattr(bot, 'send_message'):
            return bot.send_message(room_id, text)

        print("[오류] 전송 가능한 메서드를 찾지 못했습니다.")

    except Exception as e:
        print(f"[전송실패] 방 {room_id} 에러: {e}")


# ─────────────────────────────
# 스케줄러 & 복권 추첨
# ─────────────────────────────

def start_lotto_scheduler(bot):
    start_deep_hole_tracker(bot, safe_send_message, get_db_conn, DB_LOCK, KST)
    start_abyss_hole_tracker(bot, safe_send_message, get_db_conn, DB_LOCK, KST)

    def run():
        LOTTO_SCHEDULER_STATE["started_at"] = _lotto_now_text()
        LOTTO_SCHEDULER_STATE["alive"] = True

        while True:
            # 대기 시간 계산까지 try 안에 둡니다.
            # 이 스레드가 죽으면 봇은 멀쩡히 돌면서 추첨만 영구 정지하기 때문입니다.
            try:
                now = datetime.now(KST)

                # ✅ 테스트용: 1분 뒤 실행 (테스트 끝나면 주석 처리)
                # target = now + timedelta(minutes=1)

                # [운영용] 매일 오전 6시
                target = now.replace(hour=LOTTO_DRAW_HOUR, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)

                LOTTO_SCHEDULER_STATE["next_run"] = target.strftime("%Y-%m-%d %H:%M:%S")
                wait_sec = (target - now).total_seconds()
                print(f"[시스템] 다음 추첨({target.strftime('%H:%M:%S')})까지 {wait_sec:.1f}초 대기...")

                time.sleep(wait_sec)
            except Exception as e:
                LOTTO_SCHEDULER_STATE["error_count"] += 1
                LOTTO_SCHEDULER_STATE["last_error"] = f"대기 계산 실패 {type(e).__name__}: {e}"
                print(f"[복권] 대기 계산 실패: {type(e).__name__}: {e}")
                traceback.print_exc()
                time.sleep(60)
                continue

            try:
                execute_lotto_draw(bot)
                LOTTO_SCHEDULER_STATE["run_count"] += 1
                LOTTO_SCHEDULER_STATE["last_result"] = "성공"
                LOTTO_SCHEDULER_STATE["last_error"] = None
            except Exception as e:
                # 한 회차가 실패해도 스레드는 살려둡니다. 죽으면 내일도 안 돕니다.
                LOTTO_SCHEDULER_STATE["error_count"] += 1
                LOTTO_SCHEDULER_STATE["last_result"] = "실패"
                LOTTO_SCHEDULER_STATE["last_error"] = f"{type(e).__name__}: {e}"
                print(f"[복권] 추첨 실패: {type(e).__name__}: {e}")
                traceback.print_exc()
            finally:
                LOTTO_SCHEDULER_STATE["last_run"] = _lotto_now_text()

            time.sleep(5)

    threading.Thread(target=run, daemon=True).start()


def execute_lotto_draw(bot):
    with DB_LOCK:
        conn = get_db_conn()

        # 추첨 도중 실패하면 포인트 지급과 로그가 함께 롤백되어야 합니다.
        # 예외는 삼키지 않고 다시 올려, 스케줄러가 실패를 기록하게 합니다.
        try:
            cur = conn.cursor()

            cur.execute("SELECT DISTINCT room_id FROM lotto WHERE is_drawn=0")
            rooms = [r['room_id'] for r in cur.fetchall() if r['room_id']]

            # room_id 가 없는 티켓은 결과를 방송할 곳이 없어 추첨에서 빠집니다.
            # 그대로 두면 is_drawn=0 으로 남아 그 유저가 새 복권을 받지 못하므로
            # 정산은 하되, 조용히 사라지지 않도록 흔적을 남깁니다.
            cur.execute("SELECT COUNT(*) AS count FROM lotto"
                        " WHERE is_drawn=0 AND (room_id IS NULL OR room_id = '')")
            orphan_count = cur.fetchone()["count"]
            if orphan_count:
                print(f"[복권] 방 정보 없는 티켓 {orphan_count}건은 방송할 곳이 없어"
                      f" 추첨 없이 정산 처리합니다.")

            for rid in rooms:
                # 해당 방의 티켓 정보 가져오기
                cur.execute("""
                    SELECT l.user_id, l.numbers, u.name 
                    FROM lotto l 
                    JOIN users u ON l.user_id = u.user_id 
                    WHERE l.room_id=? AND l.is_drawn=0
                """, (rid,))

                tickets = cur.fetchall()
                winning_number = _pick_lotto_winning_number(tickets)

                # 3. 채점 및 포인트 지급
                w1_list = []
                w2_list = []
                invalid_ticket_count = 0

                winner_rows = []

                for t in tickets:
                    u_num = t['numbers']
                    if not _is_valid_lotto_number(u_num):
                        invalid_ticket_count += 1
                        continue

                    match_cnt = _count_lotto_digit_matches(u_num, winning_number)

                    if match_cnt == 3:
                        w1_list.append(t['name'])
                        cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (LOTTO_FIRST_PRIZE, t['user_id']))
                        winner_rows.append((t['user_id'], t['name'], _format_lotto_number(u_num), 1, LOTTO_FIRST_PRIZE))
                    elif match_cnt == 2:
                        w2_list.append(t['name'])
                        cur.execute("UPDATE users SET points=points+? WHERE user_id=?", (LOTTO_SECOND_PRIZE, t['user_id']))
                        winner_rows.append((t['user_id'], t['name'], _format_lotto_number(u_num), 2, LOTTO_SECOND_PRIZE))

                _write_lotto_log(cur, rid, winning_number,
                                 len(tickets) - invalid_ticket_count, invalid_ticket_count,
                                 winner_rows)

                # 4. 결과 메시지 구성 (요청하신 형식)
                msg_lines = [
                    f"당첨번호 : {winning_number}",
                    "",
                    "[ 당첨자 명단 ]",
                    ""
                ]

                if w1_list or w2_list:
                    if w1_list:
                        msg_lines.append("* 1등 *")
                        for name in w1_list:
                            msg_lines.append(f"🎉 {name}")
                        msg_lines.append("") # 섹션 간 공백

                    if w2_list:
                        msg_lines.append("* 2등 *")
                        for name in w2_list:
                            msg_lines.append(f"• {name}")
                        msg_lines.append("")

                    msg_lines.append("")
                    msg_lines.append("축하합니다!")
                    msg_lines.append(f"1등 당첨자 : 🅟{LOTTO_FIRST_PRIZE}")
                    msg_lines.append(f"2등 당첨자 : 🅟{LOTTO_SECOND_PRIZE}")
                else:
                    msg_lines.append(f"행운의 복권 {len(tickets)}명 추첨 결과")
                    msg_lines.append("────────")
                    msg_lines.append("'푸헤헤헤. 다음 기회에' 로 ")

                if invalid_ticket_count:
                    msg_lines.append("")
                    msg_lines.append(f"범위 밖 복권 {invalid_ticket_count}건은 자동 탈락 처리되었습니다.")

                # 최종 메시지 전송
                safe_send_message(bot, rid, "\n".join(msg_lines))

            # 정산 완료 처리
            cur.execute("UPDATE lotto SET is_drawn=1 WHERE is_drawn=0")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


execute_probability_draw = execute_lotto_draw



# ─────────────────────────────
# 명령어 핸들러
# ─────────────────────────────

def handle_user_commands(chat: ChatContext):
    try:
        admin_id = chat.sender.id
        cmd = getattr(chat.message, "command", "")
        user = _get_or_create_user(chat)

        if handle_barter_commands(chat, get_db_conn, DB_LOCK):
            return True

        if handle_rune_commands(chat, get_db_conn, DB_LOCK):
            return True

        # ─────────────────────────────
        # 관리자 ID 확인
        # 최초 .env에 본인 ID를 넣기 전에 내 ID를 확인해야 하는 경우도 있어서
        # 이 명령어는 비관리자도 자기 ID만 확인 가능하게 열어둡니다.
        # ─────────────────────────────
        if cmd == "/관리자ID":
            admin_status = "관리자" if is_admin(chat.sender.id) else "일반유저"

            chat.reply(
                f"🆔 내 ID 확인\n"
                f"────────\n"
                f"• 내 ID: {chat.sender.id}\n"
                f"• 닉네임: {chat.sender.name}\n"
                f"• 권한: {admin_status}\n"
                f"────────\n"
                f"💡 최초 관리자는 .env에 ADMIN_IDS={chat.sender.id} 형태로 추가 후 봇을 재시작하세요."
            )
            return True

        if cmd == "/심층체크":
            if not is_admin(chat.sender.id):
                return False

            try:
                status = fetch_deep_hole_status(KST)
                chat.reply(format_deep_hole_status(status))
            except Exception as e:
                chat.reply(f"⚠️ 심층 구멍 체크 실패\n{e}")
            return True

        if cmd == "/심구알림시작":
            if not is_admin(chat.sender.id):
                return False

            room_ids = get_deep_hole_room_ids(get_db_conn, DB_LOCK)
            if not room_ids:
                chat.reply(
                    "⚠️ 심구 알림 채팅방이 지정되지 않았습니다.\n"
                    "알림 받을 채팅방에서 /알림선택 을 먼저 실행하세요.\n"
                    "추적 스크립트는 봇 시작 시 자동 실행됩니다."
                )
                return True

            try:
                status = fetch_deep_hole_status(KST)
                status_text = format_deep_hole_status(status)
            except Exception as e:
                status_text = f"현재 상태 확인 실패\n{e}"

            chat.reply(
                f"✅ 심구 알림 추적 중\n"
                f"대상: {DEEP_HOLE_TARGET_SERVER} / {DEEP_HOLE_TARGET_AREA}\n"
                f"체크 간격: {DEEP_HOLE_CHECK_INTERVAL_SECONDS // 60}분\n"
                f"알림방: {', '.join(room_ids)}\n"
                f"※ 알림은 지정된 채팅방에만 전송됩니다.\n\n"
                f"{status_text}"
            )
            return True

        if cmd in ("/어구체크", "/어비스체크"):
            if not is_admin(chat.sender.id):
                return False

            try:
                status = fetch_abyss_hole_status(KST)
                chat.reply(format_abyss_hole_status(status))
            except Exception as e:
                chat.reply(f"⚠️ 어비스 구멍 체크 실패\n{e}")
            return True

        if cmd in ("/어구알림시작", "/어비스알림시작"):
            if not is_admin(chat.sender.id):
                return False

            room_ids = get_abyss_hole_room_ids(get_db_conn, DB_LOCK)
            if not room_ids:
                chat.reply(
                    "⚠️ 어구 알림 채팅방이 지정되지 않았습니다.\n"
                    "알림 받을 채팅방에서 /어구알림선택 을 먼저 실행하세요.\n"
                    "추적 스크립트는 봇 시작 시 자동 실행됩니다."
                )
                return True

            try:
                status = fetch_abyss_hole_status(KST)
                status_text = format_abyss_hole_status(status)
            except Exception as e:
                status_text = f"현재 상태 확인 실패\n{e}"

            chat.reply(
                f"✅ 어구 알림 추적 중\n"
                f"체크 간격: {ABYSS_HOLE_CHECK_INTERVAL_SECONDS // 60}분\n"
                f"알림방: {', '.join(room_ids)}\n"
                f"※ 알림은 지정된 채팅방에만 전송됩니다.\n\n"
                f"{status_text}"
            )
            return True

        if cmd in ("/어구알림선택", "/어비스알림선택"):
            room_id = str(chat.room.id)
            select_abyss_hole_room(room_id, chat.sender.id, get_db_conn, DB_LOCK, KST)
            chat.reply(
                f"✅ 어구 알림 채팅방 선택 완료\n"
                f"선택방: {room_id}\n"
                f"체크 간격: {ABYSS_HOLE_CHECK_INTERVAL_SECONDS // 60}분\n"
                f"※ 기존 선택방은 해제되고, 이 채팅방에만 알림을 전송합니다."
            )
            return True

        if cmd in ("/어구알림선택해제", "/어비스알림선택해제"):
            room_id = str(chat.room.id)
            if clear_abyss_hole_room(room_id, get_db_conn, DB_LOCK):
                chat.reply(
                    f"✅ 어구 알림 채팅방 선택 해제 완료\n"
                    f"해제방: {room_id}\n"
                    f"※ 이제 이 채팅방에는 어구 알림을 전송하지 않습니다."
                )
            else:
                chat.reply(
                    f"ℹ️ 현재 채팅방은 어구 알림방으로 선택되어 있지 않습니다.\n"
                    f"선택방 변경은 알림 받을 채팅방에서 /어구알림선택 을 실행하세요."
                )
            return True

        if cmd == "/알림선택":
            room_id = str(chat.room.id)
            select_deep_hole_room(room_id, chat.sender.id, get_db_conn, DB_LOCK, KST)
            chat.reply(
                f"✅ 심구 알림 채팅방 선택 완료\n"
                f"선택방: {room_id}\n"
                f"대상: {DEEP_HOLE_TARGET_SERVER} / {DEEP_HOLE_TARGET_AREA}\n"
                f"체크 간격: {DEEP_HOLE_CHECK_INTERVAL_SECONDS // 60}분\n"
                f"※ 기존 선택방은 해제되고, 이 채팅방에만 알림을 전송합니다."
            )
            return True

        if cmd == "/알림선택해제":
            room_id = str(chat.room.id)
            if clear_deep_hole_room(room_id, get_db_conn, DB_LOCK):
                chat.reply(
                    f"✅ 심구 알림 채팅방 선택 해제 완료\n"
                    f"해제방: {room_id}\n"
                    f"※ 이제 이 채팅방에는 심구 알림을 전송하지 않습니다."
                )
            else:
                chat.reply(
                    f"ℹ️ 현재 채팅방은 심구 알림방으로 선택되어 있지 않습니다.\n"
                    f"선택방 변경은 알림 받을 채팅방에서 /알림선택 을 실행하세요."
                )
            return True

        # ─────────────────────────────
        # 관리자 전용: 관리자 추가
        # 사용법: /관리자추가 123456789
        # ─────────────────────────────
        if cmd == "/관리자추가":
            if not is_admin(chat.sender.id):
                return False

            param = _command_param(chat)

            if not param:
                chat.reply(
                    "⚠️ 추가할 관리자 ID를 입력해주세요.\n"
                    "예: /관리자추가 123456789"
                )
                return True

            if not param.isdigit():
                chat.reply("⚠️ 관리자 ID는 숫자로 입력해주세요.")
                return True

            target_admin_id = int(param)

            success, message = add_admin(
                admin_id=target_admin_id,
                added_by=chat.sender.id,
                memo="COMMAND_ADDED"
            )

            if success:
                chat.reply(
                    f"✅ 관리자 추가 완료\n"
                    f"────────\n"
                    f"• 추가된 관리자 ID: {target_admin_id}\n"
                    f"• 추가한 관리자 ID: {chat.sender.id}"
                )
            else:
                chat.reply(f"⚠️ 관리자 추가 실패\n{message}")

            return True

        # ─────────────────────────────
        # 관리자 전용: 관리자 삭제
        # 사용법: /관리자삭제 123456789
        # .env 초기 관리자는 삭제 불가
        # ─────────────────────────────
        if cmd == "/관리자삭제":
            if not is_admin(chat.sender.id):
                return False

            param = _command_param(chat)

            if not param:
                chat.reply(
                    "⚠️ 삭제할 관리자 ID를 입력해주세요.\n"
                    "예: /관리자삭제 123456789"
                )
                return True

            if not param.isdigit():
                chat.reply("⚠️ 관리자 ID는 숫자로 입력해주세요.")
                return True

            target_admin_id = int(param)

            if target_admin_id == chat.sender.id:
                chat.reply("⚠️ 자기 자신은 관리자에서 삭제할 수 없습니다.")
                return True

            success, message = remove_admin(target_admin_id)

            if success:
                chat.reply(
                    f"🗑️ 관리자 삭제 완료\n"
                    f"────────\n"
                    f"• 삭제된 관리자 ID: {target_admin_id}"
                )
            else:
                chat.reply(f"⚠️ 관리자 삭제 실패\n{message}")

            return True

        # ─────────────────────────────
        # 관리자 전용: 관리자 목록
        # ─────────────────────────────
        if cmd == "/관리자목록":
            if not is_admin(chat.sender.id):
                return False

            admins = get_admin_list()

            if not admins:
                chat.reply("⚠️ 등록된 관리자가 없습니다.")
                return True

            msg = ["👑 [ 관리자 목록 ]", "────────"]

            for i, admin in enumerate(admins, start=1):
                msg.append(f"{i}. ID: {admin['admin_id']}")
                msg.append(f"   ㄴ 추가자: {admin['added_by']}")
                msg.append(f"   ㄴ 등록일: {admin['added_date']}")
                msg.append(f"   ㄴ 구분: {admin['memo']}")

            msg.append("────────")
            msg.append("💡 추가: /관리자추가 [유저ID]")
            msg.append("💡 삭제: /관리자삭제 [유저ID]")
            chat.reply("\n".join(msg))
            return True

        # ─────────────────────────────
        # 관리자 전용: 삭제 최종 확인 (/유저삭제동의 YES 또는 NO)
        # ─────────────────────────────
        if cmd == "/유저삭제동의":
            if not is_admin(admin_id):
                return False

            param = _command_param(chat).upper()

            if admin_id not in pending_deletions:
                chat.reply("⚠️ 현재 삭제 대기 중인 유저가 없습니다.")
                return True

            if param == "NO":
                pending_deletions.pop(admin_id)  # 대기열에서 제거
                chat.reply("❌ 유저 삭제가 취소되었습니다.")
                return True

            elif param == "YES":
                target_info = pending_deletions.pop(admin_id)
                uid = target_info['target_uid']
                exact_name = target_info['target_name']

                with DB_LOCK:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    try:
                        cur.execute("DELETE FROM inventory WHERE user_id = ?", (uid,))
                        cur.execute("DELETE FROM lotto WHERE user_id = ?", (uid,))
                        cur.execute("DELETE FROM name_logs WHERE user_id = ?", (uid,))
                        cur.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                        conn.commit()
                        chat.reply(f"🗑️ '{exact_name}' 유저의 모든 데이터가 영구 삭제되었습니다.")
                    except Exception as e:
                        conn.rollback()
                        chat.reply(f"❌ 유저 삭제 중 오류 발생: {e}")
                    finally:
                        conn.close()
                return True
            else:
                chat.reply("⚠️ 올바른 형식이 아닙니다.\n예시: /유저삭제동의 YES 또는 /유저삭제동의 NO")
                return True

        if cmd == "ㅊㅊ" or cmd in ["/ㅊㅊ", "!ㅊㅊ"]:
            today_str = datetime.now(KST).date().isoformat()

            if user['last_checkin_date'] == today_str:
                chat.reply("\n".join([
                    "⚠️ 이미 출석했습니다.",
                    f"📅 총 출석: {user['total_checkin']}일",
                    f"🔥 연속 출석: {user['consecutive_checkin']}일",
                    "────────",
                    f"💡 출석은 하루 한 번, 🅟{CHECKIN_REWARD_POINT} 적립됩니다",
                    "🏪 모은 포인트는 /상점 에서 사용할 수 있어요",
                ]))
                return True

            now = datetime.now(KST)
            today = now.date()
            yesterday_str = (today - timedelta(days=1)).isoformat()

            if user['last_checkin_date'] == yesterday_str:
                new_consecutive = user['consecutive_checkin'] + 1
            else:
                new_consecutive = 1

            new_total = user['total_checkin'] + 1

            with DB_LOCK:
                conn = get_db_conn()
                conn.execute(
                    """
                    UPDATE users 
                    SET total_checkin = ?, 
                        consecutive_checkin = ?, 
                        last_checkin_date = ?, 
                        points = points + ?
                    WHERE user_id = ?
                    """,
                    (new_total, new_consecutive, today_str, CHECKIN_REWARD_POINT, user['user_id']))
                conn.commit()
                conn.close()

            chat.reply("\n".join([
                f"✅ 출석 완료! (🅟{CHECKIN_REWARD_POINT})",
                f"📅 총 출석: {new_total}일",
                f"🔥 연속 출석: {new_consecutive}일째",
                "────────",
                f"💡 매일 ㅊㅊ 으로 🅟{CHECKIN_REWARD_POINT} 적립",
                "🎲 /복권자동 으로 무료 복권도 받아가세요",
                "🏪 모은 포인트는 /상점 에서 사용할 수 있어요",
            ]))
            return True

        if cmd == "/내정보":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute("SELECT old_name, new_name FROM name_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                            (user['user_id'],))
                last_log = cur.fetchone()

                cur.execute("""
                            SELECT i.item_name, inv.quantity 
                            FROM inventory inv 
                            JOIN items i ON inv.item_id = i.item_id 
                            WHERE inv.user_id = ? AND inv.quantity > 0
                        """, (user['user_id'],))
                my_items = cur.fetchall()
                conn.close()

            log_text = ""
            if last_log:
                log_text = f"\n•닉네임 변경: {last_log['old_name']}\n➜ {last_log['new_name']}"

            if not my_items:
                inv_text = "보유 아이템이 없습니다."
            else:
                inv_text = ", ".join([f"{item['item_name']}({item['quantity']})" for item in my_items])

            msg = [
                f"🌱 {user['name']}",
                "",
                f"• 클래스 : {user['job']}",
                f"• 가입일 : {user['join_date']}",
                f"• 총 출석일 : {user['total_checkin']}일",
                f"• 연속 출석일 : {user['consecutive_checkin']}일{log_text}",
                "────────",
                f"• 전체 채팅 : {user['total_chat']:,}회",
                f"• 오늘 채팅 : {user['today_chat']:,}회",
                "────────",
                f"• 보유 포인트 : 🅟{user['points']:,}",
                f"• 소비 포인트 : 🅟{user['spent_points']:,}",
                "────────",
                f"• 구매 아이템 :",
                "────────",
                f"{inv_text}"
            ]

            chat.reply("\n".join(msg))
            return True

        if cmd == "/채팅순위":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute(f"SELECT SUM(total_chat) FROM users WHERE {TAGGED_USER_SQL_CONDITION}")
                total_sum_row = cur.fetchone()
                total_sum = total_sum_row[0] if total_sum_row and total_sum_row[0] > 0 else 1

                cur.execute(f"""
                                SELECT name, total_chat, job 
                                FROM users 
                                WHERE {TAGGED_USER_SQL_CONDITION}
                                ORDER BY total_chat DESC 
                                LIMIT 15
                            """)
                rows = cur.fetchall()
                conn.close()

            if not rows:
                chat.reply("데이터가 충분하지 않습니다.")
                return True

            rank_msg = ["🏆 [ 유저 채팅 순위 TOP 15 ]", "────────"]
            medals = ["🥇", "🥈", "🥉"] + ["✨"] * 12

            for i, row in enumerate(rows):
                rank = i + 1
                share = (row['total_chat'] / total_sum) * 100
                rank_msg.append(f"{rank}위: {row['name']}")
                rank_msg.append(f"   ㄴ 누적 채팅: {row['total_chat']:,}회 ({share:.1f}%)")

            rank_msg.append("────────")
            rank_msg.append(f"📊 전체 누적 채팅수: {total_sum:,}회")
            rank_msg.append(f"💡 현재 1위는 {rows[0]['name']}님입니다!")

            chat.reply("\n".join(rank_msg))
            return True

        if cmd == "/복권자동":
            room_id = str(chat.room.id)
            today = datetime.now(KST).date().isoformat()

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute("SELECT numbers FROM lotto WHERE user_id=? AND is_drawn=0", (user['user_id'],))
                row = cur.fetchone()

                if row:
                    chat.reply("\n".join(
                        ["🎫 이미 추첨 대기 중인 복권이 있습니다.",
                         f"번호: [{row['numbers']}]"]
                        + _lotto_info_lines()
                    ))
                else:
                    new_nums = _generate_lotto_number()
                    cur.execute(
                        "INSERT INTO lotto (user_id, lotto_date, numbers, room_id, is_drawn) VALUES (?, ?, ?, ?, 0)",
                        (user['user_id'], today, new_nums, room_id))
                    conn.commit()
                    chat.reply("\n".join(
                        [f"🎲 복권 발행 완료: [{new_nums}]", "(행운을 빕니다!)"]
                        + _lotto_info_lines()
                    ))
                conn.close()
            return True

        if cmd == "/복권정보":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as cnt FROM lotto WHERE is_drawn=0")
                wait_cnt = cur.fetchone()['cnt']
                conn.close()

            chat.reply("\n".join(
                [
                    "🎰 복권 시스템 정보",
                    "",
                    f"번호 범위: {LOTTO_MIN_NUMBER}~{LOTTO_MAX_NUMBER}",
                    f"현재 {wait_cnt}명이 참여 중입니다.",
                    "",
                    "발행은 무료이며 1인 1매입니다.",
                    "💡 /복권자동 으로 복권을 받으세요",
                ]
                + _lotto_info_lines()
            ))
            return True

        # ─────────────────────────────
        # 관리자 전용: 복권 추첨/당첨 로그
        # 당첨번호는 지금까지 채팅으로만 방송되고 어디에도 남지 않았습니다.
        # ─────────────────────────────
        if cmd == "/복권로그":
            if not is_admin(chat.sender.id):
                return False

            winners_only = False
            limit = LOTTO_LOG_DEFAULT_LIMIT

            for token in _command_param(chat).split():
                if token in ("당첨", "당첨자"):
                    winners_only = True
                elif token.isdigit():
                    limit = max(1, min(int(token), LOTTO_LOG_MAX_LIMIT))
                else:
                    chat.reply(
                        "⚠️ 형식: /복권로그 [당첨] [건수]\n"
                        "예: /복권로그\n"
                        "예: /복권로그 당첨\n"
                        "예: /복권로그 당첨 20\n"
                        f"💡 건수는 최대 {LOTTO_LOG_MAX_LIMIT}건까지입니다."
                    )
                    return True

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                if winners_only:
                    cur.execute("""
                                SELECT user_name, ticket_number, win_rank, prize, draw_date
                                FROM lotto_wins
                                ORDER BY id DESC
                                LIMIT ?
                            """, (limit,))
                else:
                    cur.execute("""
                                SELECT winning_number, ticket_count, invalid_count,
                                       first_count, second_count, total_payout, draw_date
                                FROM lotto_draws
                                ORDER BY draw_id DESC
                                LIMIT ?
                            """, (limit,))
                rows = cur.fetchall()

                cur.execute("""
                            SELECT COUNT(*) AS draws,
                                   COALESCE(SUM(first_count), 0)  AS first_total,
                                   COALESCE(SUM(second_count), 0) AS second_total,
                                   COALESCE(SUM(total_payout), 0) AS payout
                            FROM lotto_draws
                        """)
                summary = cur.fetchone()
                conn.close()

            if not rows:
                chat.reply(
                    "📭 복권 기록이 없습니다.\n"
                    "(추첨은 매일 오전 6시에 진행됩니다)"
                )
                return True

            if winners_only:
                msg_lines = ["🎰 [ 복권 당첨자 내역 ]", "────────"]
                for row in rows:
                    icon = "🥇" if row["win_rank"] == 1 else "🥈"
                    stamp = str(row["draw_date"] or "")[5:16]
                    msg_lines.append(f"{icon} {row['win_rank']}등 | 👤 {row['user_name'] or '(알 수 없음)'}")
                    msg_lines.append(f"   ㄴ 번호 {row['ticket_number']} · 🅟{row['prize']:,} · 🕒 {stamp}")
            else:
                msg_lines = ["🎰 [ 복권 추첨 내역 ]", "────────"]
                for row in rows:
                    stamp = str(row["draw_date"] or "")[5:16]
                    msg_lines.append(f"🎯 당첨번호 {row['winning_number']} · {row['ticket_count']}명 참여")

                    if row["first_count"] or row["second_count"]:
                        detail = f"🥇{row['first_count']}명 🥈{row['second_count']}명 · 🅟{row['total_payout']:,}"
                    else:
                        detail = "당첨자 없음"
                    if row["invalid_count"]:
                        detail += f" · 탈락 {row['invalid_count']}건"

                    msg_lines.append(f"   ㄴ {detail} · 🕒 {stamp}")

            msg_lines.append("────────")
            msg_lines.append(
                f"📊 누적 {summary['draws']}회차 · "
                f"1등 {summary['first_total']}명 / 2등 {summary['second_total']}명"
            )
            msg_lines.append(f"💰 총 지급 🅟{summary['payout']:,}")
            if not winners_only:
                msg_lines.append("💡 /복권로그 당첨 [건수] 로 당첨자 명단")

            chat.reply("\n".join(msg_lines))
            return True

        # ─────────────────────────────
        # 관리자 전용: 복권 스케줄러 생존 확인
        # 추첨 스레드는 데몬이라 죽어도 봇은 멀쩡히 돕니다. 눈으로 볼 수단이 필요합니다.
        # ─────────────────────────────
        if cmd == "/복권상태":
            if not is_admin(chat.sender.id):
                return False

            state = LOTTO_SCHEDULER_STATE
            now = datetime.now(KST)

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS count FROM lotto WHERE is_drawn=0")
                pending = cur.fetchone()["count"]
                cur.execute("""
                            SELECT winning_number, ticket_count, draw_date
                            FROM lotto_draws
                            ORDER BY draw_id DESC
                            LIMIT 1
                        """)
                last_draw = cur.fetchone()
                conn.close()

            if not state["alive"]:
                head = "🔴 스케줄러가 기동되지 않았습니다"
            elif state["last_result"] == "실패":
                head = "🟠 마지막 추첨이 실패했습니다"
            else:
                head = "🟢 정상 가동 중"

            msg_lines = ["🩺 [ 복권 스케줄러 상태 ]", "────────", head, ""]
            msg_lines.append(f"🕒 봇 기동: {state['started_at'] or '-'}")

            next_run = state["next_run"]
            if next_run:
                try:
                    target = KST.localize(datetime.strptime(next_run, "%Y-%m-%d %H:%M:%S"))
                    left = int((target - now).total_seconds())
                    left_text = f" ({left // 3600}시간 {left % 3600 // 60}분 후)" if left > 0 else " (지났음)"
                except Exception:
                    left_text = ""
                msg_lines.append(f"⏭️ 다음 추첨: {next_run}{left_text}")
            else:
                msg_lines.append("⏭️ 다음 추첨: 대기 시각 미설정")

            msg_lines.append("────────")
            msg_lines.append(f"📊 실행 {state['run_count']}회 / 실패 {state['error_count']}회")
            if state["last_run"]:
                msg_lines.append(f"🔁 최근 실행: {state['last_run']} ({state['last_result']})")
            else:
                msg_lines.append("🔁 최근 실행: 아직 없음")
            if state["last_error"]:
                msg_lines.append(f"⚠️ 마지막 오류: {state['last_error']}")

            msg_lines.append("────────")
            msg_lines.append(f"🎫 대기 티켓: {pending}장")

            if last_draw:
                stamp = str(last_draw["draw_date"] or "")
                msg_lines.append(
                    f"🎯 최근 회차: {stamp[5:16]} · 당첨번호 {last_draw['winning_number']}"
                    f" · {last_draw['ticket_count']}명"
                )
                # 이틀 넘게 회차 기록이 없으면 스레드가 멈춘 신호일 수 있습니다.
                try:
                    last_dt = KST.localize(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
                    idle_days = (now - last_dt).days
                    if idle_days >= 2:
                        msg_lines.append(f"🚨 {idle_days}일간 추첨 기록이 없습니다. 봇 재시작을 권합니다.")
                except Exception:
                    pass
            else:
                msg_lines.append("🎯 최근 회차: 기록 없음")

            msg_lines.append("────────")
            msg_lines.append("💡 상세 내역은 /복권로그")

            chat.reply("\n".join(msg_lines))
            return True

        if cmd == "/상점":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT * FROM items")
                items = cur.fetchall()
                conn.close()

            shop_msg = ["🏪 [ 포인트 상점 ]", "────────"]
            for item in items:
                shop_msg.append(f"📦 {item['item_name']} - 🅟{item['price']:,}")
                shop_msg.append(f"   ㄴ {item['description']}")
            shop_msg.append("────────")
            shop_msg.append("💡 주문 : /구매 [아이템이름]")
            chat.reply("\n".join(shop_msg))
            return True

        if cmd == "/구매":
            target_item = _command_param(chat)

            if not target_item:
                chat.reply("⚠️ 구매하실 아이템 이름을 입력해주세요.\n예: /구매 확성기")
                return True

            now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute("SELECT * FROM items WHERE item_name = ?", (target_item,))
                item = cur.fetchone()

                if not item:
                    chat.reply(f"❓ '{target_item}'은(는) 상점에 없는 아이템입니다.")
                    conn.close()
                    return True

                cur.execute("SELECT points FROM users WHERE user_id = ?", (user['user_id'],))
                current_points = cur.fetchone()['points']

                if current_points < item['price']:
                    chat.reply(f"🚫 포인트가 부족합니다.\n보유: 🅟{current_points:,} / 필요: 🅟{item['price']:,}")
                    conn.close()
                    return True

                try:
                    cur.execute("""
                                UPDATE users 
                                SET points = points - ?, spent_points = spent_points + ? 
                                WHERE user_id = ?
                            """, (item['price'], item['price'], user['user_id']))

                    cur.execute("SELECT id FROM inventory WHERE user_id = ? AND item_id = ?",
                                (user['user_id'], item['item_id']))
                    inv_row = cur.fetchone()

                    if inv_row:
                        cur.execute("UPDATE inventory SET quantity = quantity + 1 WHERE id = ?", (inv_row['id'],))
                    else:
                        cur.execute("""
                                    INSERT INTO inventory (user_id, item_id, quantity, purchase_date) 
                                    VALUES (?, ?, 1, ?)
                                """, (user['user_id'], item['item_id'], now_time))

                    _write_shop_log(
                        cur, "구매",
                        user['user_id'], user['name'],
                        item['item_id'], item['item_name'], 1,
                        price=item['price'],
                        points_after=current_points - item['price'],
                        processed_by=user['user_id'],
                        log_date=now_time,
                    )

                    conn.commit()
                    chat.reply(
                        f"🛍️ 구매 완료: [{item['item_name']}]\n결제 금액: 🅟{item['price']:,}\n남은 포인트: 🅟{current_points - item['price']:,}")
                except Exception as e:
                    conn.rollback()
                    chat.reply("❌ 구매 처리 중 오류가 발생했습니다.")
                    print(f"Purchase Error: {e}")

                conn.close()
            return True

        if cmd == "/상점추가":
            if not is_admin(chat.sender.id):
                return False

            param = _command_param(chat)
            parts = param.split(maxsplit=2)

            if len(parts) < 3:
                chat.reply("⚠️ 형식: /상점추가 [이름] [가격] [설명]\n예: /상점추가 포션 500 체력을 회복합니다.")
                return True

            item_name = parts[0]
            try:
                item_price = int(parts[1])
            except ValueError:
                chat.reply("⚠️ 가격은 숫자로 입력해주세요.")
                return True
            item_desc = parts[2]

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                try:
                    cur.execute("""
                            INSERT INTO items (item_name, price, description) 
                            VALUES (?, ?, ?)
                        """, (item_name, item_price, item_desc))
                    conn.commit()
                    chat.reply(f"✅ 새 아이템이 등록되었습니다!\n📦 {item_name} (🅟{item_price:,})\n📝 {item_desc}")
                except sqlite3.IntegrityError:
                    chat.reply(f"❌ '{item_name}'은(는) 이미 존재하는 아이템 이름입니다.")
                except Exception as e:
                    chat.reply(f"❌ 등록 중 오류 발생: {e}")
                finally:
                    conn.close()
            return True

        if cmd == "/상점삭제":
            if not is_admin(chat.sender.id):
                return False

            item_name = _command_param(chat)

            if not item_name:
                chat.reply("⚠️ 삭제할 아이템 이름을 입력해주세요.\n예: /상점삭제 경험치부스터")
                return True

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute("SELECT item_id FROM items WHERE item_name = ?", (item_name,))
                item = cur.fetchone()

                if not item:
                    chat.reply(f"❓ '{item_name}'은(는) 상점에 등록되지 않은 아이템입니다.")
                else:
                    try:
                        cur.execute("DELETE FROM items WHERE item_name = ?", (item_name,))
                        conn.commit()
                        chat.reply(f"🗑️ 아이템 '{item_name}'이(가) 상점에서 영구 삭제되었습니다.")
                    except Exception as e:
                        chat.reply(f"❌ 삭제 중 오류 발생: {e}")

                conn.close()
            return True

        if cmd == "/포인트정보":
            if not is_admin(chat.sender.id):
                return False

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                cur.execute(f"""
                            SELECT user_id, name, points
                            FROM users
                            WHERE {TAGGED_USER_SQL_CONDITION}
                            ORDER BY points DESC
                        """)
                all_users = cur.fetchall()

                cur.execute("""
                            SELECT inv.user_id, i.item_name, inv.quantity 
                            FROM inventory inv 
                            JOIN items i ON inv.item_id = i.item_id 
                            WHERE inv.quantity > 0
                        """)
                all_inventory = cur.fetchall()
                conn.close()

            if not all_users:
                chat.reply("⚠️ 등록된 유저가 없습니다.")
                return True

            user_items_map = {}
            for inv in all_inventory:
                uid = inv['user_id']
                if uid not in user_items_map:
                    user_items_map[uid] = []
                user_items_map[uid].append(f"{inv['item_name']}({inv['quantity']})")

            info_msg = ["👑 [ 유저 포인트 & 아이템 현황 ]", "────────"]

            for u in all_users:
                uid = u['user_id']
                items_str = ", ".join(user_items_map.get(uid, ["없음"]))
                info_msg.append(f"👤 {u['name']} (🅟{u['points']:,})")
                info_msg.append(f"   ㄴ 📦 아이템: {items_str}")

            info_msg.append("────────")
            chat.reply("\n".join(info_msg))
            return True

        # ─────────────────────────────
        # 관리자 전용: 구매 아이템 사용 처리
        # /구매목록 으로 번호를 확인하고 /사용처리 [번호] [개수] 로 차감합니다.
        # ─────────────────────────────
        if cmd == "/구매목록":
            if not is_admin(chat.sender.id):
                return False

            rows = _fetch_owned_items()

            if not rows:
                chat.reply("📭 사용 처리할 보유 아이템이 없습니다.")
                return True

            msg_lines = ["📦 [ 구매 아이템 목록 ]", "────────"]
            for i, row in enumerate(rows, start=1):
                # 수량이 1이면 굳이 x1 을 붙이지 않습니다.
                qty_text = f" x{row['quantity']}" if row['quantity'] > 1 else ""
                msg_lines.append(f"{i}) {row['item_name']}{qty_text} - 👤 {row['user_name']}")

            msg_lines.append("────────")
            msg_lines.append("💡 사용 처리: /사용처리 [번호]")
            msg_lines.append("예시: /사용처리 1        (1개 처리)")
            msg_lines.append("      /사용처리 1 2      (2개 처리)")
            msg_lines.append("      /사용처리 1 전부   (전량 처리)")

            chat.reply("\n".join(msg_lines))
            return True

        if cmd == "/사용처리":
            if not is_admin(chat.sender.id):
                return False

            param = _command_param(chat)
            parts = param.split()

            if not parts or not parts[0].isdigit():
                chat.reply(
                    "⚠️ 사용 처리할 항목의 '번호'를 입력해주세요.\n"
                    "예: /사용처리 1\n"
                    "예: /사용처리 1 2   (2개 처리)\n"
                    "예: /사용처리 1 전부 (전량 처리)\n"
                    "💡 번호는 /구매목록 에서 확인하세요."
                )
                return True

            target_idx = int(parts[0])
            count_text = parts[1] if len(parts) >= 2 else "1"
            use_all = count_text in ("전부", "모두", "all", "ALL")

            if not use_all and not count_text.isdigit():
                chat.reply(
                    "⚠️ 개수는 숫자 또는 '전부' 로 입력해주세요.\n"
                    "예: /사용처리 1 2\n"
                    "예: /사용처리 1 전부"
                )
                return True

            rows = _fetch_owned_items()

            if target_idx < 1 or target_idx > len(rows):
                chat.reply(
                    f"⚠️ 잘못된 번호입니다. (1~{len(rows)} 사이 입력)\n"
                    f"/구매목록 을 다시 확인해주세요."
                )
                return True

            target = rows[target_idx - 1]
            # '전부' 는 목록에 찍힌 보유 수량 전체를 뜻하므로 target 확정 이후에 계산합니다.
            use_count = target['quantity'] if use_all else int(count_text)

            if use_count < 1:
                chat.reply("⚠️ 개수는 1 이상이어야 합니다.")
                return True

            if use_count > target['quantity']:
                chat.reply(
                    f"🚫 보유 수량보다 많이 처리할 수 없습니다.\n"
                    f"👤 {target['user_name']} / 📦 {target['item_name']}\n"
                    f"보유: {target['quantity']}개 / 요청: {use_count}개"
                )
                return True

            now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                try:
                    # quantity >= ? 조건으로 목록 조회 이후 수량이 바뀐 경우를 걸러냅니다.
                    cur.execute("""
                                UPDATE inventory
                                SET quantity = quantity - ?
                                WHERE id = ? AND quantity >= ?
                            """, (use_count, target['inv_id'], use_count))

                    if cur.rowcount == 0:
                        conn.rollback()
                        chat.reply(
                            "⚠️ 처리 도중 보유 수량이 변경되었습니다.\n"
                            "/구매목록 을 다시 확인해주세요."
                        )
                        conn.close()
                        return True

                    # 남은 수량이 0이면 인벤토리에서 행 자체를 제거합니다.
                    # 기록은 item_usage_logs 에 남으므로 /사용내역 으로 추적 가능합니다.
                    cur.execute("DELETE FROM inventory WHERE id = ? AND quantity <= 0",
                                (target['inv_id'],))

                    _write_shop_log(
                        cur, "사용",
                        target['user_id'], target['user_name'],
                        target['item_id'], target['item_name'], use_count,
                        processed_by=chat.sender.id,
                        log_date=now_time,
                    )

                    conn.commit()

                    remain = target['quantity'] - use_count
                    remain_text = f"📉 남은 수량: {remain}개" if remain > 0 else "🗑️ 목록에서 제거되었습니다."

                    chat.reply(
                        f"✅ 사용 처리 완료\n"
                        f"────────\n"
                        f"📦 {target['item_name']} x{use_count}\n"
                        f"👤 {target['user_name']}\n"
                        f"{remain_text}\n"
                        f"🕒 {now_time}"
                    )
                except Exception as e:
                    conn.rollback()
                    chat.reply("❌ 사용 처리 중 오류가 발생했습니다.")
                    print(f"Item Usage Error: {e}")
                finally:
                    conn.close()
            return True

        # ─────────────────────────────
        # 관리자 전용: 상점 활동 로그
        # /구매 와 /사용처리 가 남긴 기록을 한 곳에서 조회합니다.
        # /사용내역 은 사용 기록만 보는 단축 명령입니다.
        # ─────────────────────────────
        if cmd in ("/상점로그", "/사용내역"):
            if not is_admin(chat.sender.id):
                return False

            action_filter = "사용" if cmd == "/사용내역" else None
            limit = SHOP_LOG_DEFAULT_LIMIT

            for token in _command_param(chat).split():
                if token in SHOP_LOG_ACTIONS:
                    action_filter = token
                elif token.isdigit():
                    limit = max(1, min(int(token), SHOP_LOG_MAX_LIMIT))
                else:
                    chat.reply(
                        f"⚠️ 형식: {cmd} [구매|사용] [건수]\n"
                        f"예: {cmd}\n"
                        f"예: {cmd} 구매\n"
                        f"예: {cmd} 사용 30\n"
                        f"💡 건수는 최대 {SHOP_LOG_MAX_LIMIT}건까지입니다."
                    )
                    return True

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                if action_filter:
                    cur.execute("""
                                SELECT * FROM shop_logs
                                WHERE action = ?
                                ORDER BY id DESC
                                LIMIT ?
                            """, (action_filter, limit))
                else:
                    cur.execute("SELECT * FROM shop_logs ORDER BY id DESC LIMIT ?", (limit,))
                logs = cur.fetchall()

                cur.execute("""
                            SELECT action, COUNT(*) AS count, SUM(quantity) AS total
                            FROM shop_logs
                            GROUP BY action
                        """)
                summary = {row['action']: row for row in cur.fetchall()}
                conn.close()

            if not logs:
                target_text = f"'{action_filter}' " if action_filter else ""
                chat.reply(f"📭 {target_text}상점 로그가 없습니다.")
                return True

            title = f"🧾 [ 상점 로그 - {action_filter} ]" if action_filter else "🧾 [ 상점 로그 ]"
            msg_lines = [title, "────────"]
            msg_lines.extend(_format_shop_log_lines(logs))
            msg_lines.append("────────")

            buy = summary.get("구매")
            use = summary.get("사용")
            msg_lines.append(
                f"📊 누적 구매 {buy['count'] if buy else 0}건 / "
                f"사용 처리 {use['count'] if use else 0}건"
            )
            msg_lines.append(f"💡 최신 {len(logs)}건 표시 · {cmd} [구매|사용] [건수]")

            chat.reply("\n".join(msg_lines))
            return True

        if cmd == "/유저목록":
            if not is_admin(chat.sender.id):
                return False

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute(f"""
                            SELECT name, job, points
                            FROM users
                            WHERE {TAGGED_USER_SQL_CONDITION}
                            ORDER BY name ASC
                        """)
                users = cur.fetchall()
                conn.close()

            if not users:
                chat.reply("⚠️ 등록된 유저가 없습니다.")
                return True

            msg_lines = ["📋 [ 전체 유저 목록 ]", "────────"]
            for i, u in enumerate(users, start=1):
                msg_lines.append(f"{i}. 👤 {u['name']} [{u['job']}] - 🅟{u['points']:,}")

            msg_lines.append("────────")
            msg_lines.append("💡 삭제 방법: /유저삭제 [번호]")
            msg_lines.append("예시: /유저삭제 3")

            chat.reply("\n".join(msg_lines))
            return True

        # ─────────────────────────────
        # 관리자 전용: 유저 삭제 (목록 번호 기준 + YES/NO 대기열 등록)
        # ─────────────────────────────
        if cmd == "/유저삭제":
            if not is_admin(chat.sender.id):
                return False

            param = _command_param(chat)

            if not param.isdigit():
                chat.reply("⚠️ 삭제할 유저의 '번호'를 입력해주세요.\n예: /유저삭제 3")
                return True

            target_idx = int(param)

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute(f"""
                            SELECT user_id, name
                            FROM users
                            WHERE {TAGGED_USER_SQL_CONDITION}
                            ORDER BY name ASC
                        """)
                users = cur.fetchall()
                conn.close()

            if target_idx < 1 or target_idx > len(users):
                chat.reply(f"⚠️ 잘못된 번호입니다. (1~{len(users)} 사이 입력)\n/유저목록 을 다시 확인해주세요.")
                return True

            target_user = users[target_idx - 1]

            # 대기열에 저장
            pending_deletions[chat.sender.id] = {
                "target_uid": target_user['user_id'],
                "target_name": target_user['name']
            }

            chat.reply(
                f"⚠️ 정말로 [{target_idx}번] '{target_user['name']}' 유저의 모든 데이터를 삭제하시겠습니까?\n\n"
                f"동의하시면 `/유저삭제동의 YES` 를, 취소하시려면 `/유저삭제동의 NO` 를 입력해주세요."
            )
            return True

    except Exception as e:
        print(f"Error: {e}")
    return False
