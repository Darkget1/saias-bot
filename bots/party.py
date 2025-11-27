# bots/party.py
from __future__ import annotations

import threading
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from iris import ChatContext

# ─────────────────────────────
# 전역 상태 (room_id -> { owner_id: party })
# ─────────────────────────────

PARTY_STATE: Dict[int, Dict[int, Dict[str, Any]]] = {}
PARTY_LOCK = threading.RLock()

# 파티 ID 시퀀스 (전역 증가 숫자)
_PARTY_ID_SEQ = 1


def _next_party_id() -> int:
    """새 파티 ID 발급 (전역 증가 숫자)."""
    global _PARTY_ID_SEQ
    pid = _PARTY_ID_SEQ
    _PARTY_ID_SEQ += 1
    return pid


def _truncate(text: str, max_len: int) -> str:
    """카톡 한 줄 18자 정도 맞추기 위해 길면 잘라서 … 붙이기."""
    text = str(text or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _get_room_id(chat: ChatContext) -> int:
    """방 ID 가져오기 (iris 기본 room.id 사용)."""
    return chat.room.id


# PARTY_STATE 구조 예시:
# {
#   room_id: {
#       owner_id: {
#           "party_id": int,      # 파티 고유 ID
#           "title": str,
#           "time_str": str,      # "21:30" 또는 "30분 뒤 (21:30)" 같이 표시용
#           "start_at": datetime, # 알림 예정 시간
#           "max_members": 4 또는 8,
#           "members": [ { "id": int, "name": str }, ... ],
#           "timer": threading.Timer,
#           "owner_id": int,
#           "owner_name": str,
#           "is_raid": bool,      # 레이드 파티 여부
#       },
#       ...
#   },
# }


# ─────────────────────────────
# 내부 유틸
# ─────────────────────────────

def _get_user_name(sender) -> str:
    """
    sender.name 이 None 이거나 없는 경우를 대비해서
    nickname, nick, id 등으로 안전하게 이름을 만들어준다.
    """
    name = getattr(sender, "name", None) \
        or getattr(sender, "nickname", None) \
        or getattr(sender, "nick", None)

    if not name:
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
        raise ValueError("시간과 제목을 함께 입력해주세요. 예) /파티 21:30 발로란트")

    parts = param.split(maxsplit=1)
    time_part = parts[0]
    title = parts[1] if len(parts) > 1 else "파티"

    now = datetime.now()

    # 1) HH:MM 형태
    if re.match(r"^\d{1,2}:\d{2}$", time_part):
        hour, minute = map(int, time_part.split(":"))
        start_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
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

    raise ValueError("시간 형식이 올바르지 않습니다. 예) /파티 21:30 제목  또는  /파티 30 제목")


def _notify_party(chat: ChatContext, room_id: int, owner_id: int):
    """타이머가 호출하는 실제 알림 함수 (멘션 없이 안내만)."""
    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            return

        party = room_parties.get(owner_id)
        if not party:
            return

        # 멤버 이름 리스트
        safe_names = []
        for m in party["members"]:
            n = m.get("name") or f"User{m.get('id', '?')}"
            safe_names.append(str(n))
        members_str = ", ".join(safe_names)

        kind = "레이드 파티" if party.get("is_raid") else "파티"
        outro = "즐거운 레이드 되세요!" if party.get("is_raid") else "즐거운 게임 되세요!"

        msg = (
            f"🎉 {kind} 시간입니다!\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"인원: {len(party['members'])}/{party['max_members']}\n"
            f"멤버: {members_str}\n\n"
            f"{outro}"
        )

        chat.reply(msg)

        # 알림 후 파티 삭제
        room_parties.pop(owner_id, None)
        if not room_parties:
            PARTY_STATE.pop(room_id, None)


def _find_party_by_owner_name(room_parties: Dict[int, Dict[str, Any]], name: str) -> Optional[int]:
    """파티장 닉네임(또는 @닉네임)으로 owner_id 찾기 (호환용)."""
    if not name:
        return None
    norm = name.lstrip("@").strip().lower()
    for owner_id, party in room_parties.items():
        owner_name = str(party.get("owner_name") or "").lower()
        if owner_name == norm:
            return owner_id
    for owner_id, party in room_parties.items():
        owner_name = str(party.get("owner_name") or "").lower()
        if norm in owner_name:
            return owner_id
    return None


# ─────────────────────────────
# 외부에서 호출할 명령 함수들
# ─────────────────────────────

def create_party(chat: ChatContext):
    """ /파티 명령 처리: 기본 4인 파티."""
    room_id = _get_room_id(chat)
    param = getattr(chat.message, "param", "") or ""

    owner_id = chat.sender.id
    owner_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.setdefault(room_id, {})

        if owner_id in room_parties:
            party = room_parties[owner_id]
            safe_names = [
                (m.get("name") or f"User{m.get('id', '?')}")
                for m in party["members"]
            ]
            members_str = ", ".join(str(n) for n in safe_names)

            chat.reply(
                "이미 이 방에 당신이 만든 파티가 있어요.\n"
                f"파티 ID: {party.get('party_id', '?')}\n"
                f"제목: {party['title']}\n"
                f"시간: {party['time_str']}\n"
                f"인원: {len(party['members'])}/{party['max_members']}\n"
                f"멤버: {members_str}\n"
                "해당 ID로 `/참가 파티ID` 명령을 사용할 수 있습니다."
            )
            return

        try:
            start_at, time_label, title = _parse_party_time(param)
        except ValueError as e:
            chat.reply(str(e))
            return

        creator = {
            "id": owner_id,
            "name": owner_name,
        }

        delay = max((start_at - datetime.now()).total_seconds(), 1.0)
        party_id = _next_party_id()

        timer = threading.Timer(
            delay,
            _notify_party,
            args=(chat, room_id, owner_id),
        )

        room_parties[owner_id] = {
            "party_id": party_id,
            "title": title,
            "time_str": time_label,
            "start_at": start_at,
            "max_members": 4,
            "members": [creator],
            "timer": timer,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "is_raid": False,
        }

        timer.start()

        chat.reply(
            "🎮 새 파티를 만들었어요!\n"
            f"파티 ID: {party_id}\n"
            f"제목: {title}\n"
            f"시간: {time_label}\n"
            "인원: 1/4\n"
            "참가하려면 `/참가 파티ID` 형식으로 보내주세요. 예) `/참가 3`"
        )


def create_raid_party(chat: ChatContext):
    """ /레이드파티 명령 처리: 8인 레이드 파티."""
    room_id = _get_room_id(chat)
    param = getattr(chat.message, "param", "") or ""

    owner_id = chat.sender.id
    owner_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.setdefault(room_id, {})

        if owner_id in room_parties:
            party = room_parties[owner_id]
            safe_names = [
                (m.get("name") or f"User{m.get('id', '?')}")
                for m in party["members"]
            ]
            members_str = ", ".join(str(n) for n in safe_names)

            chat.reply(
                "이미 이 방에 당신이 만든 파티가 있어요.\n"
                f"파티 ID: {party.get('party_id', '?')}\n"
                f"제목: {party['title']}\n"
                f"시간: {party['time_str']}\n"
                f"인원: {len(party['members'])}/{party['max_members']}\n"
                f"멤버: {members_str}\n"
                "해당 ID로 `/참가 파티ID` 명령을 사용할 수 있습니다."
            )
            return

        try:
            start_at, time_label, title = _parse_party_time(param)
        except ValueError as e:
            chat.reply(str(e))
            return

        creator = {
            "id": owner_id,
            "name": owner_name,
        }

        delay = max((start_at - datetime.now()).total_seconds(), 1.0)
        party_id = _next_party_id()

        timer = threading.Timer(
            delay,
            _notify_party,
            args=(chat, room_id, owner_id),
        )

        room_parties[owner_id] = {
            "party_id": party_id,
            "title": title,
            "time_str": time_label,
            "start_at": start_at,
            "max_members": 8,   # 레이드: 8명
            "members": [creator],
            "timer": timer,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "is_raid": True,
        }

        timer.start()

        chat.reply(
            "⚔️ 레이드 파티를 만들었어요!\n"
            f"파티 ID: {party_id}\n"
            f"제목: {title}\n"
            f"시간: {time_label}\n"
            "인원: 1/8\n"
            "참가하려면 `/참가 파티ID` 형식으로 보내주세요. 예) `/참가 3`"
        )


def delete_party(chat: ChatContext):
    """ /파티삭제 명령 처리 (내가 파티장인 파티들을 전부 삭제)."""
    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("현재 이 방에는 삭제할 파티가 없어요.")
            return

        owner_parties = [
            (oid, p) for oid, p in room_parties.items() if oid == user_id
        ]

        if not owner_parties:
            chat.reply("이 방에서 당신이 만든 파티가 없어요.")
            return

        for owner_id, party in owner_parties:
            timer = party.get("timer")
            if timer:
                timer.cancel()
            room_parties.pop(owner_id, None)

        if not room_parties:
            PARTY_STATE.pop(room_id, None)

        chat.reply("🛑 당신이 만든 파티를 모두 삭제했습니다.")


def join_party(chat: ChatContext):
    """ /참가 명령 처리 (파티 ID 기준, 닉네임 방식은 호환용)."""
    room_id = _get_room_id(chat)
    param = (getattr(chat.message, "param", "") or "").strip()
    user = {
        "id": chat.sender.id,
        "name": _get_user_name(chat.sender),
    }

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply(
                "현재 이 방에는 모집 중인 파티가 없어요.\n"
                "`/파티 21:30 제목` 또는 `/레이드파티 21:30 제목` 으로 새로 만들어주세요!"
            )
            return

        target_owner_id: Optional[int] = None
        party = None

        if param:
            if param.isdigit():
                target_party_id = int(param)
                for oid, p in room_parties.items():
                    if p.get("party_id") == target_party_id:
                        target_owner_id = oid
                        party = p
                        break
                if target_owner_id is None:
                    chat.reply(
                        "해당 파티 ID를 찾을 수 없어요.\n"
                        "현재 파티 목록은 `/파티현황` 으로 확인하고,\n"
                        "`/참가 파티ID` 형식으로 다시 시도해주세요."
                    )
                    return
            else:
                target_owner_id = _find_party_by_owner_name(room_parties, param)
                if target_owner_id is None:
                    chat.reply(
                        "해당 파티를 찾을 수 없어요.\n"
                        "이제는 `/참가 파티ID` 형식으로 참가하는 것을 권장합니다.\n"
                        "`/파티현황` 으로 파티 ID를 먼저 확인해주세요."
                    )
                    return
                party = room_parties.get(target_owner_id)
        else:
            if len(room_parties) == 1:
                target_owner_id = next(iter(room_parties.keys()))
                party = room_parties[target_owner_id]
            else:
                lines = ["현재 이 방에는 여러 파티가 있어요:"]
                for p_owner_id, p in room_parties.items():
                    kind = "레이드" if p.get("is_raid") else "일반"
                    lines.append(
                        f"- ID: {p.get('party_id', '?')} / [{kind}] 파티장: {p['owner_name']} "
                        f"/ 제목: {p['title']} / 시간: {p['time_str']} "
                        f"/ 인원: {len(p['members'])}/{p['max_members']}"
                    )
                lines.append("\n`/참가 파티ID` 로 참가할 파티를 골라주세요. 예) `/참가 3`")
                chat.reply("\n".join(lines))
                return

        if not party:
            chat.reply("선택한 파티가 더 이상 존재하지 않아요.")
            return

        if any(m["id"] == user["id"] for m in party["members"]):
            chat.reply("이미 이 파티에 참가 중이에요!")
            return

        if len(party["members"]) >= party["max_members"]:
            chat.reply(f"⚠️ 이미 인원이 가득 찼어요! ({party['max_members']}/{party['max_members']})")
            return

        party["members"].append(user)

        safe_names = [
            (m.get("name") or f"User{m.get('id', '?')}")
            for m in party["members"]
        ]
        members_str = ", ".join(str(n) for n in safe_names)

        kind = "레이드 파티" if party.get("is_raid") else "파티"

        chat.reply(
            f"✅ {kind}에 참가했습니다!\n"
            f"파티 ID: {party.get('party_id', '?')}\n"
            f"파티장: {party['owner_name']}\n"
            f"제목: {party['title']}\n"
            f"시간: {party['time_str']}\n"
            f"현재 인원: {len(party['members'])}/{party['max_members']}\n"
            f"멤버: {members_str}"
        )

        if len(party["members"]) == party["max_members"]:
            names = ", ".join(str(n) for n in safe_names)
            chat.reply(
                f"🎉 {kind} 인원이 모두 모였습니다! "
                f"({party['max_members']}/{party['max_members']})\n"
                f"파티 ID: {party.get('party_id', '?')}\n"
                f"파티장: {party['owner_name']}\n"
                f"멤버: {names}\n"
                f"시간: {party['time_str']} 에 알림을 보낼게요."
            )


def show_party_status(chat: ChatContext):
    """ /파티현황 명령 처리."""
    room_id = _get_room_id(chat)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("현재 이 방에는 모집 중인 파티가 없어요.")
            return

        lines: list[str] = ["📋 현재 파티 현황"]

        for idx, (owner_id, party) in enumerate(room_parties.items(), start=1):
            safe_names = []
            for m in party["members"]:
                n = m.get("name") or f"User{m.get('id', '?')}"
                safe_names.append(str(n))
            members_str = ", ".join(safe_names)

            kind = "레이드" if party.get("is_raid") else "일반"

            lines.append("────────────────")
            lines.append(f"#{idx} [{kind}]")
            lines.append(f"ID   : {party.get('party_id', '?')}")
            lines.append(f"파티장: {_truncate(party['owner_name'], 12)}")
            lines.append(f"제목  : {_truncate(party['title'], 14)}")
            lines.append(f"시간  : {_truncate(party['time_str'], 14)}")
            lines.append(
                f"인원  : {len(party['members'])}/{party['max_members']}"
            )
            lines.append(f"멤버  : {_truncate(members_str, 16)}")

        lines.append(
            "\n원하는 파티의 ID로 `/참가 파티ID` 를 입력해서 참가할 수 있어요. 예) `/참가 3`"
        )

        chat.reply("\n".join(lines))


def leave_party(chat: ChatContext):
    """ /파티취소 명령 처리 (본인이 속한 모든 파티에서 나가기)."""
    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("현재 이 방에는 모집 중인 파티가 없어요.")
            return

        joined: list[tuple[int, Dict[str, Any]]] = []
        for owner_id, party in list(room_parties.items()):
            if any(m["id"] == user_id for m in party["members"]):
                joined.append((owner_id, party))

        if not joined:
            chat.reply("이 방의 어떤 파티에도 참가 중이 아니에요.")
            return

        cancelled_titles = []
        left_titles = []

        for owner_id, party in joined:
            if party["owner_id"] == user_id:
                timer = party.get("timer")
                if timer:
                    timer.cancel()
                room_parties.pop(owner_id, None)
                cancelled_titles.append(party["title"])
            else:
                party["members"] = [m for m in party["members"] if m["id"] != user_id]
                if not party["members"]:
                    timer = party.get("timer")
                    if timer:
                        timer.cancel()
                    room_parties.pop(owner_id, None)
                    cancelled_titles.append(party["title"])
                else:
                    left_titles.append(party["title"])

        if not room_parties:
            PARTY_STATE.pop(room_id, None)

        msg_lines = []
        if left_titles:
            msg_lines.append(
                "다음 파티에서 나갔습니다:\n- " + "\n- ".join(left_titles)
            )
        if cancelled_titles:
            msg_lines.append(
                "다음 파티는 더 이상 멤버가 없어 취소되었습니다(또는 본인이 파티장이어서 삭제됨):\n- "
                + "\n- ".join(cancelled_titles)
            )
        if not msg_lines:
            msg_lines.append("변경된 파티가 없습니다.")

        chat.reply("\n\n".join(msg_lines))


def handle_party_command(chat: ChatContext):
    """
    메인 봇에서 `/파티`, `/레이드파티`, `/참가`, `/파티현황`, `/파티취소`, `/파티삭제`
    다 이 함수 하나로 라우팅.
    """
    cmd = chat.message.command

    if cmd == "/파티":
        create_party(chat)
    elif cmd == "/레이드파티":
        create_raid_party(chat)
    elif cmd == "/참가":
        join_party(chat)
    elif cmd == "/파티현황":
        show_party_status(chat)
    elif cmd == "/파티취소":
        leave_party(chat)
    elif cmd == "/파티삭제":
        delete_party(chat)
