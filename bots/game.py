from __future__ import annotations
import threading
import time
import random
from typing import Dict, Any, Optional
from iris import ChatContext

from bots.user_system import get_db_conn, DB_LOCK

# ─────────────────────────────
# 게임 포인트 지급 설정 (테스트 중에는 False, 나중에 True로 변경)
# ─────────────────────────────
ENABLE_GAME_REWARD = False

# ─────────────────────────────
# 통합 게임 상태 관리
# ─────────────────────────────
GAME_STATE: Dict[int, Dict[str, Any]] = {}
GAME_LOCK = threading.RLock()

# 게임 코드 -> 화면에 보일 이름. 여러 곳에서 쓰므로 모듈 상수로 둡니다.
GAME_NAMES_KR = {
    "REACTION": "반응 속도",
    "369": "369",
    "CHOSUNG": "자음 퀴즈",
}


def _reaction_timeout(chat: ChatContext, room_id: int, expected_idx: int):
    """5초 동안 응답이 없을 경우 패배 처리하고 다음 턴으로 넘기는 함수"""
    state = _get_game_state(room_id)
    with GAME_LOCK:
        # 게임이 취소되었거나 끝난 경우 중단
        if state["current_game"] != "REACTION" or state.get("data", {}).get("status") != "RUNNING":
            return

        data = state["data"]
        # 5초가 지났는데도 여전히 같은 차례(expected_idx)라면 응답을 안 한 것
        if data["current_idx"] == expected_idx:
            current_player = data["members"][expected_idx]

            # 패배 처리 (99.99초로 기록하여 꼴찌로 만듦)
            data["results"].append({
                "id": current_player["id"],
                "name": current_player["name"],
                "time": 99.99
            })

            chat.reply(f"⏰ 5초 초과! {current_player['name']}님 응답 없음 (탈락)\n다음 사람으로 넘어갑니다.")

            # 다음 사람으로 턴 넘기기
            data["current_idx"] += 1
            _reaction_next_turn(chat, state)

def _get_game_state(room_id: int) -> Dict[str, Any]:
    with GAME_LOCK:
        if room_id not in GAME_STATE:
            GAME_STATE[room_id] = {
                "current_game": None,  # "REACTION", "369", None
                "data": {}  # 각 게임별 세부 데이터 저장
            }
        return GAME_STATE[room_id]


def _get_user_name(sender) -> str:
    name = getattr(sender, "name", None) or getattr(sender, "nickname", None) or getattr(sender, "nick", None)
    return str(name) if name else f"User{getattr(sender, 'id', '?')}"


def _extract_text(chat: ChatContext) -> str:
    """모든 환경에서 안전하게 텍스트 추출"""
    msg = chat.message
    if isinstance(msg, str):
        return msg.strip()

    # 텍스트, 내용, 혹은 명령어로 파싱된 값까지 모두 긁어옵니다.
    text = getattr(msg, "text", "") or getattr(msg, "content", "") or getattr(msg, "command", "")
    return str(text).strip()


