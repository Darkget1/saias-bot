# bots/party.py
from __future__ import annotations

import threading
from datetime import datetime, date
from typing import Dict, Any, Optional

from iris import ChatContext

# ─────────────────────────────
# 전역 상태 (room_id -> { owner_id: party })
# ─────────────────────────────

PARTY_STATE: Dict[int, Dict[int, Dict[str, Any]]] = {}
PARTY_LOCK = threading.RLock()


# 마지막으로 파티 상태를 사용한 "날짜"
# - 날짜가 바뀌면(자정 지나면) PARTY_STATE 를 전부 초기화한다.
_PARTY_STATE_DATE: Optional[date] = None


def _next_party_id(room_id: int) -> int:
    """
    해당 방(room_id)에서 사용 중인 파티 번호를 확인하고,
    1번부터 시작하여 비어있는 가장 낮은 번호를 반환합니다.
    """
    room_parties = PARTY_STATE.get(room_id, {})

    # 현재 이 방에 있는 파티들의 ID만 모음
    used_ids = {p.get("party_id", 0) for p in room_parties.values()}

    # 1부터 숫자를 키워가며 사용 중이지 않은 번호를 찾음
    pid = 1
    while pid in used_ids:
        pid += 1

    return pid


def _truncate(text: str, max_len: int) -> str:
    """카톡 말풍선 폭을 고려해 너무 길면 잘라준다."""
    text = str(text or "")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _get_room_id(chat: ChatContext) -> int:
    """방 ID 가져오기 (iris 기본 room.id 사용)."""
    return chat.room.id


def _ensure_today_state():
    """
    날짜가 바뀌었으면(자정 이후) 모든 파티 상태를 초기화한다.
    - 서버 시간 기준으로 동작.
    """
    global PARTY_STATE, _PARTY_STATE_DATE
    today = datetime.now().date()

    if _PARTY_STATE_DATE is None:
        _PARTY_STATE_DATE = today
        return

    if _PARTY_STATE_DATE != today:
        PARTY_STATE.clear()
        _PARTY_STATE_DATE = today


# ─────────────────────────────
# 내부 유틸
# ─────────────────────────────

def _get_user_name(sender) -> str:
    """
    sender.name 이 None 이거나 없는 경우를 대비해서
    nickname, nick, id 등으로 안전하게 이름을 만들어준다.
    """
    name = (
            getattr(sender, "name", None)
            or getattr(sender, "nickname", None)
            or getattr(sender, "nick", None)
    )

    if not name:
        uid = getattr(sender, "id", "?")
        name = f"User{uid}"
    return str(name)


def _parse_main_flag(token: str) -> Optional[bool]:
    """
    '본', '본캐', 'main', 'm' → True
    '부', '부캐', 'sub', 'alt', 's' → False
    그 외 → None
    """
    if not token:
        return None
    t = token.strip().lower()
    if t in ("본", "본캐", "m", "main"):
        return True
    if t in ("부", "부캐", "s", "sub", "alt"):
        return False
    return None


def _extract_cls_from_tokens(tokens: list[str]) -> Optional[str]:
    """
    /추가 명령 등에서 직업만 필요할 때 사용.
    본/부 토큰은 무시하고, 나머지 첫 토큰을 직업으로 본다.
    """
    for t in tokens:
        if _parse_main_flag(t) is None:
            return t
    return None


def _extract_cls_and_main(tokens: list[str]) -> tuple[Optional[str], Optional[bool]]:
    """
    토큰 리스트에서 직업과 본/부 플래그를 같이 추출한다.
    """
    cls: Optional[str] = None
    main_flag: Optional[bool] = None

    for t in tokens:
        flag = _parse_main_flag(t)
        if flag is not None:
            main_flag = flag
        elif cls is None:
            cls = t

    return cls, main_flag


def _parse_party_create_args(param: str) -> tuple[str, Optional[str]]:
    """
    /파티, /레이드파티 에서 사용하는 인자 파싱.
    """
    param = (param or "").strip()
    if not param:
        return "파티", None

    tokens = param.split()
    if not tokens:
        return "파티", None

    # 맨 뒤에서부터 본/부 토큰은 제거
    while tokens and _parse_main_flag(tokens[-1]) is not None:
        tokens.pop()

    if not tokens:
        return "파티", None

    if len(tokens) >= 2:
        cls = tokens[-1]
        title_tokens = tokens[:-1]
    else:
        cls = None
        title_tokens = tokens

    title = " ".join(title_tokens) if title_tokens else "파티"
    return title, cls


