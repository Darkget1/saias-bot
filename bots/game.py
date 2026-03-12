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

    # 1. 턴 안내 메시지를 보냅니다.
    chat.reply(f"👉 {current_idx + 1}. {current_name}님 준비...!")

    # 2. 딜레이 없이 즉시 랜덤 번호 출제 및 시작 시간 측정
    target_num = random.randint(10, 99)
    state["data"]["target_num"] = target_num
    state["data"]["start_time"] = time.time()

    # 3. 헷갈리게 멘트를 여러 개 준비해서 랜덤으로 하나 선택
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

    # 랜덤으로 포맷을 골라서 출력
    chosen_msg = random.choice(confusing_formats)
    chat.reply(chosen_msg)


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

        game_names_kr = {
            "REACTION": "반응 속도",
            "369": "369"
        }
        raw_game_name = state["current_game"]
        display_name = game_names_kr.get(raw_game_name, raw_game_name)

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

        # 2. 369 게임 처리
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