# ─────────────────────────────
# [1] 반응 속도 게임 로직
# ─────────────────────────────
def handle_reaction_command(chat: ChatContext):
    room_id = chat.room.id
    state = _get_game_state(room_id)
    cmd = chat.message.command

    with GAME_LOCK:
        if cmd == "/반응참가":
            user_id = chat.sender.id
            user_name = _get_user_name(chat.sender)

            # 1. 게임이 아예 없는 경우 -> 방 생성 및 자동 참여
            if not state["current_game"]:
                state["current_game"] = "REACTION"
                state["data"] = {
                    "status": "WAITING",
                    "members": [{"id": user_id, "name": user_name}],
                    "current_idx": 0,
                    "results": [],
                    "creator_id": str(user_id)  # 만든 사람 ID 저장
                }

                member_names = ", ".join([m["name"] for m in state["data"]["members"]])
                chat.reply(
                    f"🎮 [반응 속도 게임] 방이 생성되었습니다!\n"
                    f"✅ {user_name}님 참여 완료\n\n"
                    f"👥 현재 대기 인원 ({len(state['data']['members'])}명): {member_names}\n\n"
                    f"👉 참여: /반응참가\n"
                    f"👉 시작: /반응시작 (2명 이상)\n"
                    f"👉 취소: /게임삭제"
                )
                return

            # 2. 반응 게임 모집 중인 경우 -> 추가 참여
            if state["current_game"] == "REACTION" and state["data"]["status"] == "WAITING":
                # 이미 참여한 유저인지 확인
                if any(m["id"] == user_id for m in state["data"]["members"]):
                    member_names = ", ".join([m["name"] for m in state["data"]["members"]])
                    chat.reply(f"⚠️ 이미 참여하셨습니다.\n👥 현재 대기 인원: {member_names}")
                    return

                # 새 멤버 추가
                state["data"]["members"].append({"id": user_id, "name": user_name})
                member_names = ", ".join([m["name"] for m in state["data"]["members"]])

                chat.reply(
                    f"✅ {user_name}님 참여!\n"
                    f"👥 현재 대기 인원 ({len(state['data']['members'])}명): {member_names}"
                )
                return

            # 3. 이미 게임이 진행 중이거나 다른 게임이 켜진 경우
            if state["current_game"]:
                game_names_kr = {"REACTION": "반응 속도", "369": "369"}
                display_name = game_names_kr.get(state["current_game"], state["current_game"])
                chat.reply(f"⚠️ 이미 [{display_name}] 게임이 진행/모집 중입니다.")
                return

        elif cmd == "/반응시작":
            if state["current_game"] != "REACTION" or state["data"]["status"] != "WAITING":
                return

            if len(state["data"]["members"]) < 2:
                chat.reply("❌ 최소 2명 이상 참여해야 시작할 수 있습니다.")
                return

            state["data"]["status"] = "RUNNING"

            # [추가된 부분] 게임 시작 직전에 멤버 순서를 무작위로 섞습니다.
            random.shuffle(state["data"]["members"])

            chat.reply("🚀 게임 시작! (순서는 랜덤으로 진행됩니다)\n집중하세요!")
            _reaction_next_turn(chat, state)


def _reaction_next_turn(chat: ChatContext, state: Dict[str, Any]):
    data = state["data"]
    if data["current_idx"] >= len(data["members"]):
        _finish_reaction(chat, state)
        return

    current_idx = data["current_idx"]
    current_name = data["members"][current_idx]["name"]

    # 1. 턴 안내 메시지 전송
    chat.reply(f"👉 {current_idx + 1}. {current_name}님 준비...!")

    # 2. 1~2초 사이의 랜덤한 지연 시간 설정
    delay = random.uniform(2.0, 3.0)

    # 3. 실제 숫자 출제 함수를 별도로 정의하여 Timer로 실행
    def display_target():
        with GAME_LOCK:
            # 게임이 도중에 취소되었는지 확인 (방어 코드)
            if state["current_game"] != "REACTION" or data["status"] != "RUNNING":
                return

            target_num = random.randint(10, 99)
            state["data"]["target_num"] = target_num
            state["data"]["start_time"] = time.time()

            # ★ [추가] 현재 누구의 차례인지 인덱스 저장
            expected_idx = state["data"]["current_idx"]

            confusing_formats = [
                f"🚨 [{target_num}] 🚨",
                f"🔥 {target_num} 🔥 빨리!!",
                f"👀 정답은 바로... [{target_num}]",
                f"⚡ 삐빅! {target_num} ⚡",
                f"🎯 과연 숫자는? >> {target_num} <<",
                f"⚠️ [주의] {target_num} 입력!",
                f"✨ {target_num} ✨",
                f"🤔 ...{target_num}...",
                f"💢 입력ㄱㄱ: {target_num}",
                f"🎲 뽑힌 숫자: {target_num}"
            ]

            chosen_msg = random.choice(confusing_formats)
            chat.reply(chosen_msg)

            # ★ [추가] 문제 출제 후 5초 타임아웃 타이머 시작
            threading.Timer(5.0, _reaction_timeout, args=[chat, chat.room.id, expected_idx]).start()

    # 비동기 타이머 시작 (메인 스레드를 차단하지 않음)
    threading.Timer(delay, display_target).start()


