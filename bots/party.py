# bots/party.py
from __future__ import annotations

import threading
import re
from datetime import datetime, timedelta
from typing import Dict, Any

from iris import ChatContext

# ─────────────────────────────
# 전역 상태
# ─────────────────────────────

PARTY_STATE: Dict[int, Dict[str, Any]] = {}
PARTY_LOCK = threading.RLock()

# PARTY_STATE 구조 예시:
# {
#   room_id: {
#       "title": str,
#       "time_str": str,      # "21:30" 또는 "30분 뒤 (21:30)" 같이 표시용
#       "start_at": datetime, # 알림 예정 시간
#       "max_members": 4,
#       "members": [ { "id": int, "name": str }, ... ],
#       "timer": threading.Timer,
#   }
# }


# ─────────────────────────────
# 내부 유틸
# ─────────────────────────────

def _get_room_id(chat: ChatContext) -> int:
    """방 ID 가져오기 (iris 기본 room.id 사용)."""
    return chat.room.id


def _get_user_name(sender) -> str:
    """
    sender.name 이 None 이거나 없는 경우를 대비해서
    nickname, nick, id 등으로 안전하게 이름을 만들어준다.
    """
    name = getattr(sender, "name", None) \
        or getattr(sender, "nickname", None) \
        or getattr(sender, "nick", None)

    if not name:
        # 그래도 없으면 id 기반으로 대체
        uid = getattr(sender, "id", "?")
        name = f"User{uid}"
    return str(name)


def _parse_party_time(param: str) -> tuple[datetime, str, str]:
    """
    param 예시:
      - '21:30 발로란트'
      - '30 발로란트'
      - '21:30'
    반환:
      (start_at: datetime, time_label: str, title: str)
    """
    param = (param or "").strip()
    if not param:
        raise ValueError("시간과 제목을 함께 입력해주세요. 예) !파티 21:30 발로란트")

    parts = param.split(maxsplit=1)
    time_part = parts[0]
    title = parts[1] if len(parts) > 1 else "파티"

    now = datetime.now()

    # 1) HH:MM 형태
    if re.match(r"^\d{1,2}:\d{2}$", time_part):
        hour, minute = map(int, time_part.split(":"))
        start_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # 이미 지난 시간이면 내일로
        if start_at <= now:
            start_at = start_at + timedelta(days=1)
        time_label = start_at.strftime("%m/%d %H:%M")
        return start_at, time_label, title

    # 2) 숫자만 → N분 뒤
    if time_part.isdigit():
        minutes = int(time_part)
        start_at = now + timedelta(minutes=minutes)
        time_label = f"{minutes}분 뒤 ({start_at.strftime('%H:%M')})"
        return start_at, time_label, title

    raise ValueError("시간 형식이 올바르지 않습니다. 예) !파티 21:30 제목  또는  !파티 30 제목")


def _notify_party(chat: ChatContext, room_id: int):
    """타이머가 호출하는 실제 알림 함수."""
    with PARTY_LOCK:
        party = PARTY_STATE.get(room_id)
        if not party:
            return

        # None 방지: 이름이 없으면 User{id} 형태로 대체
        safe_names = []
        for m in party["members"]:
            n = m.get("name") or f"User{m.get('id', '?')}"
            safe_names.append(str(n))

        # @닉네임 텍스트 멘션용
        mention_list = [f"@{n}" for n in safe_names]
        mention_text = " ".join(mention_list)

        members_str = ", ".join(safe_names)

        msg = (
            f"{mention_text}\n"  # 맨 위에 멘션들 쭉
            "🎉 파티 시간입니다!\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"인원: {len(party['members'])}/{party['max_members']}\n"
            f"멤버: {members_str}\n\n"
            "즐거운 게임 되세요!"
        )

        chat.reply(msg)

        # 알림 후 파티 삭제
        PARTY_STATE.pop(room_id, None)


# ─────────────────────────────
# 외부에서 호출할 명령 함수들
# ─────────────────────────────

def create_party(chat: ChatContext):
    """!파티 명령 처리: 새 파티 만들기."""
    room_id = _get_room_id(chat)
    param = getattr(chat.message, "param", "") or ""

    with PARTY_LOCK:
        if room_id in PARTY_STATE:
            party = PARTY_STATE[room_id]
            # 출력할 때도 safe name 사용
            safe_names = [
                (m.get("name") or f"User{m.get('id', '?')}")
                for m in party["members"]
            ]
            members_str = ", ".join(str(n) for n in safe_names)

            chat.reply(
                "이미 모집 중인 파티가 있어요.\n"
                f"제목: {party['title']}\n"
                f"시간: {party['time_str']}\n"
                f"인원: {len(party['members'])}/{party['max_members']}\n"
                f"멤버: {members_str}"
            )
            return

        try:
            start_at, time_label, title = _parse_party_time(param)
        except ValueError as e:
            chat.reply(str(e))
            return

        creator = {
            "id": chat.sender.id,
            "name": _get_user_name(chat.sender),
        }

        delay = max((start_at - datetime.now()).total_seconds(), 1.0)

        timer = threading.Timer(
            delay,
            _notify_party,
            args=(chat, room_id),
        )

        PARTY_STATE[room_id] = {
            "title": title,
            "time_str": time_label,
            "start_at": start_at,
            "max_members": 4,
            "members": [creator],
            "timer": timer,
            "owner_id": creator["id"],  # ✅ 파티장 ID 저장
        }

        timer.start()

        chat.reply(
            "🎮 새 파티를 만들었어요!\n"
            f"제목: {title}\n"
            f"시간: {time_label}\n"
            "인원: 1/4\n"
            "참가하려면 `!참가` 라고 보내주세요."
        )


