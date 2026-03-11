from __future__ import annotations
import threading
import time
import random
from typing import Dict, Any, Optional
from iris import ChatContext

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
    print(msg)
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
        if cmd == "/반응게임":
            if state["current_game"]:
                chat.reply(f"⚠️ 이미 {state['current_game']} 게임이 진행 중입니다.")
                return
            state["current_game"] = "REACTION"
            state["data"] = {"status": "WAITING", "members": [], "current_idx": 0, "results": []}
            chat.reply("🎮 [반응 속도 게임] 모집!\n참여: /반응게임참여\n시작: /반응게임시작 (2명 이상)")

        elif cmd == "/반응게임참여":
            if state["current_game"] != "REACTION" or state["data"]["status"] != "WAITING": return
            user_id = chat.sender.id
            if any(m["id"] == user_id for m in state["data"]["members"]): return
            state["data"]["members"].append({"id": user_id, "name": _get_user_name(chat.sender)})
            chat.reply(f"✅ {_get_user_name(chat.sender)}님 참여! (현재 {len(state['data']['members'])}명)")

        elif cmd == "/반응게임시작":
            if state["current_game"] != "REACTION" or state["data"]["status"] != "WAITING": return
            if len(state["data"]["members"]) < 1:
                chat.reply("❌ 최소 2명 이상 참여해야 합니다.")
                return
            state["data"]["status"] = "RUNNING"
            _reaction_next_turn(chat, state)


def _reaction_next_turn(chat: ChatContext, state: Dict[str, Any]):
    data = state["data"]
    if data["current_idx"] >= len(data["members"]):
        _finish_reaction(chat, state)
        return

    current_idx = data["current_idx"]
    current_name = data["members"][current_idx]["name"]

    # 1. 턴 안내 메시지를 먼저 보냅니다.
    chat.reply(f"👉 {current_idx + 1}. {current_name}님 준비...!")

    # 2. 봇 멈춤 방지를 위해 별도 스레드에서 딜레이 후 번호를 띄웁니다.
    def delayed_popup():
        # 1.0초 ~ 3.0초 사이 랜덤 대기
        time.sleep(random.uniform(1.0, 3.0))

        with GAME_LOCK:
            # 대기하는 동안 게임이 취소되었거나 턴이 넘어갔는지 안전 확인
            if state.get("current_game") != "REACTION" or state["data"].get("current_idx") != current_idx:
                return

            # 랜덤 번호 출제 및 시작 시간 측정
            target_num = random.randint(10, 99)
            state["data"]["target_num"] = target_num
            state["data"]["start_time"] = time.time()

            chat.reply(f"🚨 [{target_num}] 🚨")

    # 스레드 실행
    threading.Thread(target=delayed_popup, daemon=True).start()

def _finish_reaction(chat: ChatContext, state: Dict[str, Any]):
    res = sorted(state["data"]["results"], key=lambda x: x["time"])
    msg = "🏆 [결과]\n" + "\n".join([f"{i + 1}. {r['name']} ({r['time']:.4f}초)" for i, r in enumerate(res)])
    chat.reply(msg)
    state["current_game"] = None  # 게임 종료


# ─────────────────────────────
# [2] 369 게임 로직
# ─────────────────────────────
def handle_369_command(chat: ChatContext):
    room_id = chat.room.id
    state = _get_game_state(room_id)
    cmd = chat.message.command

    with GAME_LOCK:
        if cmd == "/369시작":
            if state["current_game"]:
                chat.reply(f"⚠️ 이미 {state['current_game']} 게임이 진행 중입니다.")
                return
            state["current_game"] = "369"
            state["data"] = {"current": 1}
            chat.reply("🎉 369 시작! 봇부터 시작할게 👉 [봇] 1")
            return True
        elif cmd == "/369끝":
            state["current_game"] = None
            chat.reply("🛑 369 종료")
            return True
    return False


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
            target_str = str(data["target_num"])

            # 입력한 텍스트가 정답(숫자)과 일치하는 경우
            if text == target_str or text == f"/{target_str}":
                current_player_id = str(data["members"][data["current_idx"]]["id"])
                sender_id = str(chat.sender.id)

                # 1) 자기 차례가 맞는지 확인
                if sender_id == current_player_id:
                    elapsed = time.time() - data["start_time"]
                    data["results"].append({"name": data["members"][data["current_idx"]]["name"], "time": elapsed})
                    chat.reply(f"✅ 정답! 반응 시간: [{elapsed:.4f}초]")

                    data["current_idx"] += 1
                    _reaction_next_turn(chat, state)
                else:
                    # 2) 자기 차례가 아닌 사람이 친 경우 (원치 않으시면 이 두 줄은 지우셔도 됩니다)
                    chat.reply(f"❌ 지금은 {data['members'][data['current_idx']]['name']}님의 차례입니다!")
            return  # 반응게임 중일 땐 여기서 종료
        # 2. 369 게임 처리
        elif state["current_game"] == "369":
            data = state["data"]
            expect_n = data["current"] + 1
            # 369 규칙 계산 (생략된 기존로직 적용)
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
                chat.reply(f"❌ 틀렸어! {expect_n} 차례였고 정답은 {ans}")
                state["current_game"] = None