def _finish_reaction(chat: ChatContext, state: Dict[str, Any]):
    res = sorted(state["data"]["results"], key=lambda x: x["time"])
    msg = "🏆 [결과]\n" + "\n".join([f"{i + 1}. {r['name']} ({r['time']:.4f}초)" for i, r in enumerate(res)])

    # 1등 포인트 지급 로직
    if res:
        winner = res[0]  # 시간이 가장 짧은 1등
        if ENABLE_GAME_REWARD:
            try:
                # DB_LOCK과 get_db_conn()은 기존 DB 코드에 정의된 것을 사용
                with DB_LOCK:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    cur.execute("UPDATE users SET points = points + 10 WHERE user_id = ?", (winner["id"],))
                    conn.commit()
                    conn.close()
                msg += f"\n\n🎉 {winner['name']}님 1등! 10포인트가 지급되었습니다. (🅟+10)"
            except Exception as e:
                print(f"포인트 지급 오류: {e}")
                msg += f"\n\n⚠️ 포인트 지급 중 오류가 발생했습니다."
        else:
            msg += "\n\n💡 (현재는 테스트 기간이라 포인트가 지급되지 않습니다.)"

    chat.reply(msg)
    state["current_game"] = None  # 게임 종료


# ─────────────────────────────
# [2] 369 게임 로직
# ─────────────────────────────
def handle_369_command(chat: ChatContext):
    room_id = chat.room.id
    state = _get_game_state(room_id)
    cmd = getattr(chat.message, "command", "")

    with GAME_LOCK:
        if cmd == "/369시작":
            if state["current_game"]:
                game_names_kr = {"REACTION": "반응 속도", "369": "369"}
                display_name = game_names_kr.get(state["current_game"], state["current_game"])
                chat.reply(f"⚠️ 이미 [{display_name}] 게임이 진행 중입니다.")
                return
            state["current_game"] = "369"
            state["data"] = {"current": 1, "creator_id": str(chat.sender.id)}
            chat.reply("🎉 369 시작! 봇부터 시작할게 👉 [봇] 1\n취소: /게임삭제")
            return True
        elif cmd == "/369끝":
            state["current_game"] = None
            chat.reply("🛑 369 종료")
            return True
    return False


# ─────────────────────────────
# [공통] 게임삭제 (취소)
# ─────────────────────────────
def handle_game_cancel(chat: ChatContext):
    """게임을 만든 사람만 게임을 강제 종료하는 기능"""
    room_id = chat.room.id
    state = _get_game_state(room_id)

    with GAME_LOCK:
        if not state["current_game"]:
            chat.reply("⚠️ 현재 진행 중이거나 모집 중인 게임이 없습니다.")
            return True

        creator_id = state["data"].get("creator_id")
        sender_id = str(chat.sender.id)

        # 만든 사람인지 확인 (만약 봇 관리자도 지울 수 있게 하려면 or sender_id in ADMIN_LIST 추가 가능)
        if creator_id and sender_id != creator_id:
            chat.reply("❌ 게임을 시작한 사람만 삭제(취소)할 수 있습니다.")
            return True

        raw_game_name = state["current_game"]
        display_name = GAME_NAMES_KR.get(raw_game_name, raw_game_name)

        if raw_game_name == "CHOSUNG":
            _chosung_cancel_timer(state["data"])

        # 상태 초기화
        state["current_game"] = None
        state["data"] = {}

        chat.reply(f"🗑️ [{display_name}] 게임이 주최자에 의해 취소되었습니다.")
        return True