def delete_party(chat: ChatContext):
    """!파티삭제 명령 처리 (파티장이 강제 종료)."""
    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        party = PARTY_STATE.get(room_id)
        if not party:
            chat.reply("현재 이 방에는 삭제할 파티가 없어요.")
            return

        owner_id = party.get("owner_id")

        # 파티장만 삭제 가능하도록 (원하면 이 조건은 빼도 됨)
        if owner_id is not None and owner_id != user_id:
            chat.reply("이 파티를 만든 사람만 파티를 삭제할 수 있어요.")
            return

        # 타이머 취소
        timer = party.get("timer")
        if timer:
            timer.cancel()

        # 멤버 이름들 보기 좋게 정리
        safe_names = [
            (m.get("name") or f"User{m.get('id', '?')}")
            for m in party["members"]
        ]
        members_str = ", ".join(str(n) for n in safe_names)

        PARTY_STATE.pop(room_id, None)

        chat.reply(
            "🛑 파티를 강제 종료했습니다.\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"멤버: {members_str}"
        )

def join_party(chat: ChatContext):
    """!참가 명령 처리."""
    room_id = _get_room_id(chat)
    user = {
        "id": chat.sender.id,
        "name": _get_user_name(chat.sender),
    }

    with PARTY_LOCK:
        party = PARTY_STATE.get(room_id)
        if not party:
            chat.reply(
                "현재 이 방에는 모집 중인 파티가 없어요.\n"
                "`!파티 21:30 제목` 처럼 새로 만들어주세요!"
            )
            return

        # 이미 참가
        if any(m["id"] == user["id"] for m in party["members"]):
            chat.reply("이미 이 파티에 참가 중이에요!")
            return

        if len(party["members"]) >= party["max_members"]:
            chat.reply("⚠️ 이미 인원이 가득 찼어요! (4/4)")
            return

        party["members"].append(user)

        safe_names = [
            (m.get("name") or f"User{m.get('id', '?')}")
            for m in party["members"]
        ]
        members_str = ", ".join(str(n) for n in safe_names)

        chat.reply(
            "✅ 파티에 참가했습니다!\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"현재 인원: {len(party['members'])}/{party['max_members']}\n"
            f"멤버: {members_str}"
        )

        if len(party["members"]) == party["max_members"]:
            names = ", ".join(str(n) for n in safe_names)
            chat.reply(
                "🎉 파티 인원이 모두 모였습니다! (4/4)\n"
                f"멤버: {names}\n"
                f"시간: {party['time_str']} 에 알림을 보낼게요."
            )


def show_party_status(chat: ChatContext):
    """!파티현황 명령 처리."""
    room_id = _get_room_id(chat)

    with PARTY_LOCK:
        party = PARTY_STATE.get(room_id)
        if not party:
            chat.reply("현재 이 방에는 모집 중인 파티가 없어요.")
            return

        safe_names = [
            (m.get("name") or f"User{m.get('id', '?')}")
            for m in party["members"]
        ]
        members_str = ", ".join(str(n) for n in safe_names)

        chat.reply(
            "📋 현재 파티 현황\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"인원: {len(party['members'])}/{party['max_members']}\n"
            f"멤버: {members_str}"
        )


def leave_party(chat: ChatContext):
    """!파티취소 명령 처리 (본인 파티에서 나가기)."""
    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        party = PARTY_STATE.get(room_id)
        if not party:
            chat.reply("현재 이 방에는 모집 중인 파티가 없어요.")
            return

        before = len(party["members"])
        party["members"] = [m for m in party["members"] if m["id"] != user_id]
        after = len(party["members"])

        if before == after:
            chat.reply("이 파티에 참가 중인 상태가 아니에요.")
            return

        if after == 0:
            timer = party.get("timer")
            if timer:
                timer.cancel()
            PARTY_STATE.pop(room_id, None)
            chat.reply("마지막 참가자가 나갔습니다. 파티를 취소합니다.")
            return

        safe_names = [
            (m.get("name") or f"User{m.get('id', '?')}")
            for m in party["members"]
        ]
        members_str = ", ".join(str(n) for n in safe_names)

        chat.reply(
            "파티에서 나갔습니다.\n"
            f"현재 인원: {after}/{party['max_members']}\n"
            f"멤버: {members_str}"
        )


def handle_party_command(chat: ChatContext):
    """
    메인 봇에서 `!파티`, `!참가`, `!파티현황`, `!파티취소`
    네 가지 모두 이 함수 하나로 처리하게 만들기.
    """
    cmd = chat.message.command

    if cmd == "!파티":
        create_party(chat)
    elif cmd == "!참가":
        join_party(chat)
    elif cmd == "!파티현황":
        show_party_status(chat)
    elif cmd == "!파티취소":
        leave_party(chat)
    elif cmd == "!파티삭제":          # ✅ 여기 추가
        delete_party(chat)