def _format_party_table(party: Dict[str, Any]) -> str:
    """
    파티 정보를 카톡에서 보기 좋게 출력하는 포맷(22자 기준).

    [변경 사항]
    출력 순서: No | 본/부 | 직업 | 이름
    """
    members = party.get("members", [])
    max_members = party.get("max_members", len(members))
    party_id = party.get("party_id", "?")
    title = party.get("title") or "파티"
    owner_name = party.get("owner_name") or "-"

    is_raid = party.get("is_raid")
    kind = "레이드 파티" if is_raid else "일반 파티"

    lines: list[str] = []

    # ── 헤더 (각 줄 22자 이내) ───────────────────
    lines.append(_truncate(f"🎮 {kind} #{party_id}", 22))
    lines.append(f"제목: {_truncate(title, 18)}")
    lines.append(f"파티장: {_truncate(owner_name, 17)}")
    lines.append(f"인원: {len(members)}/{max_members}")
    lines.append("")  # 빈 줄

    # ── 멤버 목록 ───────────────────────────────
    lines.append("👥 멤버 목록")

    if not members:
        lines.append("(아직 멤버 없음)")
        return "\n".join(lines)

    # 컬럼 헤더: No | 본/부 | 직업 | 이름
    lines.append("No | 본/부 | 직업 | 이름")

    for idx, m in enumerate(members, start=1):
        raw_name = m.get("name") or f"User{m.get('id', '?')}"
        raw_cls = m.get("cls") or "-"

        # 공백 제거
        clean_name = str(raw_name).replace(" ", "")
        clean_cls = str(raw_cls).replace(" ", "")

        # is_main 값 우선, 없으면 1번=본케, 나머지=부케
        is_main_flag = m.get("is_main")
        if is_main_flag is None:
            is_main_flag = (idx == 1)

        role_str = "본케" if is_main_flag else "부케"

        # 포맷팅 (22자 제한 고려)
        # 1) 번호+본/부(합쳐서 6~7자) | 직업(4자) | 이름(나머지)
        # 예: 1)본케|전사  |홍길동

        role_fixed = role_str[:2]  # "본케" (2글자)
        cls_fixed = clean_cls[:4].ljust(0)  # 직업 4칸 확보

        # 이름은 뒷부분에 배치하여 자연스럽게 잘리도록 함
        line = f"{idx}) {role_fixed} | {cls_fixed} | {clean_name}"
        lines.append(_truncate(line, 22))

    return "\n".join(lines)


def _find_party_by_owner_name(
        room_parties: Dict[int, Dict[str, Any]], name: str
) -> Optional[int]:
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


def _join_help_lines() -> list[str]:
    """22자 기준으로 자른 참여 안내 문구."""
    return [
        "",
        "====참여 방법====",
        "/파티참여 ID 직업 본/부",
        "예) /참여 3 도적 본 ",
    ]


# ─────────────────────────────
# 외부에서 호출할 명령 함수들
# ─────────────────────────────

def create_party(chat: ChatContext):
    """ /파티 명령 처리: 기본 4인 파티."""
    _ensure_today_state()

    room_id = _get_room_id(chat)
    param = getattr(chat.message, "param", "") or ""

    title, cls = _parse_party_create_args(param)

    owner_id = chat.sender.id
    owner_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.setdefault(room_id, {})

        if owner_id in room_parties:
            party = room_parties[owner_id]
            table = _format_party_table(party)
            msg_lines = [
                            "이미 만든 파티가 있어요.",
                            "",
                            table,
                        ] + _join_help_lines()
            chat.reply("\n".join(msg_lines))
            return

        party_id = _next_party_id(room_id)

        creator = {
            "id": owner_id,
            "name": owner_name,
            "cls": cls,
            "is_main": True,  # 파티장 기본 본케
        }

        room_parties[owner_id] = {
            "party_id": party_id,
            "title": title,
            "max_members": 4,
            "members": [creator],
            "owner_id": owner_id,
            "owner_name": owner_name,
            "is_raid": False,
        }

        table = _format_party_table(room_parties[owner_id])

        msg_lines = [
                        "🎮 새 파티를 만들었어요!",
                        "",
                        table,
                    ] + _join_help_lines()
        chat.reply("\n".join(msg_lines))