# ─────────────────────────────
# [공통] 일반 텍스트(숫자/짝) 입력 처리
# ─────────────────────────────
def handle_game_input(chat: ChatContext):
    room_id = chat.room.id
    state = _get_game_state(room_id)
    if not state["current_game"]: return

    text = _extract_text(chat)

    with GAME_LOCK:
        # 1. 반응게임 처리
        if state["current_game"] == "REACTION" and state["data"]["status"] == "RUNNING":
            data = state["data"]
            target_str = str(data.get("target_num", ""))

            if text == target_str or text == f"/{target_str}":
                current_player_id = str(data["members"][data["current_idx"]]["id"])
                sender_id = str(chat.sender.id)

                # 자기 차례가 맞는지 확인
                if sender_id == current_player_id:
                    elapsed = time.time() - data["start_time"]

                    # 결과를 저장할 때 포인트 지급을 위해 'id' 정보도 함께 저장
                    data["results"].append({
                        "id": data["members"][data["current_idx"]]["id"],
                        "name": data["members"][data["current_idx"]]["name"],
                        "time": elapsed
                    })

                    chat.reply(f"✅ 정답! 반응 시간: [{elapsed:.4f}초]")

                    data["current_idx"] += 1
                    _reaction_next_turn(chat, state)
                else:
                    chat.reply(f"❌ 지금은 {data['members'][data['current_idx']]['name']}님의 차례입니다!")
            return  # 반응게임 중일 땐 여기서 종료

        # 2. 자음 퀴즈 처리
        elif state["current_game"] == "CHOSUNG":
            data = state["data"]
            if not data.get("answer"):
                return

            # 오답에는 반응하지 않습니다. 일반 대화가 전부 오답 처리되면 방이 시끄러워집니다.
            if _normalize_answer(text) != _normalize_answer(data["answer"]):
                return

            uid = str(chat.sender.id)
            name = _get_user_name(chat.sender)
            score = data["scores"].setdefault(uid, {"id": chat.sender.id, "name": name, "count": 0})
            score["name"] = name
            score["count"] += 1
            _chosung_cancel_timer(data)
            data["miss_streak"] = 0

            _chosung_next_question(
                chat, state,
                prefix=f"정답! [{data['answer']}]\n{name}님 {score['count']}개째",
            )
            return

        # 3. 369 게임 처리
        elif state["current_game"] == "369":
            data = state["data"]
            expect_n = data["current"] + 1
            clap_cnt = sum(1 for ch in str(expect_n) if ch in "369")
            ans = "ㅉ" * clap_cnt if clap_cnt > 0 else str(expect_n)

            if text == ans:
                data["current"] = expect_n
                # 가끔 봇이 끼어들기
                if random.random() < 0.3:
                    data["current"] += 1
                    bot_n = data["current"]
                    b_clap = sum(1 for ch in str(bot_n) if ch in "369")
                    b_ans = "ㅉ" * b_clap if b_clap > 0 else str(bot_n)
                    chat.reply(f"[봇] {b_ans}")
            else:
                # 오답 처리 시 숫자가 입력되거나 'ㅉ'이 포함되었을 때만 처리 (일반 대화 방해 방지)
                if text.isdigit() or "ㅉ" in text:
                    chat.reply(f"❌ 틀렸어! {expect_n} 차례였고 정답은 '{ans}'")
                    state["current_game"] = None

# ─────────────────────────────
# [3] 자음(초성) 퀴즈 로직
# ─────────────────────────────
CHOSUNG_TABLE = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
CHOSUNG_HANGUL_START = 0xAC00
CHOSUNG_HANGUL_END = 0xD7A3
CHOSUNG_REWARD_POINT = 10
CHOSUNG_TIME_LIMIT = 60.0        # 문제당 제한시간(초)
CHOSUNG_MAX_MISS_STREAK = 2      # 연속 시간초과 허용 횟수. 넘으면 자동 종료

# 카테고리를 함께 알려줘야 초성만으로 좁혀지지 않는 문제를 풀 수 있습니다.
CHOSUNG_WORDS: Dict[str, list] = {
    "음식": [
        "김치찌개", "된장찌개", "삼겹살", "떡볶이", "짜장면", "탕수육", "비빔밥",
        "순대국밥", "제육볶음", "돈가스", "칼국수", "물냉면", "감자탕", "닭갈비",
        "부대찌개", "양념치킨", "순두부찌개",
    ],
    "동물": [
        "코끼리", "기린", "호랑이", "다람쥐", "고슴도치", "펭귄", "카멜레온",
        "너구리", "청설모", "독수리", "두더지", "하이에나", "코뿔소", "원숭이",
        "미어캣", "판다",
    ],
    "사물": [
        "냉장고", "세탁기", "청소기", "선풍기", "에어컨", "전자레인지", "가습기",
        "충전기", "이어폰", "키보드", "책가방", "우산", "손톱깎이", "돋보기",
        "빨래건조대",
    ],
    "장소": [
        "도서관", "놀이공원", "지하철역", "박물관", "수영장", "영화관", "편의점",
        "우체국", "찜질방", "주차장", "미용실", "체육관", "공항", "전망대",
    ],
    "길드": [
        "칸쵸조밥", "칸쵸메롱", "칸쵸양아치",
    ],
    "마비노기": [
        "던바튼", "티르코네일", "심층구멍", "교역품", "엠블럼", "방어구", "물레방아",
        "룬각인", "밤의흔적", "창백한산", "여신강림", "행운의여신",
    ],
}


