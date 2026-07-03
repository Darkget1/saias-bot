import argparse
import hashlib
import json
import os
import sqlite3


RUNE_DATA_FILE = os.path.join(os.path.dirname(__file__), "rune_info_data.json")
RUNE_COMMANDS = {"/룬", "/룬정보", "/룬검색", "/룬찾기"}
RUNE_FULL_COMMANDS = {"/룬전체", "/룬풀", "/룬풀출력"}
RUNE_LIST_COMMANDS = {"/룬목록", "/룬리스트", "/룬도움말"}
RUNE_LIST_KEYWORDS = {"목록", "리스트", "도움말", "사용법", "help", "?"}
RUNE_FULL_KEYWORDS = {"전체", "전부", "풀", "풀출력", "all", "full"}
RUNE_DEFAULT_MAX_RESULTS = 10
RUNE_REPLY_CHUNK_LIMIT = 3000
RUNE_SEARCH_ALIASES = {
    "공증": ["공격력"],
    "치피": ["치명타 피해"],
    "주피": ["적에게 주는 피해"],
    "직피": ["의 피해를 주", "피해를 주고", "피해를 주는", "피해를 준다"],
}
RUNE_GRADE_ORDER = {"신화": 1, "전설": 2, "영웅": 3, "희귀": 4, "고급": 5, "일반": 6}
RUNE_CATEGORY_ORDER = {"무기": 1, "방어구": 2, "엠블럼": 3}
RUNE_FILTER_VALUES = {
    "grade": set(RUNE_GRADE_ORDER.keys()),
    "category": set(RUNE_CATEGORY_ORDER.keys()),
    "tag": {"없음", "빛", "어둠", "용"},
}


def _compact_text(value):
    return "".join(str(value or "").split()).lower()


def _clean_query(query):
    return str(query or "").strip().strip("\"'“”‘’")


def _strip_full_keywords(query):
    full_output = False
    terms = []
    for token in str(query or "").split():
        normalized = _compact_text(token.strip("\"'“”‘’"))
        if normalized in RUNE_FULL_KEYWORDS:
            full_output = True
        else:
            terms.append(token)
    return _clean_query(" ".join(terms)), full_output


