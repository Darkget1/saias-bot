BARTER_SOURCE_NOTE = "이멘마하 요리(제작대 Lv.6)"

BARTER_COMMANDS = {"/물교", "/물교정보", "/물교검색", "/물교찾기", "/물교정보찾기"}
BARTER_LIST_COMMANDS = {"/물교목록"}

BARTER_RECIPES = [
    {
        "trader": "멜렌",
        "dish_name": "오트밀 영양죽",
        "dish_quantity": 4,
        "reward_item": "특급 가죽*1",
        "weekly_limit": "주2회",
        "materials": [
            ("재료", "오트밀", 20),
            ("재료", "물에 불린 콩", 16),
            ("재료", "사과", 32),
            ("재료", "당근", 20),
            ("재료", "소금", 8),
            ("가공 재료", "귀리", 210),
            ("가공 재료", "콩", 120),
            ("가공 재료", "물이 든 병", 12),
        ],
    },
    {
        "trader": "멜렌",
        "dish_name": "가든 샐러드",
        "dish_quantity": 4,
        "reward_item": "특급 목재*1",
        "weekly_limit": "주2회",
        "materials": [
            ("재료", "양배추", 32),
            ("재료", "파스닙", 40),
            ("재료", "샐러리", 8),
            ("재료", "마요네즈", 16),
            ("재료", "허브", 24),
            ("가공 재료", "달걀", 60),
            ("가공 재료", "식용유", 12),
        ],
    },
    {
        "trader": "엘리노아",
        "dish_name": "달콤 쌉쌀 푸딩",
        "dish_quantity": 4,
        "reward_item": "특급 옷감*1",
        "weekly_limit": "주2회",
        "materials": [
            ("재료", "헤이즐넛", 40),
            ("재료", "두유", 24),
            ("재료", "말린 찻잎", 16),
            ("재료", "딸기", 32),
            ("재료", "설탕", 28),
            ("가공 재료", "콩", 150),
            ("가공 재료", "물이 든 병", 39),
            ("가공 재료", "소금", 16),
            ("가공 재료", "식용유", 8),
            ("가공 재료", "찻잎", 180),
        ],
    },
    {
        "trader": "엘리노아",
        "dish_name": "넛츠 초코 비스킷",
        "dish_quantity": 4,
        "reward_item": "특급 실크*1",
        "weekly_limit": "주2회",
        "materials": [
            ("재료", "헤이즐넛", 40),
            ("재료", "밀가루", 32),
            ("재료", "조각 초콜릿", 20),
            ("재료", "달걀", 16),
            ("재료", "생크림", 24),
            ("가공 재료", "밀", 45),
            ("가공 재료", "우유", 96),
            ("가공 재료", "달걀", 48),
            ("가공 재료", "설탕", 16),
        ],
    },
    {
        "trader": "오슬라",
        "dish_name": "매콤 파프리카 스튜",
        "dish_quantity": 4,
        "reward_item": "백금 광괴*1",
        "weekly_limit": "주2회",
        "materials": [
            ("재료", "담백한 고기", 40),
            ("재료", "파프리카", 8),
            ("재료", "밥", 16),
            ("재료", "양파", 16),
            ("재료", "고춧가루", 4),
            ("가공 재료", "쌀", 300),
            ("가공 재료", "물이 든 병", 72),
        ],
    },
]