def create_raid_party(chat: ChatContext):
    """ /레이드파티 명령 처리: 8인 레이드 파티."""
    _ensure_today_state()

    room_id = _get_room_id(chat)
    param = getattr(chat.message, "param", "") or ""

    title, cls = _parse_party_create_args(param)
    if title == "파티":
        title = "레이드 파티"

    owner_id = chat.sender.id
    owner_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.setdefault(room_id, {})

        if owner_id in room_parties:
            party = room_parties[owner_id]
            table = _format_party_table(party)
            msg_lines = [
                            "이미 만든 파티가 있어요.",
                            "",
                            table,
                        ] + _join_help_lines()
            chat.reply("\n".join(msg_lines))
            return

        party_id = _next_party_id(room_id)

        creator = {
            "id": owner_id,
            "name": owner_name,
            "cls": cls,
            "is_main": True,
        }

        room_parties[owner_id] = {
            "party_id": party_id,
            "title": title,
            "max_members": 8,
            "members": [creator],
            "owner_id": owner_id,
            "owner_name": owner_name,
            "is_raid": True,
        }

        table = _format_party_table(room_parties[owner_id])

        msg_lines = [
                        "⚔️ 레이드 파티를 만들었어요!",
                        "",
                        table,
                    ] + _join_help_lines()
        chat.reply("\n".join(msg_lines))


def delete_party(chat: ChatContext):
    """ /파티삭제 명령 처리 (내가 파티장인 파티를 모두 삭제)."""
    _ensure_today_state()

    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("삭제할 파티가 없어요.")
            return

        owner_parties = [
            (oid, p) for oid, p in room_parties.items() if oid == user_id
        ]

        if not owner_parties:
            chat.reply("당신이 만든 파티가 없어요.")
            return

        for owner_id, _party in owner_parties:
            room_parties.pop(owner_id, None)

        if not room_parties:
            PARTY_STATE.pop(room_id, None)

        chat.reply("🛑 당신이 만든 파티를 삭제했어요.")


def add_member_by_master(chat: ChatContext):
    """
    /추가 명령 처리 (파티장 전용)
    형식: /추가 닉네임 [직업] [본/부]
    """
    _ensure_today_state()

    room_id = _get_room_id(chat)
    owner_id = chat.sender.id
    param = (getattr(chat.message, "param", "") or "").strip()

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties or owner_id not in room_parties:
            chat.reply("먼저 `/파티 제목` 으로 파티를 만들어 주세요.")
            return

        party = room_parties[owner_id]

        if not param:
            chat.reply("사용법: `/추가 닉네임 [직업] [본/부]`")
            return

        tokens = param.split()
        name = tokens[0]

        # ───────────────────────────────────────────────────────────
        # [수정] 기존 _extract_cls_from_tokens 대신
        # _extract_cls_and_main을 사용하여 직업과 본/부 설정을 모두 파싱
        # ───────────────────────────────────────────────────────────
        cls = None
        is_main = None

        if len(tokens) >= 2:
            cls, is_main = _extract_cls_and_main(tokens[1:])

        if len(party["members"]) >= party["max_members"]:
            chat.reply(
                f"⚠️ 이미 인원이 가득 찼어요! "
                f"({party['max_members']}/{party['max_members']})"
            )
            return

        new_member = {
            "id": 0,  # 임의 인원 (실제 유저 ID 아님)
            "name": name,
            "cls": cls,
        }

        # [수정] 파싱된 본/부 설정이 있다면 적용
        if is_main is not None:
            new_member["is_main"] = is_main

        party["members"].append(new_member)

        table = _format_party_table(party)
        chat.reply(f"✅ `{name}` 님을 추가했어요.\n\n{table}")

        if len(party["members"]) == party["max_members"]:
            full_msg = (
                    f"🎉 {'레이드 파티' if party.get('is_raid') else '파티'} "
                    f"인원이 모두 모였습니다!\n"
                    f"({party['max_members']}/{party['max_members']})\n\n"
                    + table
            )
            chat.reply(full_msg)


