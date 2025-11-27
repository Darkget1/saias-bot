# bots/game_369.py
from __future__ import annotations

import threading
import random
from typing import Dict, Any

from iris import ChatContext

# ─────────────────────────────
# 369 게임 상태
# ─────────────────────────────

GAME_369_STATE: Dict[str, Dict[str, Any]] = {}
GAME_369_LOCK = threading.RLock()

# 봇이 끼어들 때 쓸 재밌는 멘트 템플릿들
# {answer} 위치에 실제 369 답(숫자 또는 ㅉㅉ)이 들어감
BOT_369_MESSAGES = [
    "[봇] {answer}",
    "[봇] 나도 한 번 껴볼게 → {answer}",
    "[봇] 여기서 내가 받아간다 {answer}",
    "[봇] 조용히… {answer}",
    "[봇] 에이 이건 내가 해야지 {answer}",
    "[봇] 생각보다 쉽네 {answer}",
    "[봇] 눈치게임 실패한 김에 나도 {answer}",
    "[봇] 잠깐, 여기 {answer}",
    "[봇] 오케이 내 차례지? {answer}",
    "[봇] 369 자동완성: {answer}",
    "[봇] 끼어들기 성공 ✋ {answer}",
]


def _get_room_id(chat: ChatContext) -> str:
    """
    방/채팅을 구분할 수 있는 고유값.
    (메인 스크립트에서 쓰는 방식과 동일하게 맞춰도 됨)
    """
    if hasattr(chat, "room") and hasattr(chat.room, "id"):
        return str(chat.room.id)
    return str(chat.sender.id)


def _get_state(room_id: str) -> Dict[str, Any]:
    """
    방(room_id)별 369 상태 가져오기 (없으면 초기화).
    """
    with GAME_369_LOCK:
        if room_id not in GAME_369_STATE:
            GAME_369_STATE[room_id] = {
                "active": False,   # 게임 진행 여부
                "current": 0,      # 마지막까지 성공한 숫자
                "join_rate": 0.3,  # 봇이 다음 턴에 끼어드는 확률
            }
        return GAME_369_STATE[room_id]


def _reset_state(room_id: str) -> None:
    """
    해당 방의 369 게임 상태 완전 초기화.
    """
    with GAME_369_LOCK:
        GAME_369_STATE.pop(room_id, None)


def _format_answer(n: int) -> str:
    """
    369 규칙으로 정답 문자열 만들기.

    - 3, 6, 9가 하나도 없으면 숫자 그대로 (예: "1", "25")
    - 포함된 개수만큼 'ㅉ' 반복 (예: "3" → "ㅉ", "39" → "ㅉㅉ")
    """
    s = str(n)
    clap_cnt = sum(1 for ch in s if ch in "369")
    if clap_cnt == 0:
        return s
    return "ㅉ" * clap_cnt


def _normalize_input(text: str) -> str:
    """
    유저 입력을 비교하기 쉽게 정규화.
    - 숫자가 있으면: 숫자만 추출 → "12"
    - 'ㅉ'이 있으면: 'ㅉ'만 남김 → "ㅉㅉ"
    """
    text = text.strip()

    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return digits

    claps = "".join(ch for ch in text if ch == "ㅉ")
    if claps:
        return claps

    return text


def _bot_take_turn(chat: ChatContext, state: Dict[str, Any]) -> None:
    """
    봇이 중간에 같이 369를 말하는 부분.
    항상 정답만 말하고, 재밌는 멘트를 랜덤으로 붙인다.
    """
    current = state["current"]
    next_n = current + 1
    answer = _format_answer(next_n)

    # 재밌는 멘트 템플릿 중 하나 랜덤 선택
    template = random.choice(BOT_369_MESSAGES)
    msg = template.format(answer=answer)

    chat.reply(msg)
    state["current"] = next_n


# ─────────────────────────────
# 공개 API: 명령 처리 / 일반 메시지 처리
# ─────────────────────────────