BARTER_MATERIAL_SOURCES = [
    ("구매 재료", "당근", 20, "이멘마하 - 고든", 4200, 84000, None, None, None),
    ("구매 재료", "소금", 24, "티르 / 던바 / 반호르 / 이멘", 1000, 24000, None, None, None),
    ("구매 재료", "샐러리", 8, "이멘마하 - 고든", 10000, 80000, None, None, None),
    ("구매 재료", "식용유", 20, "티르 / 던바 / 이멘마하", 1200, 24000, None, None, None),
    ("구매 재료", "딸기", 32, "콜헨 / 이멘마하", 1200, 38400, None, None, None),
    ("구매 재료", "설탕", 44, "티르 / 던바 / 이멘마하", 1200, 52800, None, None, None),
    ("구매 재료", "조각 초콜릿", 20, "이멘마하 - 프레이저", 3500, 70000, None, None, None),
    ("구매 재료", "담백한 고기", 40, "반호르 / 이멘마하", 400, 16000, None, None, None),
    ("구매 재료", "파프리카", 8, "이멘마하 - 고든", 7300, 58400, None, None, None),
    ("구매 재료", "고춧가루", 4, "제니퍼/프레이저", 3000, 12000, None, None, None),
    ("가공 재료", "밀가루", 32, "프레이저", 600, 18000, None, None, None),
    ("가공 재료", "생크림", 24, "주간 30개", 1100, 33000, None, None, None),
    ("가공 재료", "밥", 16, "구매 불가", None, None, None, None, None),
    ("가공 재료", "말린 찻잎", 16, "구매 불가", None, None, None, None, None),
    ("가공 재료", "오트밀", 20, "구매 불가", None, None, None, None, None),
    ("가공 재료", "두유", 24, "구매 불가", None, None, None, None, None),
    ("가공 재료", "물에 불린 콩", 16, "구매 불가", None, None, None, None, None),
    ("채집 재료", "양파", 16, "던바튼 / 이멘마하", None, None, "호미질", "Lv.1", None),
    ("채집 재료", "양배추", 32, "이멘마하", None, None, "호미질", "Lv.15", None),
    ("채집 재료", "물이 든 병", 123, "모든 지역", None, None, None, "Lv.1", None),
    ("채집 재료", "우유", 96, "던바튼 / 이멘마하", None, None, "일상 채집", "Lv.1", None),
    ("채집 재료", "달걀", 124, "던바튼 추천", None, None, "일상 채집", "Lv.1", None),
    ("채집 재료", "찻잎", 180, "이멘마하", None, None, "일상 채집", "Lv.10", None),
    ("채집 재료", "헤이즐넛", 80, "이멘마하", None, None, "일상 채집", "Lv.25", None),
    ("채집 재료", "허브", 24, "모든 마을", None, None, "약초 채집", "Lv.1", None),
    ("채집 재료", "밀", 45, "티르코네일 / 던바튼", None, None, "추수", "Lv.1", None),
    ("채집 재료", "콩", 270, "반호르", None, None, "추수", "Lv.10", None),
    ("채집 재료", "쌀", 300, "이멘마하", None, None, "추수", "Lv.20", None),
    ("채집 재료", "귀리", 210, "이멘마하", None, None, "추수", "Lv.25", None),
]


def initialize_barter_db(db_file="iris.db"):
    import sqlite3

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    create_barter_tables(cur)
    seed_barter_data(cur)
    conn.commit()
    return conn


