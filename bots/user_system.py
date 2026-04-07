import sqlite3
import random
import threading
import time
from datetime import datetime, date, timedelta
import pytz
from iris import ChatContext
import re
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# 환경변수에서 ADMIN_IDS를 가져와 리스트로 변환
admin_raw = os.getenv("ADMIN_IDS", "")
# 공백 제거 후 정수형(int) 리스트로 생성
ADMIN_LIST = [int(aid.strip()) for aid in admin_raw.split(",") if aid.strip()]
# ─────────────────────────────
# 설정 및 DB 연결
# ─────────────────────────────
DB_FILE = "iris.db"
DB_LOCK = threading.RLock()
KST = pytz.timezone('Asia/Seoul')


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


        cur.execute("PRAGMA table_info(lotto)")
        if 'room_id' not in [c[1] for c in cur.fetchall()]:
            cur.execute("ALTER TABLE lotto ADD COLUMN room_id TEXT")

        conn.commit()
        conn.close()


init_db()


# ─────────────────────────────
# 유틸리티
# ─────────────────────────────


def _get_or_create_user(chat: ChatContext):
    uid = chat.sender.id
    current_name = str(chat.sender.name or f"User{uid}").strip()
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

            chat.reply(f"📝 닉네임 변경 감지\n[{old_name}] ➜ [{current_name}]")
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

        # 채팅 카운트 업데이트
        new_cnt = 1 if user['last_chat_date'] != today else user['today_chat'] + 1
        cur.execute("UPDATE users SET total_chat=total_chat+1, today_chat=?, last_chat_date=? WHERE user_id=?",
                    (new_cnt, today, uid))
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
# 스케줄러 & 확률 추첨 (확률 비공개)
# ─────────────────────────────

def start_lotto_scheduler(bot):
    def run():
        while True:
            now = datetime.now(KST)

            # ✅ 테스트용: 1분 뒤 실행 (테스트 끝나면 주석 처리)
            # target = now + timedelta(minutes=1)

            # [운영용] 매일 오전 7시
            target = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            wait_sec = (target - now).total_seconds()
            print(f"[시스템] 다음 추첨({target.strftime('%H:%M:%S')})까지 {wait_sec:.1f}초 대기...")

            time.sleep(wait_sec)

            execute_probability_draw(bot)
            time.sleep(5)

    threading.Thread(target=run, daemon=True).start()


def execute_probability_draw(bot):
    today_str = datetime.now(KST).date().isoformat()

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("SELECT DISTINCT room_id FROM lotto WHERE is_drawn=0")
        rooms = [r['room_id'] for r in cur.fetchall() if r['room_id']]

        if not rooms:

            conn.close()
            return



        for rid in rooms:
            # 해당 방의 티켓 정보 가져오기
            cur.execute("""
                SELECT l.user_id, l.numbers, u.name 
                FROM lotto l 
                JOIN users u ON l.user_id = u.user_id 
                WHERE l.room_id=? AND l.is_drawn=0
            """, (rid,))

            tickets = cur.fetchall()
            taken_numbers = set([t['numbers'] for t in tickets])
            winning_number = None

            # 1. 1등 당첨자 선정 (1% 확률)
            for t in tickets:
                if random.randint(1, 100) == 1:
                    winning_number = t['numbers']
                    break

            # 2. 당첨자가 없을 경우 중복되지 않는 꽝 번호 생성
            if winning_number is None:
                for _ in range(1000):
                    temp_num = f"{random.randint(0, 999):03d}"
                    if temp_num not in taken_numbers:
                        winning_number = temp_num
                        break
                if winning_number is None:
                    winning_number = f"{random.randint(0, 999):03d}"

            # 3. 채점 및 포인트 지급
            w1_list = []
            w2_list = []

            for t in tickets:
                u_num = t['numbers']
                match_cnt = 0
                for i in range(3):
                    if u_num[i] == winning_number[i]:
                        match_cnt += 1

                if match_cnt == 3:
                    # 1등 (300P)
                    w1_list.append(t['name'])
                    cur.execute("UPDATE users SET points=points+300 WHERE user_id=?", (t['user_id'],))
                elif match_cnt == 2:
                    # 2등 (150P로 수정)
                    w2_list.append(t['name'])
                    cur.execute("UPDATE users SET points=points+150 WHERE user_id=?", (t['user_id'],))

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
                msg_lines.append("1등 당첨자 : 🅟300")
                msg_lines.append("2등 당첨자 : 🅟150")
            else:
                msg_lines.append(f"행운의 복권 {len(tickets)}명 추첨 결과")
                msg_lines.append("────────")
                msg_lines.append("'푸헤헤헤. 다음 기회에' 로 ")

            # 최종 메시지 전송
            safe_send_message(bot, rid, "\n".join(msg_lines))

        # 정산 완료 처리
        cur.execute("UPDATE lotto SET is_drawn=1 WHERE is_drawn=0")
        conn.commit()
        conn.close()