def kick_member(chat: ChatContext):
    """
    /파티추방 [번호]
    - 파티장만 사용 가능.
    - 1번(파티장)은 추방 불가.
    """
    _ensure_today_state()

    room_id = _get_room_id(chat)
    owner_id = chat.sender.id
    param = (getattr(chat.message, "param", "") or "").strip()

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties or owner_id not in room_parties:
            chat.reply("추방할 파티가 없거나, 파티장이 아니에요.")
            return

        party = room_parties[owner_id]

        if not param.isdigit():
            chat.reply("사용법: `/파티추방 번호` (예: /파티추방 2)")
            return

        target_idx = int(param)

        # 1번(파티장) 보호 로직
        if target_idx == 1:
            chat.reply("⚠️ 파티장은 추방할 수 없습니다. 파티를 없애려면 `/파티삭제`를 해주세요.")
            return

        # 인덱스 유효성 검사 (화면엔 1부터 표시되므로 실제 인덱스는 -1)
        real_idx = target_idx - 1
        if real_idx < 0 or real_idx >= len(party["members"]):
            chat.reply(f"{target_idx}번 멤버가 존재하지 않습니다.")
            return

        # 멤버 삭제
        removed = party["members"].pop(real_idx)

        table = _format_party_table(party)
        chat.reply(f"🚫 `{removed['name']}` 님을 파티에서 추방했어요.\n\n{table}")


def join_party(chat: ChatContext):
    """ /참가, /참여 명령 처리 """
    _ensure_today_state()

    room_id = _get_room_id(chat)
    raw_param = (getattr(chat.message, "param", "") or "").strip()
    tokens = raw_param.split()

    user_id = chat.sender.id
    user_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("모집 중인 파티가 없어요.")
            return

        target_owner_id: Optional[int] = None
        party: Optional[Dict[str, Any]] = None
        cls: Optional[str] = None
        is_main: Optional[bool] = None

        # ──────────────────────
        # 1) 파티 찾기 및 파라미터 파싱
        # ──────────────────────
        if tokens:
            # 1-1) 첫 토큰이 숫자면 → 파티 ID로 찾기
            if tokens[0].isdigit():
                target_party_id = int(tokens[0])
                for oid, p in room_parties.items():
                    if p.get("party_id") == target_party_id:
                        target_owner_id = oid
                        party = p
                        break
                if target_owner_id is None:
                    msg_lines = [
                                    "해당 ID의 파티가 없어요.",
                                    "현재 파티 목록은 `/파티현황` 으로",
                                    "확인해 주세요.",
                                ] + _join_help_lines()
                    chat.reply("\n".join(msg_lines))
                    return

                cls, is_main = _extract_cls_and_main(tokens[1:])

            else:
                # 1-2) 첫 토큰이 숫자가 아닐 때
                if len(room_parties) == 1:
                    target_owner_id = next(iter(room_parties.keys()))
                    party = room_parties[target_owner_id]
                    cls, is_main = _extract_cls_and_main(tokens)
                else:
                    target_owner_id = _find_party_by_owner_name(
                        room_parties, tokens[0]
                    )
                    if target_owner_id is None:
                        msg_lines = [
                                        "파티가 여러 개 있어요.",
                                        "ID로 참가하는 걸 권장해요.",
                                    ] + _join_help_lines()
                        chat.reply("\n".join(msg_lines))
                        return
                    party = room_parties.get(target_owner_id)
                    cls, is_main = _extract_cls_and_main(tokens[1:])
        else:
            # 1-3) 파라미터가 없을 때 (파티가 1개면 자동 선택)
            if len(room_parties) == 1:
                target_owner_id = next(iter(room_parties.keys()))
                party = room_parties[target_owner_id]
            else:
                lines = ["여러 파티가 있어요:"]
                for p_owner_id, p in room_parties.items():
                    kind = "레이드" if p.get("is_raid") else "일반"
                    lines.append(
                        f"- ID:{p.get('party_id', '?')} "
                        f"[{kind}] {p['owner_name']}"
                    )
                lines += _join_help_lines()
                chat.reply("\n".join(lines))
                return

        if not party:
            chat.reply("선택한 파티가 더 이상 없어요.")
            return

        # ──────────────────────
        # 2) 이미 이 파티에 있는 경우 → 직업/본부 수정
        # ──────────────────────
        existing_index: Optional[int] = None
        for i, m in enumerate(party["members"]):
            if m["id"] == user_id:
                existing_index = i
                break

        if existing_index is not None:
            member = party["members"][existing_index]
            old_cls = member.get("cls")
            old_is_main = member.get("is_main")

            if cls:
                member["cls"] = cls

            if is_main is not None:
                member["is_main"] = is_main

            # 수정 시점에서도 값이 없으면 True(본캐)로 간주
            is_main_flag = member.get("is_main", True)

            my_role_label = "본케" if is_main_flag else "부케"
            table = _format_party_table(party)

            header = ""
            if cls and cls != old_cls:
                header = f"✅ 직업을 {cls} 로 수정했어요."
            elif is_main is not None and is_main != old_is_main:
                header = f"✅ 포지션을 {my_role_label} 로 수정했어요."
            elif cls or is_main is not None:
                header = "이미 같은 정보예요.\n현재 상태를 다시 보여줄게요."
            else:
                header = "현재 내 정보를 다시 보여줄게요."

            msg_lines = [
                header,
                "",
                f"내 포지션: {my_role_label}",
                "",
                table,
            ]
            chat.reply("\n".join(msg_lines))
            return

        # ──────────────────────
        # 3) 새로 참가하는 경우 (수정된 로직)
        # ──────────────────────
        if len(party["members"]) >= party["max_members"]:
            chat.reply(
                f"⚠️ 이미 인원이 가득 찼어요! "
                f"({party['max_members']}/{party['max_members']})"
            )
            return

        member = {
            "id": user_id,
            "name": user_name,
            "cls": cls,
        }

        # [수정됨] is_main이 입력되지 않았다면(None) -> 기본값 True(본캐) 설정
        if is_main is not None:
            member["is_main"] = is_main
        else:
            member["is_main"] = True

        party["members"].append(member)

        # 표시용 변수 설정
        is_main_flag = member["is_main"]
        my_role_label = "본케" if is_main_flag else "부케"
        kind_str = "레이드 파티" if party.get("is_raid") else "파티"
        table = _format_party_table(party)

        msg_lines = [
            f"✅ {kind_str}에 참가했어요.",
            f"내 직업: {cls or '-'}",
            f"내 포지션: {my_role_label}",
            "",
            table,
        ]
        chat.reply("\n".join(msg_lines))

        if len(party["members"]) == party["max_members"]:
            chat.reply(
                f"🎉 {kind_str} 인원이 모두 모였어요!\n"
                f"({party['max_members']}/{party['max_members']})\n\n"
                + table
            )