def create_barter_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS barter_recipes (
            recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trader TEXT NOT NULL,
            dish_name TEXT NOT NULL,
            dish_quantity INTEGER NOT NULL,
            reward_item TEXT NOT NULL,
            weekly_limit TEXT,
            source_note TEXT,
            UNIQUE(trader, dish_name)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS barter_recipe_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            material_type TEXT NOT NULL,
            material_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY(recipe_id) REFERENCES barter_recipes(recipe_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS barter_material_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            material_name TEXT NOT NULL UNIQUE,
            quantity INTEGER NOT NULL,
            source TEXT,
            unit_price INTEGER,
            total_price INTEGER,
            gather_method TEXT,
            required_level TEXT,
            note TEXT
        )
        """
    )


def seed_barter_data(cur):
    for recipe in BARTER_RECIPES:
        cur.execute(
            """
            INSERT OR IGNORE INTO barter_recipes
                (trader, dish_name, dish_quantity, reward_item, weekly_limit, source_note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                recipe["trader"],
                recipe["dish_name"],
                recipe["dish_quantity"],
                recipe["reward_item"],
                recipe["weekly_limit"],
                BARTER_SOURCE_NOTE,
            ),
        )
        cur.execute(
            """
            UPDATE barter_recipes
            SET dish_quantity = ?, reward_item = ?, weekly_limit = ?, source_note = ?
            WHERE trader = ? AND dish_name = ?
            """,
            (
                recipe["dish_quantity"],
                recipe["reward_item"],
                recipe["weekly_limit"],
                BARTER_SOURCE_NOTE,
                recipe["trader"],
                recipe["dish_name"],
            ),
        )
        cur.execute(
            "SELECT recipe_id FROM barter_recipes WHERE trader = ? AND dish_name = ?",
            (recipe["trader"], recipe["dish_name"]),
        )
        recipe_id = cur.fetchone()["recipe_id"]
        cur.execute("DELETE FROM barter_recipe_materials WHERE recipe_id = ?", (recipe_id,))
        cur.executemany(
            """
            INSERT INTO barter_recipe_materials
                (recipe_id, material_type, material_name, quantity)
            VALUES (?, ?, ?, ?)
            """,
            [(recipe_id, material_type, material_name, quantity) for material_type, material_name, quantity in recipe["materials"]],
        )

    for source in BARTER_MATERIAL_SOURCES:
        cur.execute(
            """
            INSERT OR REPLACE INTO barter_material_sources
                (category, material_name, quantity, source, unit_price, total_price, gather_method, required_level, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            source,
        )


def _comma_number(value):
    return f"{value:,}" if isinstance(value, int) else "-"


def _material_text(rows):
    return ", ".join(f"{row['material_name']} {row['quantity']}" for row in rows) if rows else "-"


def _format_source(row):
    lines = [f"[{row['category']}] {row['material_name']} x{row['quantity']}"]
    if row["source"]:
        label = "채집처" if row["category"] == "채집 재료" else "구매/획득처"
        lines.append(f"{label}: {row['source']}")
    if row["unit_price"] is not None or row["total_price"] is not None:
        lines.append(f"단가: {_comma_number(row['unit_price'])} / 금액: {_comma_number(row['total_price'])}")
    if row["gather_method"] or row["required_level"]:
        method = row["gather_method"] or "채집"
        level = row["required_level"] or "-"
        lines.append(f"채집: {method} {level}")
    if row["note"]:
        lines.append(f"비고: {row['note']}")
    return "\n".join(lines)


def _format_recipe(cur, row):
    recipe_id = row["recipe_id"]
    cur.execute(
        """
        SELECT material_name, quantity
        FROM barter_recipe_materials
        WHERE recipe_id = ? AND material_type = ?
        ORDER BY id
        """,
        (recipe_id, "재료"),
    )
    materials = cur.fetchall()
    cur.execute(
        """
        SELECT material_name, quantity
        FROM barter_recipe_materials
        WHERE recipe_id = ? AND material_type = ?
        ORDER BY id
        """,
        (recipe_id, "가공 재료"),
    )
    processed = cur.fetchall()
    reward = row["reward_item"]
    if row["weekly_limit"]:
        reward = f"{reward} ({row['weekly_limit']})"
    return "\n".join(
        [
            f"[요리] {row['dish_name']} x{row['dish_quantity']}",
            f"교환자: {row['trader']}",
            f"교환 물품: {reward}",
            f"재료: {_material_text(materials)}",
            f"가공 재료: {_material_text(processed)}",
        ]
    )


def _format_barter_help(cur):
    cur.execute(
        """
        SELECT trader, dish_name, reward_item
        FROM barter_recipes
        ORDER BY recipe_id
        """
    )
    rows = cur.fetchall()
    lines = [
        "물교 정보 검색",
        "사용법: /물교 [요리/재료/교환자/교환물품]",
        "예: /물교 당근, /물교 오트밀, /물교 멜렌",
        "등록 요리:",
    ]
    lines.extend(f"- {row['trader']} / {row['dish_name']} -> {row['reward_item']}" for row in rows)
    return "\n".join(lines)


def search_barter_info(cur, query, max_recipes=4, max_sources=6):
    keyword = f"%{query}%"
    cur.execute(
        """
        SELECT DISTINCT r.*
        FROM barter_recipes r
        LEFT JOIN barter_recipe_materials m ON m.recipe_id = r.recipe_id
        WHERE r.trader LIKE ?
           OR r.dish_name LIKE ?
           OR r.reward_item LIKE ?
           OR m.material_name LIKE ?
        ORDER BY r.recipe_id
        LIMIT ?
        """,
        (keyword, keyword, keyword, keyword, max_recipes),
    )
    recipes = cur.fetchall()

    cur.execute(
        """
        SELECT *
        FROM barter_material_sources
        WHERE material_name LIKE ?
           OR category LIKE ?
           OR source LIKE ?
           OR gather_method LIKE ?
           OR note LIKE ?
        ORDER BY
            CASE category
                WHEN '구매 재료' THEN 1
                WHEN '가공 재료' THEN 2
                WHEN '채집 재료' THEN 3
                ELSE 4
            END,
            id
        LIMIT ?
        """,
        (keyword, keyword, keyword, keyword, keyword, max_sources),
    )
    sources = cur.fetchall()

    if not recipes and not sources:
        return (
            f"'{query}' 물교 정보를 찾지 못했습니다.\n"
            "예: /물교 당근, /물교 오트밀, /물교 멜렌"
        )

    lines = [f"물교 정보 검색: {query}", "────────"]
    if sources:
        lines.append("재료 정보")
        for row in sources:
            lines.append(_format_source(row))
            lines.append("")
    if recipes:
        lines.append("관련 요리")
        for row in recipes:
            lines.append(_format_recipe(cur, row))
            lines.append("")

    return "\n".join(lines).strip()


def handle_barter_commands(chat, get_db_conn, db_lock):
    cmd = getattr(chat.message, "command", "")
    if cmd not in BARTER_COMMANDS and cmd not in BARTER_LIST_COMMANDS:
        return False

    query = getattr(chat.message, "param", "").strip()

    with db_lock:
        conn = get_db_conn()
        cur = conn.cursor()
        if cmd in BARTER_LIST_COMMANDS or not query:
            message = _format_barter_help(cur)
        else:
            message = search_barter_info(cur, query)
        conn.close()

    chat.reply(message)
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="물교 정보 DB 초기화 및 검색")
    parser.add_argument("query", nargs="*", help="검색어. 예: 당근, 오트밀, 멜렌")
    parser.add_argument("--db", default="iris.db", help="SQLite DB 경로. 기본값: iris.db")
    args = parser.parse_args()

    conn = initialize_barter_db(args.db)
    cur = conn.cursor()
    query = " ".join(args.query).strip()
    if query:
        print(search_barter_info(cur, query))
    else:
        print(_format_barter_help(cur))
    conn.close()


if __name__ == "__main__":
    main()
