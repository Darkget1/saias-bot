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
    # global EVENT_STATE, _EVENT_STATE_DATE
    # today = datetime.now().date()
    # if _EVENT_STATE_DATE != today:
    #     EVENT_STATE.clear()
    #     _EVENT_STATE_DATE = today
    pass


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
        chat.reply(f"✅ 새 이벤트가 생성되었습니다!\n\n{_format_event_table(room_events[eid])}\n\n참여: /이벤트참여 {eid}")


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
        "• /이벤트삭제 [이벤트번호] : 모집 취소 (주최자만)",
        "• /이벤트멤버삭제 [이벤트번호] [참여자번호] : 특정 참여자 제외 (주최자만)",
        "",
        "✅ 참여 및 홍보",
        "• /이벤트참여 [이벤트번호] : 명단에 이름 올리기",
        "• /이벤트탈퇴 [이벤트번호] : 참여한 이벤트에서 빠지기",
        "• /이벤트홍보 [이벤트번호] : 채팅방에 이벤트 다시 알리기 (주최자/참여자만)",
        "• /이벤트목록 : 현재 모집 중인 이벤트 확인",
        "",
        "💡 방장이 이벤트를 만들어도 자동으로 참여되지 않으니, 생성 후 꼭 직접 [/참여 번호]를 입력해주세요!"
    ]
    chat.reply("\n".join(lines))


def remove_event_member(chat: ChatContext):
    """ /이벤트멤버삭제 [이벤트번호] [참여자번호] """
    param = (getattr(chat.message, "param", "") or "").strip()
    parts = param.split()

    # 파라미터가 2개가 아니거나 둘 다 숫자가 아닌 경우
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        chat.reply("⚠️ 사용법: /이벤트멤버삭제 [이벤트번호] [참여자번호]\n예) /이벤트멤버삭제 1 2 (1번 이벤트의 2번째 참여자 삭제)")
        return

    eid = int(parts[0])
    member_idx = int(parts[1])

    with EVENT_LOCK:
        room_events = EVENT_STATE.get(chat.room.id, {})
        if eid not in room_events:
            chat.reply(f"❌ {eid}번 이벤트를 찾을 수 없습니다.")
            return

        event = room_events[eid]

        # 주최자 권한 확인
        if event["owner_id"] != chat.sender.id:
            chat.reply("❌ 주최자만 참여 멤버를 삭제할 수 있습니다.")
            return

        # 참여자 번호 유효성 검사 (1번부터 시작하므로)
        if member_idx < 1 or member_idx > len(event["members"]):
            chat.reply(f"❌ {member_idx}번 참여자를 찾을 수 없습니다. (현재 인원: {len(event['members'])}명)")
            return

        # 참여자 삭제 (리스트 인덱스는 0부터 시작하므로 member_idx - 1)
        removed_member = event["members"].pop(member_idx - 1)

        chat.reply(f"✅ '{removed_member['name']}'님을 이벤트 명단에서 제외했습니다.\n\n{_format_event_table(event)}")


def leave_event(chat: ChatContext):
    """ /이벤트탈퇴 [번호] """
    param = (getattr(chat.message, "param", "") or "").strip()

    if not param.isdigit():
        chat.reply("⚠️ 탈퇴할 이벤트 번호를 입력해주세요.\n예) /이벤트탈퇴 1")
        return

    eid = int(param)
    user_id = chat.sender.id

    with EVENT_LOCK:
        room_events = EVENT_STATE.get(chat.room.id, {})
        if eid not in room_events:
            chat.reply(f"❌ {eid}번 이벤트를 찾을 수 없습니다.")
            return

        event = room_events[eid]
        original_count = len(event["members"])

        # 본인 ID와 일치하지 않는 멤버들만 남김 (탈퇴 처리)
        event["members"] = [m for m in event["members"] if m["id"] != user_id]

        if len(event["members"]) == original_count:
            chat.reply("❌ 해당 이벤트에 참여하고 있지 않습니다.")
            return

        chat.reply(f"✅ {event['title']} 이벤트에서 성공적으로 탈퇴했습니다.\n\n{_format_event_table(event)}")


def promote_event(chat: ChatContext):
    """ /이벤트홍보 [번호] """
    _ensure_today_state()
    param = (getattr(chat.message, "param", "") or "").strip()

    if not param.isdigit():
        chat.reply("⚠️ 홍보할 이벤트 번호를 입력해주세요.\n예) /이벤트홍보 1")
        return

    eid = int(param)
    user_id = chat.sender.id

    with EVENT_LOCK:
        room_events = EVENT_STATE.get(chat.room.id, {})
        if eid not in room_events:
            chat.reply(f"❌ {eid}번 이벤트를 찾을 수 없습니다.")
            return

        event = room_events[eid]

        # 권한 확인: 주최자이거나 참여자 명단에 있는지 체크
        is_owner = event["owner_id"] == user_id
        is_member = any(m["id"] == user_id for m in event["members"])

        if not (is_owner or is_member):
            chat.reply("❌ 이벤트를 주최하거나 참여한 사람만 홍보할 수 있습니다.")
            return

        # 홍보 메시지 출력
        reply_msg = (
            f"📣 **[이벤트 홍보] 함께할 분들을 모집 중입니다!** 📣\n\n"
            f"{_format_event_table(event)}\n\n"
            f"👉 같이 하실 분은 `/참여 {eid}` 를 입력해주세요!"
        )
        chat.reply(reply_msg)


def handle_event_command(chat: ChatContext):
    cmd = chat.message.command
    if cmd == "/이벤트생성":
        create_event(chat)
    elif cmd in ("/이벤트참여", "/참여"):
        join_event(chat)
    elif cmd == "/이벤트삭제":
        delete_event(chat)
    elif cmd == "/이벤트멤버삭제":  # 추가됨
        remove_event_member(chat)
    elif cmd == "/이벤트탈퇴":      # 추가됨
        leave_event(chat)
    elif cmd == "/이벤트홍보":\
            promote_event(chat)# 추가됨
    elif cmd == "/내이벤트":
        show_my_events(chat)
    elif cmd in ("/이벤트목록", "/이벤트현황"):
        show_events_status(chat)
    elif cmd in ("/이벤트도움말"):
        show_event_help(chat)