def show_party_status(chat: ChatContext):
    """ /파티현황 명령 처리."""
    _ensure_today_state()

    room_id = _get_room_id(chat)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("현재 모집 중인 파티가 없어요.")
            return

        lines: list[str] = ["📋 현재 파티 현황"]

        for idx, (_owner_id, party) in enumerate(
                room_parties.items(), start=1
        ):
            safe_names = []
            for m in party["members"]:
                n = m.get("name") or f"User{m.get('id', '?')}"
                safe_names.append(str(n))
            members_str = ", ".join(safe_names)

            kind = "레이드" if party.get("is_raid") else "일반"

            lines.append("────────────────")
            lines.append(f"#{idx} [{kind}]")
            lines.append(f"ID:{party.get('party_id', '?')}")
            lines.append(f"장:{_truncate(party['owner_name'], 10)}")
            lines.append(f"제목:{_truncate(party['title'], 12)}")
            lines.append(
                f"인원:{len(party['members'])}/{party['max_members']}"
            )
            lines.append(f"멤버:{_truncate(members_str, 14)}")

        lines += _join_help_lines()
        chat.reply("\n".join(lines))


def leave_party(chat: ChatContext):
    """ /파티취소 명령 처리 (본인이 속한 모든 파티에서 나가기)."""
    _ensure_today_state()

    room_id = _get_room_id(chat)
    user_id = chat.sender.id

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("모집 중인 파티가 없어요.")
            return

        joined: list[tuple[int, Dict[str, Any]]] = []
        for owner_id, party in list(room_parties.items()):
            if any(m["id"] == user_id for m in party["members"]):
                joined.append((owner_id, party))

        if not joined:
            chat.reply("참가 중인 파티가 없어요.")
            return

        cancelled_titles = []
        left_titles = []

        for owner_id, party in joined:
            if party["owner_id"] == user_id:
                room_parties.pop(owner_id, None)
                cancelled_titles.append(party["title"])
            else:
                party["members"] = [
                    m for m in party["members"] if m["id"] != user_id
                ]
                if not party["members"]:
                    room_parties.pop(owner_id, None)
                    cancelled_titles.append(party["title"])
                else:
                    left_titles.append(party["title"])

        if not room_parties:
            PARTY_STATE.pop(room_id, None)

        msg_lines = []
        if left_titles:
            msg_lines.append("나간 파티:")
            msg_lines += [f"- {t}" for t in left_titles]
        if cancelled_titles:
            msg_lines.append("삭제된 파티:")
            msg_lines += [f"- {t}" for t in cancelled_titles]
        if not msg_lines:
            msg_lines.append("변경된 파티가 없어요.")

        chat.reply("\n".join(msg_lines))