def handle_369_command(chat: ChatContext) -> bool:
    """
    369 관련 명령어라면 처리하고 True, 아니면 False 반환.
    - /369시작
    - /369끝
    - /369상태
    - /369도움말, /369
    """
    cmd = getattr(chat.message, "command", "")

    room_id = _get_room_id(chat)
    state = _get_state(room_id)

    # ─ /369시작 ─
    if cmd == "/369시작":
        # 게임 상태 초기화
        state["active"] = True
        state["current"] = 0

        # 안내 멘트
        chat.reply(
            "🎉 369 게임 시작!\n"
            "- 숫자 또는 `ㅉ` 로만 보내면 돼.\n"
            "- 규칙 예시:\n"
            "  1 → 1\n"
            "  2 → 2\n"
            "  3 → ㅉ\n"
            "  29 → 29\n"
            "  39 → ㅉㅉ\n"
            "- 나는 중간중간 랜덤 멘트 치면서 같이 참여할 거야 😎\n"
            "\n"
            "먼저 내가 1부터 시작할게 👉"
        )

        # 시작하자마자 봇이 1 먼저 치기
        _bot_take_turn(chat, state)  # current=0 → [봇] 1, current=1

        return True

    # ─ /369끝 ─
    if cmd == "/369끝":
        _reset_state(room_id)
        chat.reply("🛑 369 게임 종료! `/369시작` 으로 다시 시작 가능")
        return True

    # ─ /369상태 ─
    if cmd == "/369상태":
        if not state["active"]:
            chat.reply("지금은 369 게임이 꺼져 있어. `/369시작` 으로 시작해줘!")
        else:
            chat.reply(
                f"현재 숫자: {state['current']}\n"
                f"(다음은 {state['current'] + 1} 차례)"
            )
        return True

    # ─ /369도움말, /369 ─
    if cmd in ("/369도움말", "/369"):
        chat.reply(
            "📘 369 게임 도움말\n"
            "- `/369시작` : 게임 시작 (봇이 1부터 시작)\n"
            "- `/369끝` : 게임 종료\n"
            "- `/369상태` : 현재 진행 상황 표시\n"
            "- 규칙:\n"
            "  · 3,6,9가 하나도 없으면 숫자 그대로 보내기 (예: 1, 25)\n"
            "  · 3,6,9가 들어가면 개수만큼 `ㅉ` 보내기 (예: 3→ㅉ, 39→ㅉㅉ)\n"
            "- 나는 랜덤 멘트 치면서 랜덤 타이밍에 끼어들어 😏"
        )
        return True

    return False


def handle_369_turn(chat: ChatContext) -> None:
    """
    일반 메시지를 369 게임 턴으로 처리.
    - 명령어(!, / 로 시작)는 무시
    - 게임이 활성화된 방에서만 동작
    - 틀리면 게임 종료 + 누가 틀렸는지 알려줌
    """
    # 1) 텍스트 가져오기 (Iris는 보통 param에 실제 내용이 들어감)
    text = ""

    if hasattr(chat, "message"):
        text = getattr(chat.message, "param", "") or \
               getattr(chat.message, "text", "") or \
               getattr(chat.message, "command", "")
    else:
        text = getattr(chat, "text", "") or ""

    text = (text or "").strip()
    if not text:
        return

    # 2) 명령어는 건들지 않기
    if text[0] in ("!", "/"):
        return

    room_id = _get_room_id(chat)
    state = _get_state(room_id)

    if not state["active"]:
        return

    normalized = _normalize_input(text)
    expected_n = state["current"] + 1
    expected_answer = _format_answer(expected_n)

    # 3) 정답일 때
    if normalized == expected_answer:
        state["current"] = expected_n

        # 가끔 칭찬
        if random.random() < 0.2:
            chat.reply(f"✅ 정답! 다음은 {expected_n + 1}번!")

        # 랜덤으로 봇이 바로 다음 턴 가져감
        if random.random() < state.get("join_rate", 0.3):
            _bot_take_turn(chat, state)
        return

    # 4) 오답일 때 → 게임 종료 + 누가 틀렸는지
    name = getattr(chat.sender, "name", None) \
        or getattr(chat.sender, "nickname", None) \
        or "누군가"

    chat.reply(
        f"❌ `{name}` 가(이) 틀려서 369 게임 종료!\n"
        f"지금은 {expected_n} 차례였고, 정답은 `{expected_answer}` 였어.\n"
        "다시 하려면 `/369시작` 으로 새로 시작해줘 🌀"
    )

    _reset_state(room_id)