def _normalize_effect(value):
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _load_rune_source():
    with open(RUNE_DATA_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("runes", [])


def _source_fingerprint(runes):
    payload = json.dumps(runes, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def initialize_rune_db(db_file="iris.db"):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    create_rune_tables(cur)
    seed_rune_data(cur)
    conn.commit()
    return conn


def create_rune_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rune_entries (
            rune_id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade TEXT NOT NULL,
            category TEXT NOT NULL,
            tag TEXT NOT NULL,
            name TEXT NOT NULL UNIQUE,
            effect TEXT NOT NULL,
            source_row INTEGER,
            search_text TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rune_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def seed_rune_data(cur):
    runes = _load_rune_source()
    fingerprint = _source_fingerprint(runes)
    cur.execute("SELECT value FROM rune_meta WHERE key = 'seed_fingerprint'")
    row = cur.fetchone()
    cur.execute("SELECT COUNT(*) AS count FROM rune_entries")
    count_row = cur.fetchone()
    if row and row["value"] == fingerprint and count_row and count_row["count"] == len(runes):
        return

    cur.execute("DELETE FROM rune_entries")
    for rune in runes:
        grade = str(rune.get("grade", "")).strip()
        category = str(rune.get("category", "")).strip()
        tag = str(rune.get("tag", "")).strip() or "없음"
        name = str(rune.get("name", "")).strip()
        effect = _normalize_effect(rune.get("effect", ""))
        source_row = rune.get("source_row")
        search_text = _compact_text(" ".join([grade, category, tag, name, effect]))
        cur.execute(
            """
            INSERT INTO rune_entries
                (grade, category, tag, name, effect, source_row, search_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (grade, category, tag, name, effect, source_row, search_text),
        )

    cur.execute(
        "INSERT OR REPLACE INTO rune_meta (key, value) VALUES ('seed_fingerprint', ?)",
        (fingerprint,),
    )


def _target_fields_for_token(token):
    compact = _compact_text(token)
    targets = set()
    for field_name, values in RUNE_FILTER_VALUES.items():
        if compact in {_compact_text(value) for value in values}:
            targets.add(field_name)

    if targets:
        return targets | {"name"}
    return {"name", "grade", "category", "tag", "effect"}


def _search_groups(query):
    tokens = [_clean_query(token) for token in str(query or "").split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return []

    groups = []
    for raw in tokens:
        terms = []

        def add(term):
            term = str(term or "").strip()
            compact = _compact_text(term)
            for candidate in (term, compact):
                if candidate and candidate not in terms:
                    terms.append(candidate)

        add(raw)
        compact_raw = _compact_text(raw)
        for alias in RUNE_SEARCH_ALIASES.get(compact_raw, []):
            add(alias)
        groups.append({"raw": raw, "terms": terms, "fields": _target_fields_for_token(raw)})
    return groups


def _row_sort_key(row):
    return (
        RUNE_GRADE_ORDER.get(row["grade"], 99),
        RUNE_CATEGORY_ORDER.get(row["category"], 99),
        row["tag"],
        row["name"],
    )


def _score_field(field_name, value, term):
    text = str(value or "")
    compact = _compact_text(text)
    term_compact = _compact_text(term)
    if not term_compact:
        return 0

    if field_name in {"grade", "category", "tag"}:
        if term_compact == compact:
            return 90
        return 0
    if field_name == "name":
        if term_compact == compact:
            return 180
        if term_compact in compact:
            return 120
        return 0
    if term in text or term_compact in compact:
        return 20
    return 0


def _score_group(row, group):
    best_score = 0
    fields = {
        "name": row["name"],
        "grade": row["grade"],
        "category": row["category"],
        "tag": row["tag"],
        "effect": row["effect"],
    }
    for field_name in group["fields"]:
        for term in group["terms"]:
            best_score = max(best_score, _score_field(field_name, fields[field_name], term))
    return best_score


def _score_row(row, query, groups):
    query_compact = _compact_text(query)
    name_compact = _compact_text(row["name"])
    score = 0
    if query_compact and query_compact == name_compact:
        score += 1000
    if query_compact and query_compact in name_compact:
        score += 500

    for group in groups:
        group_score = _score_group(row, group)
        if group_score <= 0:
            return 0
        score += group_score
    return score


def _format_rune(row):
    tag_text = row["tag"] if row["tag"] and row["tag"] != "없음" else "태그 없음"
    effect_lines = [line.strip() for line in row["effect"].splitlines() if line.strip()]
    lines = [f"[{row['grade']} / {row['category']} / {tag_text}] {row['name']}"]
    lines.extend(f"- {line}" for line in effect_lines)
    return "\n".join(lines)


def _format_rune_help(cur):
    cur.execute(
        """
        SELECT grade, category, COUNT(*) AS count
        FROM rune_entries
        GROUP BY grade, category
        ORDER BY
            CASE grade WHEN '신화' THEN 1 WHEN '전설' THEN 2 ELSE 9 END,
            CASE category WHEN '무기' THEN 1 WHEN '방어구' THEN 2 WHEN '엠블럼' THEN 3 ELSE 9 END
        """
    )
    rows = cur.fetchall()
    counts = ", ".join(f"{row['grade']} {row['category']} {row['count']}개" for row in rows)
    return "\n".join(
        [
            "룬 정보 검색",
            "사용법: /룬 [이름/등급/분류/태그/효과]",
            "전체 출력: /룬전체 [검색어] 또는 /룬 [검색어] 전체",
            "예: /룬 죽음, /룬 공증, /룬 치피 방어구 용, /룬전체 치피",
            "줄임말: 공증=공격력, 치피=치명타 피해, 주피=적에게 주는 피해, 직피=n의 피해를 주는 효과",
            f"등록 데이터: {counts}",
        ]
    )


def search_rune_info(cur, query, max_results=RUNE_DEFAULT_MAX_RESULTS):
    query = _clean_query(query)
    groups = _search_groups(query)
    if not groups:
        return _format_rune_help(cur)

    cur.execute(
        """
        SELECT *
        FROM rune_entries
        ORDER BY
            CASE grade WHEN '신화' THEN 1 WHEN '전설' THEN 2 ELSE 9 END,
            CASE category WHEN '무기' THEN 1 WHEN '방어구' THEN 2 WHEN '엠블럼' THEN 3 ELSE 9 END,
            rune_id
        """
    )
    scored = []
    for row in cur.fetchall():
        score = _score_row(row, query, groups)
        if score > 0:
            scored.append((score, row))

    if not scored:
        return (
            f"'{query}' 룬 정보를 찾지 못했습니다.\n"
            "예: /룬 죽음, /룬 공증, /룬 치피 방어구 용, /룬 주피"
        )

    scored.sort(key=lambda item: (-item[0], _row_sort_key(item[1])))
    rows = [row for _, row in scored]
    full_output = max_results is None or max_results <= 0
    visible = rows if full_output else rows[:max_results]
    lines = [f"룬 정보 검색: {query}", f"검색 결과: {len(rows)}건"]
    if full_output and len(rows) > 1:
        lines.append("전체 결과를 출력합니다.")
    elif len(rows) > max_results:
        lines.append(f"상위 {max_results}건만 출력합니다. 이름/분류/태그를 더 붙이면 좁혀집니다.")
    lines.append("────────")
    for row in visible:
        lines.append(_format_rune(row))
        lines.append("")
    return "\n".join(lines).strip()


def split_rune_reply(message, limit=RUNE_REPLY_CHUNK_LIMIT):
    message = str(message or "")
    if len(message) <= limit:
        return [message]

    chunks = []
    current = ""
    for block in message.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= limit:
            current = block
            continue
        lines = block.splitlines()
        current = ""
        for line in lines:
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = line
    if current:
        chunks.append(current)

    total = len(chunks)
    return [f"{chunk}\n\n({idx}/{total})" for idx, chunk in enumerate(chunks, 1)]


def _message_attr_text(message):
    for attr_name in ("text", "msg", "content", "raw", "body"):
        value = getattr(message, attr_name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _rune_command_from_chat(chat):
    message = chat.message
    cmd = str(getattr(message, "command", "") or "").strip()
    param = str(getattr(message, "param", "") or "").strip()

    if not cmd:
        text = _message_attr_text(message)
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].strip()
            if not param and len(parts) > 1:
                param = parts[1].strip()

    full_output = cmd in RUNE_FULL_COMMANDS

    if (
        cmd.startswith("/룬")
        and cmd not in RUNE_COMMANDS
        and cmd not in RUNE_FULL_COMMANDS
        and cmd not in RUNE_LIST_COMMANDS
    ):
        suffix = cmd.removeprefix("/룬").strip()
        if suffix in RUNE_LIST_KEYWORDS:
            cmd = "/룬목록"
        elif suffix in RUNE_FULL_KEYWORDS:
            cmd = "/룬전체"
            full_output = True
        elif suffix:
            param = f"{suffix} {param}".strip()
            cmd = "/룬"

    param, keyword_full_output = _strip_full_keywords(param)
    return cmd, param, full_output or keyword_full_output


def handle_rune_commands(chat, get_db_conn, db_lock):
    cmd, query, full_output = _rune_command_from_chat(chat)
    if cmd not in RUNE_COMMANDS and cmd not in RUNE_FULL_COMMANDS and cmd not in RUNE_LIST_COMMANDS:
        return False

    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        if cmd in RUNE_LIST_COMMANDS or not query or query.lower() in RUNE_LIST_KEYWORDS:
            message = _format_rune_help(cur)
        else:
            message = search_rune_info(cur, query, max_results=None if full_output else RUNE_DEFAULT_MAX_RESULTS)
        conn.close()

    for reply in split_rune_reply(message):
        chat.reply(reply)
    return True


def main():
    parser = argparse.ArgumentParser(description="룬 정보 DB 초기화 및 검색")
    parser.add_argument("query", nargs="*", help="검색어. 예: 죽음, 공증, 치피, 주피, 직피")
    parser.add_argument("--db", default="iris.db", help="SQLite DB 경로. 기본값: iris.db")
    parser.add_argument("--all", "--full", action="store_true", dest="full_output", help="검색 결과 전체 출력")
    args = parser.parse_args()

    conn = initialize_rune_db(args.db)
    cur = conn.cursor()
    query = " ".join(args.query).strip()
    if query:
        query, keyword_full_output = _strip_full_keywords(query)
        print(search_rune_info(cur, query, max_results=None if args.full_output or keyword_full_output else RUNE_DEFAULT_MAX_RESULTS))
    else:
        print(_format_rune_help(cur))
    conn.close()


if __name__ == "__main__":
    main()