def promote_party(chat: ChatContext):
    """
    /파티홍보 명령 처리
    - 파티장 + 파티원 모두 사용 가능
    """
    _ensure_today_state()

    room_id = _get_room_id(chat)
    user_id = chat.sender.id
    user_name = _get_user_name(chat.sender)

    with PARTY_LOCK:
        room_parties = PARTY_STATE.get(room_id)
        if not room_parties:
            chat.reply("먼저 `/파티 제목` 으로 파티를 만들어 주세요.")
            return

        party = None

        # 1) 내가 파티장인 경우 → 내 파티 우선
        if user_id in room_parties:
            party = room_parties[user_id]
        else:
            # 2) 파티장은 아니지만, 멤버로 들어가 있는 파티 찾기
            for _owner_id, p in room_parties.items():
                if any(m.get("id") == user_id for m in p.get("members", [])):
                    party = p
                    break

        if not party:
            chat.reply("현재 홍보할 수 있는 파티가 없어요.\n(파티에 먼저 참가해 주세요)")
            return

        table = _format_party_table(party)

        # 파티장이 아닌 파티원이 홍보한 경우, 누가 요청했는지 표시
        if party.get("owner_id") != user_id:
            header = f"📣 파티 홍보! (요청자: {_truncate(user_name, 10)})"
        else:
            header = "📣 파티 홍보!"

        msg_lines = [
            header,
            "",
            table,
        ] + _join_help_lines()

        chat.reply("\n".join(msg_lines))


def show_help(chat: ChatContext):
    """ /파티도움말 명령 처리 """
    lines = [
        "📚 [파티 봇 도움말]",
        "",
        "✅ 파티 생성/관리",
        "• /파티 [제목] [직업] [본/부] : 4인 파티 생성",
        "• /레이드파티 [제목] [직업] [본/부] : 8인 파티 생성",
        "• /파티삭제 : 내가 만든 파티 삭제",
        "• /파티홍보 : 현재 파티 정보 띄우기",
        "",
        "✅ 참여/탈퇴",
        "• /파티참여 [번호] [직업] [본/부] : 파티 참여",
        "• /파티탈퇴 : 참여 중인 파티 나가기",
        "",
        "✅ 파티장 전용",
        "• /파티멤버추가 [이름] [직업] [본/부] : 멤버 강제 추가",
        "• /파티추방 [번호] : 멤버 내보내기",
        "",
        "✅ 조회",
        "• /파티목록 : 전체 파티 목록 보기",
        "• /파티도움말 : 명령어 목록 보기"
    ]
    chat.reply("\n".join(lines))


def handle_party_command(chat: ChatContext):
    """
    메인 봇 명령어 라우팅
    """
    _ensure_today_state()

    cmd = chat.message.command

    if cmd == "/파티":
        create_party(chat)
    elif cmd == "/레이드파티":
        create_raid_party(chat)
    elif cmd in ("/파티참가", "/파티참여", "/참가", "/참여"):
        join_party(chat)
    elif cmd in ("/파티목록", "/파티현황"):
        show_party_status(chat)
    elif cmd in ("/파티탈퇴", "/파티취소"):
        leave_party(chat)
    elif cmd == "/파티삭제":
        delete_party(chat)
    elif cmd == "/파티멤버추가":
        add_member_by_master(chat)
    elif cmd == "/파티홍보":
        promote_party(chat)
    elif cmd == "/파티추방":
        kick_member(chat)
    elif cmd in ("/파티도움말", "/파티명령어"):
        show_help(chat)