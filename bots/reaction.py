from __future__ import annotations

import threading
import time
import random
from datetime import datetime
from typing import Dict, List, Any, Optional

from iris import ChatContext

# ─────────────────────────────
# 전역 상태 (room_id -> game_info)
# ─────────────────────────────
REACTION_STATE: Dict[int, Dict[str, Any]] = {}
REACTION_LOCK = threading.RLock()


def _get_user_name(sender) -> str:
    name = getattr(sender, "name", None) or getattr(sender, "nickname", None) or getattr(sender, "nick", None)
    return str(name) if name else f"User{getattr(sender, 'id', '?')}"


# ─────────────────────────────
# 명령어 함수들
# ─────────────────────────────

def start_reaction_game(chat: ChatContext):
    """ /반응게임 : 모집 시작 """
    room_id = chat.room.id

    with REACTION_LOCK:
        if room_id in REACTION_STATE:
            chat.reply("⚠️ 이미 반응 속도 게임이 진행 중입니다.")
            return

        REACTION_STATE[room_id] = {
            "status": "WAITING",
            "members": [],
            "current_idx": 0,
            "target_num": 0,
            "start_time": 0.0,
            "results": []
        }

    chat.reply("🎮 [반응 속도 게임] 모집 시작!\n\n참여: /반응게임참여\n시작: /반응게임시작 (방장)")


def join_reaction_game(chat: ChatContext):
    """ /반응게임참여 """
    room_id = chat.room.id
    user_id = chat.sender.id
    user_name = _get_user_name(chat.sender)

    with REACTION_LOCK:
        game = REACTION_STATE.get(room_id)
        if not game or game["status"] != "WAITING":
            return

        if any(m["id"] == user_id for m in game["members"]):
            chat.reply(f"이미 참여하셨습니다, {user_name}님!")
            return

        game["members"].append({"id": user_id, "name": user_name})

        member_names = ", ".join([m["name"] for m in game["members"]])
        chat.reply(f"✅ {user_name}님 게임 참여!\n현재 대기열: {member_names}")


def begin_reaction_game(chat: ChatContext):
    """ /반응게임시작 : 2명 이상일 때만 시작 가능 """
    room_id = chat.room.id

    with REACTION_LOCK:
        game = REACTION_STATE.get(room_id)
        if not game or game["status"] != "WAITING":
            return

        # 참여 인원 체크 로직 추가
        member_count = len(game["members"])
        if member_count < 1:
            chat.reply(f"❌ 최소 2명 이상 참여해야 게임을 시작할 수 있습니다. (현재 {member_count}명)")
            return

        game["status"] = "RUNNING"
        chat.reply(f"🚀 게임을 시작합니다! (총 {member_count}명)")
        _next_turn(chat, game)

def _next_turn(chat: ChatContext, game: Dict[str, Any]):
    """ 다음 순서 유저에게 숫자 제시 """
    idx = game["current_idx"]
    if idx >= len(game["members"]):
        _finish_game(chat, game)
        return

    current_player = game["members"][idx]
    target = random.randint(10, 99)
    game["target_num"] = target

    # [52] 형식으로 제시
    chat.reply(f"{idx + 1}. {current_player['name']}\n\n[{target}]")
    game["start_time"] = time.time()


def handle_reaction_input(chat: ChatContext):
    """ 일반 텍스트 입력 중 현재 순서 유저가 숫자를 맞췄는지 확인 """

    room_id = chat.room.id
    user_id = chat.sender.id

    # 1. 메인과 동일한 방식으로 안전하게 텍스트 추출
    msg_obj = chat.message
    # chat.message가 문자열일 수도, 객체일 수도 있으므로 안전하게 처리
    raw_text = msg_obj if isinstance(msg_obj, str) else getattr(msg_obj, "text", "") or getattr(msg_obj, "content",
                                                                                                "") or str(msg_obj)
    text = str(raw_text).strip()
    print("게임텍스트",text)
    with REACTION_LOCK:
        game = REACTION_STATE.get(room_id)

        # [체크] 이 방에서 반응 게임이 진행 중(RUNNING)인지 확인
        if not game or game.get("status") != "RUNNING":
            return

        # [체크] 현재 자기 차례인 유저가 보낸 것인지 확인
        current_player = game["members"][game["current_idx"]]
        if user_id != current_player["id"]:
            return

        # [체크] 입력한 숫자가 제시된 숫자(target_num)와 정확히 일치하는지 확인
        if text == str(game["target_num"]):
            elapsed = time.time() - game["start_time"]

            game["results"].append({
                "name": current_player["name"],
                "time": elapsed
            })

            # 결과 출력 (예: 1. 칸쵸타드 반응 시간 [2.1023초])
            chat.reply(f"{game['current_idx'] + 1}. {current_player['name']} 반응 시간 [{elapsed:.4f}초]")

            # 다음 사람으로 순서 넘기기
            game["current_idx"] += 1
            _next_turn(chat, game)


def _finish_game(chat: ChatContext, game: Dict[str, Any]):
    """ 모든 참가자 종료 후 결과 발표 """
    lines = ["🏆 [반응 속도 게임 결과]", ""]

    # 기록이 빠른 순서대로 정렬
    sorted_res = sorted(game["results"], key=lambda x: x["time"])

    for i, res in enumerate(sorted_res, start=1):
        lines.append(f"{i}등. {res['name']} ({res['time']:.4f}초)")

    chat.reply("\n".join(lines))
    REACTION_STATE.pop(chat.room.id, None)


def handle_reaction_command(chat: ChatContext):
    """ 라우팅 함수 """
    cmd = chat.message.command
    if cmd == "/반응게임":
        start_reaction_game(chat)
    elif cmd == "/반응게임참여":
        join_reaction_game(chat)
    elif cmd == "/반응게임시작":
        begin_reaction_game(chat)