def _to_chosung(word: str) -> str:
    """한글 문자열에서 초성만 뽑아냅니다. 한글이 아닌 글자는 그대로 둡니다."""
    out = []
    for ch in word:
        code = ord(ch)
        if CHOSUNG_HANGUL_START <= code <= CHOSUNG_HANGUL_END:
            out.append(CHOSUNG_TABLE[(code - CHOSUNG_HANGUL_START) // 588])
        elif ch.strip():
            out.append(ch)
    return "".join(out)


def _normalize_answer(text: str) -> str:
    """띄어쓰기 차이로 오답 처리되지 않도록 공백을 모두 지우고 비교합니다."""
    return "".join(str(text or "").split())


def _chosung_pick_word(asked: list):
    """아직 안 나온 단어 중에서 하나 고릅니다. 다 소진되면 None."""
    pool = [
        (category, word)
        for category, words in CHOSUNG_WORDS.items()
        for word in words
        if word not in asked
    ]
    if not pool:
        return None
    return random.choice(pool)


def _chosung_cancel_timer(data: Dict[str, Any]):
    """걸려 있는 제한시간 타이머를 해제합니다. 없으면 아무 일도 하지 않습니다."""
    timer = data.get("timer")
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
        data["timer"] = None


def _chosung_timeout(chat: ChatContext, room_id: int, expected_no: int):
    """제한시간 안에 아무도 못 맞히면 정답을 공개하고 다음 문제로 넘깁니다."""
    state = _get_game_state(room_id)
    with GAME_LOCK:
        # 그 사이 게임이 끝났거나 다음 문제로 넘어갔으면 흘러간 타이머입니다.
        if state["current_game"] != "CHOSUNG":
            return
        data = state["data"]
        if data.get("question_no") != expected_no:
            return

        data["timer"] = None
        data["miss_streak"] = data.get("miss_streak", 0) + 1

        # 아무도 안 보고 있는 방에서 74문제를 혼자 풀어대지 않도록 멈춥니다.
        if data["miss_streak"] >= CHOSUNG_MAX_MISS_STREAK:
            chat.reply(
                f"⏰ 시간 초과! 정답은 [{data['answer']}] 였습니다.\n"
                f"{CHOSUNG_MAX_MISS_STREAK}문제 연속으로 정답이 없어 게임을 종료합니다."
            )
            _finish_chosung(chat, state)
            return

        _chosung_next_question(
            chat, state,
            prefix=f"⏰ 시간 초과! 정답은 [{data['answer']}] 였습니다.",
        )


def _chosung_next_question(chat: ChatContext, state: Dict[str, Any], prefix: str = ""):
    """다음 문제를 내고 상태를 갱신합니다. 낼 문제가 없으면 게임을 마칩니다."""
    data = state["data"]
    _chosung_cancel_timer(data)
    picked = _chosung_pick_word(data["asked"])

    if picked is None:
        chat.reply((prefix + "\n" if prefix else "") + "📚 준비된 문제를 모두 풀었습니다!")
        _finish_chosung(chat, state)
        return

    category, word = picked
    data["asked"].append(word)
    data["answer"] = word
    data["category"] = category
    data["chosung"] = _to_chosung(word)
    data["hint_used"] = False
    data["question_no"] += 1

    lines = []
    if prefix:
        lines.append(prefix)
        lines.append("")
    lines.append(f"🔤 [{data['question_no']}번 문제]")
    lines.append("────────")
    lines.append(f"📂 분류 : {category}")
    lines.append(f"❓ 초성 : {data['chosung']}")
    lines.append(f"📏 글자 : {len(word)}글자")
    lines.append("────────")
    lines.append("💡 채팅으로 바로 정답을 입력하세요")
    lines.append(f"⏱️ 제한시간 {int(CHOSUNG_TIME_LIMIT)}초")
    lines.append("힌트 /자음힌트 · 넘기기 /자음패스 · 종료 /자음끝")
    chat.reply("\n".join(lines))

    # 아무도 못 맞히면 방이 이 게임에 묶여버리므로 제한시간을 겁니다.
    timer = threading.Timer(
        CHOSUNG_TIME_LIMIT, _chosung_timeout,
        args=[chat, chat.room.id, data["question_no"]],
    )
    timer.daemon = True
    data["timer"] = timer
    timer.start()


def _finish_chosung(chat: ChatContext, state: Dict[str, Any]):
    """점수를 집계해 결과를 알리고 게임을 종료합니다."""
    data = state["data"]
    _chosung_cancel_timer(data)
    scores = sorted(data["scores"].values(), key=lambda s: -s["count"])

    lines = ["🏁 [ 자음 퀴즈 종료 ]", "────────"]
    if scores:
        medals = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(scores):
            mark = medals[i] if i < len(medals) else "▪️"
            lines.append(f"{mark} {s['name']} - {s['count']}개")
    else:
        lines.append("맞힌 사람이 없습니다.")
    lines.append("────────")
    lines.append(f"총 {data['question_no']}문제 출제")

    if scores:
        winner = scores[0]
        if ENABLE_GAME_REWARD:
            try:
                with DB_LOCK:
                    conn = get_db_conn()
                    cur = conn.cursor()
                    cur.execute("UPDATE users SET points = points + ? WHERE user_id = ?",
                                (CHOSUNG_REWARD_POINT, winner["id"]))
                    conn.commit()
                    conn.close()
                lines.append("")
                lines.append(f"🎉 {winner['name']}님 1등! {CHOSUNG_REWARD_POINT}포인트가 지급되었습니다. (🅟+{CHOSUNG_REWARD_POINT})")
            except Exception as e:
                print(f"포인트 지급 오류: {e}")
                lines.append("")
                lines.append("⚠️ 포인트 지급 중 오류가 발생했습니다.")
        else:
            lines.append("")
            lines.append("💡 (현재는 테스트 기간이라 포인트가 지급되지 않습니다.)")

    chat.reply("\n".join(lines))
    state["current_game"] = None
    state["data"] = {}


def handle_chosung_command(chat: ChatContext):
    room_id = chat.room.id
    state = _get_game_state(room_id)
    cmd = getattr(chat.message, "command", "")

    with GAME_LOCK:
        if cmd == "/자음시작":
            if state["current_game"] and state["current_game"] != "CHOSUNG":
                display_name = GAME_NAMES_KR.get(state["current_game"], state["current_game"])
                chat.reply(f"⚠️ 이미 [{display_name}] 게임이 진행/모집 중입니다.")
                return True

            if state["current_game"] == "CHOSUNG":
                chat.reply("⚠️ 이미 자음 퀴즈가 진행 중입니다.\n현재 문제는 /자음문제 로 다시 볼 수 있습니다.")
                return True

            state["current_game"] = "CHOSUNG"
            state["data"] = {
                "creator_id": str(chat.sender.id),
                "answer": "",
                "category": "",
                "chosung": "",
                "hint_used": False,
                "asked": [],
                "scores": {},
                "question_no": 0,
                "timer": None,
                "miss_streak": 0,
            }
            _chosung_next_question(chat, state, prefix="🔠 자음 퀴즈 시작!")
            return True

        if state["current_game"] != "CHOSUNG":
            chat.reply("⚠️ 진행 중인 자음 퀴즈가 없습니다.\n/자음시작 으로 시작하세요.")
            return True

        data = state["data"]

        if cmd == "/자음문제":
            chat.reply(
                f"🔤 [{data['question_no']}번 문제]\n"
                f"────────\n"
                f"📂 분류 : {data['category']}\n"
                f"❓ 초성 : {data['chosung']}\n"
                f"📏 글자 : {len(data['answer'])}글자"
            )
            return True

        if cmd == "/자음힌트":
            if data["hint_used"]:
                chat.reply(f"💬 힌트는 문제당 한 번입니다.\n첫 글자 : {data['answer'][0]}")
                return True

            data["hint_used"] = True
            chat.reply(
                f"💬 힌트!\n"
                f"첫 글자 : {data['answer'][0]}\n"
                f"❓ 초성 : {data['chosung']} ({len(data['answer'])}글자)"
            )
            return True

        if cmd == "/자음패스":
            data["miss_streak"] = 0
            _chosung_next_question(chat, state, prefix=f"⏭️ 정답은 [{data['answer']}] 였습니다.")
            return True

        if cmd == "/자음끝":
            _finish_chosung(chat, state)
            return True

    return False
