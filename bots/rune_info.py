import argparse
import hashlib
import json
import os
import sqlite3


RUNE_DATA_FILE = os.path.join(os.path.dirname(__file__), "rune_info_data.json")
RUNE_COMMANDS = {"/룬", "/룬정보", "/룬검색", "/룬찾기"}
RUNE_LIST_COMMANDS = {"/룬목록", "/룬리스트", "/룬도움말"}
RUNE_LIST_KEYWORDS = {"목록", "리스트", "도움말", "사용법", "help", "?"}
RUNE_SEARCH_ALIASES = {
    "공증": ["공격력"],
    "치피": ["치명타 피해"],
    "주피": ["적에게 주는 피해"],
    "직피": ["의 피해를 주", "피해를 주고", "피해를 주는", "피해를 준다"],
}
RUNE_GRADE_ORDER = {"신화": 1, "전설": 2, "영웅": 3, "희귀": 4, "고급": 5, "일반": 6}
RUNE_CATEGORY_ORDER = {"무기": 1, "방어구": 2, "엠블럼": 3}


def _compact_text(value):
    return "".join(str(value or "").split()).lower()


def _clean_query(query):
    return str(query or "").strip().strip("\"'“”‘’")


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


def _search_terms(query):
    raw = _clean_query(query)
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
    return terms


def _row_sort_key(row):
    return (
        RUNE_GRADE_ORDER.get(row["grade"], 99),
        RUNE_CATEGORY_ORDER.get(row["category"], 99),
        row["tag"],
        row["name"],
    )


def _score_row(row, query, terms):
    query_compact = _compact_text(query)
    name_compact = _compact_text(row["name"])
    score = 0
    if query_compact and query_compact == name_compact:
        score += 1000
    if query_compact and query_compact in name_compact:
        score += 500

    fields = {
        "name": row["name"],
        "grade": row["grade"],
        "category": row["category"],
        "tag": row["tag"],
        "effect": row["effect"],
    }
    for term in terms:
        term_compact = _compact_text(term)
        if not term_compact:
            continue
        for field_name, value in fields.items():
            text = str(value or "")
            compact = _compact_text(text)
            if term in text or term_compact in compact:
                if field_name == "name":
                    score += 120
                elif field_name in {"grade", "category", "tag"}:
                    score += 60
                else:
                    score += 20
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
            "예: /룬 죽음, /룬 무기, /룬 공증, /룬 치피, /룬 주피, /룬 직피",
            "줄임말: 공증=공격력, 치피=치명타 피해, 주피=적에게 주는 피해, 직피=n의 피해를 주는 효과",
            f"등록 데이터: {counts}",
        ]
    )


def search_rune_info(cur, query, max_results=5):
    query = _clean_query(query)
    terms = _search_terms(query)
    if not terms:
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
        score = _score_row(row, query, terms)
        if score > 0:
            scored.append((score, row))

    if not scored:
        return (
            f"'{query}' 룬 정보를 찾지 못했습니다.\n"
            "예: /룬 죽음, /룬 공증, /룬 치피, /룬 주피, /룬 직피"
        )

    scored.sort(key=lambda item: (-item[0], _row_sort_key(item[1])))
    rows = [row for _, row in scored]
    visible = rows[:max_results]
    lines = [f"룬 정보 검색: {query}", f"검색 결과: {len(rows)}건"]
    if len(rows) > max_results:
        lines.append(f"상위 {max_results}건만 출력합니다. 이름/분류/태그를 더 붙이면 좁혀집니다.")
    lines.append("────────")
    for row in visible:
        lines.append(_format_rune(row))
        lines.append("")
    return "\n".join(lines).strip()


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

    if cmd.startswith("/룬") and cmd not in RUNE_COMMANDS and cmd not in RUNE_LIST_COMMANDS:
        suffix = cmd.removeprefix("/룬").strip()
        if suffix in RUNE_LIST_KEYWORDS:
            cmd = "/룬목록"
        elif suffix:
            param = f"{suffix} {param}".strip()
            cmd = "/룬"

    return cmd, _clean_query(param)


def handle_rune_commands(chat, get_db_conn, db_lock):
    cmd, query = _rune_command_from_chat(chat)
    if cmd not in RUNE_COMMANDS and cmd not in RUNE_LIST_COMMANDS:
        return False

    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        if cmd in RUNE_LIST_COMMANDS or not query or query.lower() in RUNE_LIST_KEYWORDS:
            message = _format_rune_help(cur)
        else:
            message = search_rune_info(cur, query)
        conn.close()

    chat.reply(message)
    return True


def main():
    parser = argparse.ArgumentParser(description="룬 정보 DB 초기화 및 검색")
    parser.add_argument("query", nargs="*", help="검색어. 예: 죽음, 공증, 치피, 주피, 직피")
    parser.add_argument("--db", default="iris.db", help="SQLite DB 경로. 기본값: iris.db")
    args = parser.parse_args()

    conn = initialize_rune_db(args.db)
    cur = conn.cursor()
    query = " ".join(args.query).strip()
    if query:
        print(search_rune_info(cur, query))
    else:
        print(_format_rune_help(cur))
    conn.close()


if __name__ == "__main__":
    main()