# ─────────────────────────────
# 명령어 핸들러
# ─────────────────────────────

def handle_user_commands(chat: ChatContext):
    try:
        user = _get_or_create_user(chat)
        cmd = getattr(chat.message, "command", "")

        if cmd == "ㅊㅊ" or cmd in ["/ㅊㅊ", "!ㅊㅊ"]:
            today_str = datetime.now(KST).date().isoformat()

            if user['last_checkin_date'] == today_str:
                # ✅ 이미 출석한 경우에도 현재 기록을 보여줌
                chat.reply(
                    f"⚠️ 이미 출석했습니다.\n"
                    f"📅 총 출석: {user['total_checkin']}일\n"
                    f"🔥 연속 출석: {user['consecutive_checkin']}일"
                )
                return True

            # --- 출석하지 않은 경우 (신규 출석 로직) ---
            now = datetime.now(KST)
            today = now.date()
            yesterday_str = (today - timedelta(days=1)).isoformat()

            # 연속 출석 계산
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
                        points = points + 10 
                    WHERE user_id = ?
                    """,
                    (new_total, new_consecutive, today_str, user['user_id']))
                conn.commit()
                conn.close()

            chat.reply(
                f"✅ 출석 완료! (🅟10)\n"
                f"📅 총 출석: {new_total}일\n"
                f"🔥 연속 출석: {new_consecutive}일째"
            )
            return True

        if cmd == "/내정보":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 1. 최근 닉네임 변경 로그 가져오기
                cur.execute("SELECT old_name, new_name FROM name_logs WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                            (user['user_id'],))
                last_log = cur.fetchone()

                # 2. 보유 아이템(인벤토리) 정보 가져오기
                cur.execute("""
                            SELECT i.item_name, inv.quantity 
                            FROM inventory inv 
                            JOIN items i ON inv.item_id = i.item_id 
                            WHERE inv.user_id = ? AND inv.quantity > 0
                        """, (user['user_id'],))
                my_items = cur.fetchall()

                conn.close()

            # 닉네임 로그 텍스트 구성
            log_text = ""
            if last_log:
                log_text = f"\n•닉네임 변경: {last_log['old_name']}\n➜ {last_log['new_name']}"

            # 인벤토리 텍스트 구성
            if not my_items:
                inv_text = "보유 아이템이 없습니다."
            else:
                inv_text = ", ".join([f"{item['item_name']}({item['quantity']})" for item in my_items])

            # 전체 메시지 구성
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

        # ─────────────────────────────
        # 채팅 순위표 출력 (상위 10명)
        # ─────────────────────────────
        if cmd == "/채팅순위":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 1. 전체 유저의 채팅 총합 계산 (점유율 계산용)
                cur.execute("SELECT SUM(total_chat) FROM users")
                total_sum_row = cur.fetchone()
                total_sum = total_sum_row[0] if total_sum_row and total_sum_row[0] > 0 else 1

                # 2. total_chat 기준 내림차순 정렬, 상위 15명 추출
                cur.execute("""
                                SELECT name, total_chat, job 
                                FROM users 
                                ORDER BY total_chat DESC 
                                LIMIT 15
                            """)
                rows = cur.fetchall()
                conn.close()

            if not rows:
                chat.reply("데이터가 충분하지 않습니다.")
                return True

            rank_msg = ["🏆 [ 전체 채팅 순위 TOP 15 ]", "────────"]

            # 메달 이모지 리스트
            medals = ["🥇", "🥈", "🥉"] + ["✨"] * 12

            for i, row in enumerate(rows):
                rank = i + 1
                medal = medals[i]

                # 점유율 계산 (개인 채팅 / 전체 채팅 * 100)
                share = (row['total_chat'] / total_sum) * 100

                # 출력 형식: 🥇 1위: 이름 [직업] (점유율%)
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
                    # ✅ 수정: 이미 보유한 번호를 보여주도록 변경
                    chat.reply(f"🎫 이미 추첨 대기 중인 복권이 있습니다.\n번호: [{row['numbers']}]\n(매일 오전 7시 당첨 결과를 공개!)")
                else:
                    new_nums = f"{random.randint(0, 999):03d}"
                    cur.execute(
                        "INSERT INTO lotto (user_id, lotto_date, numbers, room_id, is_drawn) VALUES (?, ?, ?, ?, 0)",
                        (user['user_id'], today, new_nums, room_id))
                    conn.commit()
                    chat.reply(f"🎲 복권 발행 완료: [{new_nums}]\n(행운을 빕니다!)")
                conn.close()
            return True

        if cmd == "/복권정보":
            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as cnt FROM lotto WHERE is_drawn=0")
                wait_cnt = cur.fetchone()['cnt']
                conn.close()
            # ✅ 수정: 확률 언급 제거
            chat.reply(
                f"**복권 시스템 정보**\n\n"
                f"1등 상금: 300P\n"
                f"2등 상금: 150P\n\n"
                f"현재 {wait_cnt}명이 참여 중입니다."
            )
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

            # 2. 아이템 구매
        if cmd == "/구매":
            # iris 라이브러리의 param 속성은 명령어 뒤의 텍스트만 담고 있습니다.
            target_item = getattr(chat.message, "param", "").strip()

            if not target_item:
                chat.reply("⚠️ 구매하실 아이템 이름을 입력해주세요.\n예: /구매 확성기")
                return True

            # target_item이 바로 "확성기"가 됩니다.
            now_time = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 아이템 정보 확인
                cur.execute("SELECT * FROM items WHERE item_name = ?", (target_item,))
                item = cur.fetchone()

                if not item:
                    chat.reply(f"❓ '{target_item}'은(는) 상점에 없는 아이템입니다.")
                    conn.close()
                    return True

                # 최신 포인트 정보 실시간 확인
                cur.execute("SELECT points FROM users WHERE user_id = ?", (user['user_id'],))
                current_points = cur.fetchone()['points']

                if current_points < item['price']:
                    chat.reply(f"🚫 포인트가 부족합니다.\n보유: 🅟{current_points:,} / 필요: 🅟{item['price']:,}")
                    conn.close()
                    return True

                # 결제 및 인벤토리 추가
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

                    conn.commit()
                    chat.reply(
                        f"🛍️ 구매 완료: [{item['item_name']}]\n결제 금액: 🅟{item['price']:,}\n남은 포인트: 🅟{current_points - item['price']:,}")
                except Exception as e:
                    conn.rollback()
                    chat.reply("❌ 구매 처리 중 오류가 발생했습니다.")
                    print(f"Purchase Error: {e}")

                conn.close()

            return True

        # ─────────────────────────────
        # 관리자 전용: 상점 아이템 추가
        # ─────────────────────────────
        if cmd == "/상점추가":
            if chat.sender.id not in ADMIN_LIST:
                print("관리자가 아닙니다.",chat.sender.id)
                return False

                # 형식: /상점추가 [아이템명] [가격] [설명]
            param = getattr(chat.message, "param", "").strip()
            parts = param.split(maxsplit=2)  # 이름, 가격, 설명으로 분리

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

        # ─────────────────────────────
        # 관리자 전용: 상점 아이템 삭제
        # ─────────────────────────────
        if cmd == "/상점삭제":
            if chat.sender.id not in ADMIN_LIST:
                return False

                # 형식: /상점삭제 [아이템명]
            item_name = getattr(chat.message, "param", "").strip()

            if not item_name:
                chat.reply("⚠️ 삭제할 아이템 이름을 입력해주세요.\n예: /상점삭제 경험치부스터")
                return True

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 먼저 해당 아이템이 존재하는지 확인
                cur.execute("SELECT item_id FROM items WHERE item_name = ?", (item_name,))
                item = cur.fetchone()

                if not item:
                    chat.reply(f"❓ '{item_name}'은(는) 상점에 등록되지 않은 아이템입니다.")
                else:
                    try:
                        # 1. 상점에서 삭제
                        cur.execute("DELETE FROM items WHERE item_name = ?", (item_name,))

                        # 2. (선택사항) 인벤토리에서도 모두 회수하고 싶다면 아래 주석 해제
                        # cur.execute("DELETE FROM inventory WHERE item_id = ?", (item['item_id'],))

                        conn.commit()
                        chat.reply(f"🗑️ 아이템 '{item_name}'이(가) 상점에서 영구 삭제되었습니다.")
                    except Exception as e:
                        chat.reply(f"❌ 삭제 중 오류 발생: {e}")

                conn.close()
            return True
        # ─────────────────────────────
        # 관리자 전용: 전체 유저 포인트 및 아이템 정보 조회
        # ─────────────────────────────
        if cmd == "/포인트정보":
            # 관리자 권한 체크
            if chat.sender.id not in ADMIN_LIST:
                return False

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 1. 전체 유저 정보 가져오기 (포인트가 많은 순으로 정렬)
                cur.execute("SELECT user_id, name, points FROM users ORDER BY points DESC")
                all_users = cur.fetchall()

                # 2. 전체 인벤토리 정보 가져오기
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

            # 3. 인벤토리 데이터를 user_id를 키값으로 딕셔너리에 묶기
            user_items_map = {}
            for inv in all_inventory:
                uid = inv['user_id']
                if uid not in user_items_map:
                    user_items_map[uid] = []
                user_items_map[uid].append(f"{inv['item_name']}({inv['quantity']})")

            # 4. 출력 메시지 구성
            info_msg = ["👑 [ 유저 포인트 & 아이템 현황 ]", "────────"]

            for u in all_users:
                uid = u['user_id']
                # 해당 유저의 아이템 리스트 가져오기 (없으면 '없음' 처리)
                items_str = ", ".join(user_items_map.get(uid, ["없음"]))

                info_msg.append(f"👤 {u['name']} (🅟{u['points']:,})")
                info_msg.append(f"   ㄴ 📦 아이템: {items_str}")

            info_msg.append("────────")

            # 메시지가 너무 길 경우를 대비해 전송 (카카오톡 등 플랫폼 제한 주의)
            chat.reply("\n".join(info_msg))
            return True
        # ─────────────────────────────
        # 관리자 전용: 유저 목록 조회
        # ─────────────────────────────
        if cmd == "/유저목록":
            if chat.sender.id not in ADMIN_LIST:
                return False

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()
                # 유저 이름순으로 정렬하여 보기 편하게 출력
                cur.execute("SELECT name, job, points FROM users ORDER BY name ASC")
                users = cur.fetchall()
                conn.close()

            if not users:
                chat.reply("⚠️ 등록된 유저가 없습니다.")
                return True

            msg_lines = ["📋 [ 전체 유저 목록 ]", "────────"]
            for u in users:
                msg_lines.append(f"👤 {u['name']} [{u['job']}] - 🅟{u['points']:,}")
            msg_lines.append("────────")
            msg_lines.append("💡 삭제 방법: /유저삭제 [유저명]")

            chat.reply("\n".join(msg_lines))
            return True

        # ─────────────────────────────
        # 관리자 전용: 유저 삭제 (DB 데이터 일괄 삭제)
        # ─────────────────────────────
        if cmd == "/유저삭제":
            if chat.sender.id not in ADMIN_LIST:
                return False

            target_name = getattr(chat.message, "param", "").strip()

            if not target_name:
                chat.reply("⚠️ 삭제할 유저명을 입력해주세요.\n예: /유저삭제 홍길동")
                return True

            with DB_LOCK:
                conn = get_db_conn()
                cur = conn.cursor()

                # 1. 대상 유저 존재 여부 확인
                cur.execute("SELECT user_id FROM users WHERE name = ?", (target_name,))
                target_user = cur.fetchone()

                if not target_user:
                    chat.reply(f"❓ '{target_name}' 유저를 찾을 수 없습니다.")
                    conn.close()
                    return True

                uid = target_user['user_id']

                # 2. 연관된 모든 테이블에서 데이터 일괄 삭제 (트랜잭션 처리)
                try:
                    cur.execute("DELETE FROM inventory WHERE user_id = ?", (uid,))
                    cur.execute("DELETE FROM lotto WHERE user_id = ?", (uid,))
                    cur.execute("DELETE FROM name_logs WHERE user_id = ?", (uid,))
                    cur.execute("DELETE FROM users WHERE user_id = ?", (uid,))
                    conn.commit()

                    chat.reply(f"🗑️ '{target_name}' 유저와 관련된 모든 데이터가 영구 삭제되었습니다.")
                except Exception as e:
                    conn.rollback()
                    chat.reply(f"❌ 유저 삭제 중 오류 발생: {e}")
                finally:
                    conn.close()

            return True


    except Exception as e:
        print(f"Error: {e}")
    return False

