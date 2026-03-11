from __future__ import annotations

import threading
from datetime import datetime, date
from typing import Dict, Any, Optional

from iris import ChatContext

# ─────────────────────────────
# 전역 상태 (room_id -> { event_id: event_info })
# ─────────────────────────────
EVENT_STATE: Dict[int, Dict[int, Dict[str, Any]]] = {}
EVENT_LOCK = threading.RLock()
_EVENT_STATE_DATE: Optional[date] = None


def _ensure_today_state():
    global EVENT_STATE, _EVENT_STATE_DATE
    today = datetime.now().date()
    if _EVENT_STATE_DATE != today:
        EVENT_STATE.clear()
        _EVENT_STATE_DATE = today


def _next_event_id(room_id: int) -> int:
    room_events = EVENT_STATE.get(room_id, {})
    eid = 1
    while eid in room_events:
        eid += 1
    return eid


def _get_user_name(sender) -> str:
    name = getattr(sender, "name", None) or getattr(sender, "nickname", None) or getattr(sender, "nick", None)
    return str(name) if name else f"User{getattr(sender, 'id', '?')}"


def _format_event_table(event: Dict[str, Any]) -> str:
    """순수 이름만 나오는 목록 포맷"""
    members = event.get("members", [])
    lines = [
        f"📢 [길드이벤트 #{event['event_id']}]",
        f"제목: {event['title']}",
        f"주최: {event['owner_name']}",
        f"인원: {len(members)}명",
        "",
        "👥 참여자 명단"
    ]

    if not members:
        lines.append("(아직 참여자가 없습니다)")
    else:
        for idx, m in enumerate(members, start=1):
            lines.append(f"{idx}. {m['name']}")

    return "\n".join(lines)


# ─────────────────────────────
# 명령어 함수들
# ─────────────────────────────

def create_event(chat: ChatContext):
    """ /이벤트생성 [제목] """
    _ensure_today_state()
    room_id = chat.room.id
    param = (getattr(chat.message, "param", "") or "").strip()
    title = param if param else "길드 이벤트"

    with EVENT_LOCK:
        room_events = EVENT_STATE.setdefault(room_id, {})
        eid = _next_event_id(room_id)
        room_events[eid] = {
            "event_id": eid,
            "title": title,
            "owner_id": chat.sender.id,
            "owner_name": _get_user_name(chat.sender),
            "members": []
        }
        chat.reply(f"✅ 새 이벤트가 생성되었습니다!\n\n{_format_event_table(room_events[eid])}\n\n참여: /참여 {eid}")


def join_event(chat: ChatContext):
    """ /참여 [번호] """
    _ensure_today_state()
    param = (getattr(chat.message, "param", "") or "").strip()

    if not param.isdigit():
        chat.reply("⚠️ 참여할 이벤트 번호를 입력해주세요.\n예) /참여 1")
        return

    eid = int(param)
    user_id = chat.sender.id

    with EVENT_LOCK:
        room_events = EVENT_STATE.get(chat.room.id, {})
        if eid not in room_events:
            chat.reply(f"❌ {eid}번 이벤트를 찾을 수 없습니다.")
            return

        event = room_events[eid]
        if any(m["id"] == user_id for m in event["members"]):
            chat.reply("이미 참여 명단에 있습니다!")
            return

        event["members"].append({"id": user_id, "name": _get_user_name(chat.sender)})
        chat.reply(f"✅ {event['title']} 참여 완료!\n\n{_format_event_table(event)}")


def delete_event(chat: ChatContext):
    """ /이벤트삭제 [번호] """
    param = (getattr(chat.message, "param", "") or "").strip()
    if not param.isdigit():
        chat.reply("삭제할 번호를 입력하세요.")
        return

    eid = int(param)
    with EVENT_LOCK:
        room_events = EVENT_STATE.get(chat.room.id, {})
        if eid in room_events:
            if room_events[eid]["owner_id"] == chat.sender.id:
                del room_events[eid]
                chat.reply(f"🗑 {eid}번 이벤트를 삭제했습니다.")
            else:
                chat.reply("주최자만 삭제할 수 있습니다.")


def show_events_status(chat: ChatContext):
    _ensure_today_state()
    room_events = EVENT_STATE.get(chat.room.id, {})
    if not room_events:
        chat.reply("현재 진행 중인 이벤트가 없습니다.")
        return

    lines = ["📋 길드 이벤트 현황"]
    for eid, ev in room_events.items():
        lines.append(f"#{eid} {ev['title']} ({len(ev['members'])}명)")

    lines.append("\n/참여 [번호] 로 신청하세요!")
    chat.reply("\n".join(lines))


def show_my_events(chat: ChatContext):
    room_events = EVENT_STATE.get(chat.room.id, {})
    my_list = [f"#{eid} {ev['title']}" for eid, ev in room_events.items() if ev["owner_id"] == chat.sender.id]

    if not my_list:
        chat.reply("내가 만든 이벤트가 없습니다.")
    else:
        chat.reply("📋 내가 주최한 이벤트\n" + "\n".join(my_list) + "\n\n삭제: /이벤트삭제 [번호]")

def show_event_help(chat: ChatContext):
    """ /이벤트도움말 명령 처리 """
    lines = [
        "🎮 [길드 이벤트 도움말]",
        "",
        "✅ 이벤트 생성/관리",
        "• /이벤트생성 [제목] : 새 모집 시작",
        "• /내이벤트 : 내가 만든 목록 확인",
        "• /이벤트삭제 [번호] : 모집 취소 (주최자만)",
        "",
        "✅ 참여하기",
        "• /참여 [번호] : 명단에 이름 올리기",
        "• /이벤트목록 : 현재 모집 중인 이벤트 확인",
        "",
        "💡 방장이 이벤트를 만들어도 자동으로 참여되지 않으니, 생성 후 꼭 직접 [/참여 번호]를 입력해주세요!"
    ]
    chat.reply("\n".join(lines))

def handle_event_command(chat: ChatContext):
    cmd = chat.message.command
    if cmd == "/이벤트생성":
        create_event(chat)
    elif cmd in ("/이벤트참여", "/참여"):
        join_event(chat)
    elif cmd == "/이벤트삭제":
        delete_event(chat)
    elif cmd == "/내이벤트":
        show_my_events(chat)
    elif cmd in ("/이벤트목록", "/이벤트현황"):
        show_events_status(chat)
    elif cmd in ("/이벤트도움말"):
        show_event_help(chat)