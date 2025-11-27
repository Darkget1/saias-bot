# coding: utf8
from PIL import Image, ImageFont, ImageDraw
import requests, random, os, re, sqlite3, threading
from io import BytesIO
from typing import Optional

from bots.gemini import get_gemini_vision_analyze_image
from iris.decorators import *
from iris import ChatContext, PyKV

RES_PATH = "res/"

# --- iris.db 사용 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IRIS_DB_PATH = os.path.join(BASE_DIR, "iris.db")  # ✅ 기존 iris.db 사용
PERSONAL_IMG_DB_LOCK = threading.RLock()

disallowed_substrings = [
    "medium.com",
    "post.phinf.naver.net",
    ".gif",
    "imagedelivery.net",
    "clien.net",
]


# =========================================
#  iris.db 안에 personal_images 테이블 만들기
# =========================================

def init_personal_image_table():
    """
    iris.db 안에 sender_id -> image BLOB 저장하는 personal_images 테이블 생성
    """
    with PERSONAL_IMG_DB_LOCK:
        conn = sqlite3.connect(IRIS_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personal_images (
                    sender_id  TEXT PRIMARY KEY,
                    image      BLOB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


init_personal_image_table()


# =========================================
#  엔트리 포인트
# =========================================

def draw_text(chat: ChatContext):
    match chat.message.command:
        case "!텍스트":
            draw_default(chat)
        case "!사진":
            txt = chat.message.param
            chat.message.param = f"검색##{txt}##  "
            draw_default(chat)
        case "!껄무새":
            draw_parrot(chat)
        case "!멈춰":
            draw_stop(chat)
        case "!지워":
            draw_rmrf(chat)
        case "!진행":
            draw_gogo(chat)
        case "!말대꾸":
            draw_sungmo(chat)
        case "!텍스트추가":
            add_text(chat)
        case "!업로드":   # 카톡 이미지 → iris.db에 개인 이미지 저장
            upload_url_image(chat)


# =========================================
#  기본 이미지/텍스트 그리기
# =========================================

def draw_default(chat: ChatContext):
    try:
        msg = chat.message.param or ""
        msg_split = msg.split("##")
        url = None

        match len(msg_split):
            case 1:
                txt = msg
                check = ""

                # ✅ 개인 이미지가 있으면 그걸 기본 배경으로 사용, 없으면 default.jpg
                img = load_personal_image(chat)
                if img is None:
                    img = Image.open(RES_PATH + "default.jpg")

            case 2:
                img = get_image_from_url(msg_split[0])
                txt = msg_split[1]
                check = get_gemini_vision_analyze_image(msg_split[0])

            case 3:
                url = get_image_url_from_naver(msg_split[1])
                print(f"received photo url: {url}")
                if url is False:
                    chat.reply("사진 검색에 실패했습니다.")
                    return None

                img = get_image_from_url(url)
                txt = msg_split[2]
                check = get_gemini_vision_analyze_image(url)
                print(f'check result: {"True" if "True" in check else "False"}')

            case _:
                return None

        if "True" in check:
            chat.reply("과도한 노출로 차단합니다.")
            return None

        add_default_text(chat, img, txt)
    except Exception as e:
        print(e)
        if url:
            print(f"Exception occurred with url: {url}")
            kv = PyKV()
            failed_urls = kv.get("naver_failed_urls")
            if not failed_urls:
                failed_urls = []
            failed_urls.append(url)
            kv.put("naver_failed_urls", failed_urls)


def draw_parrot(chat: ChatContext):
    txt = chat.message.param
    img = Image.open(RES_PATH + "parrot.jpg")
    add_default_text(chat, img, txt)


def draw_stop(chat: ChatContext):
    txt = chat.message.param
    img = Image.open(RES_PATH + "stop.jpg")
    add_default_text(chat, img, txt)


def draw_gogo(chat: ChatContext):
    color = "#FFFFFF"
    txt = chat.message.param
    img = Image.open(RES_PATH + "gogo.png")
    fontsize = 30
    draw = ImageDraw.Draw(img)
    font = ImageFont.FreeTypeFont(RES_PATH + "NotoSansCJK-Bold.ttc", fontsize)
    w, h = multiline_textsize(txt, font=font)
    draw.multiline_text(
        (20, img.size[1] / 2 - 70),
        u"%s" % txt,
        font=font,
        fill=color,
    )
    chat.reply_media([img])


def draw_rmrf(chat: ChatContext):
    color = "#000000"
    txt = chat.message.param
    img = Image.open(RES_PATH + "rmrf.jpg")
    fontsize = 40
    draw = ImageDraw.Draw(img)
    font = ImageFont.FreeTypeFont(RES_PATH + "GmarketSansBold.otf", fontsize)
    w, h = multiline_textsize(txt, font=font)
    draw.multiline_text(
        (img.size[0] / 2 - w - 130, img.size[1] / 2 - 30),
        u"%s" % txt,
        font=font,
        fill=color,
    )
    chat.reply_media([img])


def draw_sungmo(chat: ChatContext):
    color = "#000000"
    txt_split = (chat.message.param or "").split("##")
    if len(txt_split) < 2:
        chat.reply("형식: !말대꾸 위문구##아래문구")
        return

    txt1 = txt_split[0]
    txt2 = txt_split[1]
    img = Image.open(RES_PATH + "sungmo.jpeg")
    fontsize = 60
    draw = ImageDraw.Draw(img)
    font = ImageFont.FreeTypeFont(RES_PATH + "NotoSansCJK-Bold.ttc", fontsize)

    w, h = multiline_textsize(txt1, font=font)
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 - 5, 60),
        u"%s" % txt1,
        font=font,
        fill=color,
    )

    w, h = multiline_textsize(txt2, font=font)
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 + 5, img.size[1] - 170),
        u"%s" % txt2,
        font=font,
        fill=color,
    )
    chat.reply_media([img])


@is_reply
def add_text(chat: ChatContext):
    src_chat = chat.get_source()
    if hasattr(src_chat.message, "image"):
        img = src_chat.message.image.img[0]
        txt = " ".join(chat.message.msg.split(" ")[1:])
        add_default_text(chat, img, txt)
    else:
        return


def add_default_text(chat: ChatContext, img: Image.Image, txt: str):
    # 색상 옵션: "문구::ff0000" 이런 식으로 컬러 지정
    if "::" in txt:
        option_split = txt.split("::")
        txt = option_split[0]
        color = "#" + option_split[1]
    else:
        color = "#ffffff"

    draw = ImageDraw.Draw(img)

    fontsize = get_max_font_size(
        img.size[0], "아" * 10, RES_PATH + "GmarketSansBold.otf", max_search_size=500
    )
    font = ImageFont.FreeTypeFont(RES_PATH + "GmarketSansBold.otf", fontsize)

    w, h = multiline_textsize(txt, font)

    base_y = img.size[1] - h - (img.size[1] / 20)

    # 테두리 (검은색) 4방향
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 - 1, base_y - 1),
        u"%s" % txt,
        font=font,
        align="center",
        fill="black",
        spacing=10,
    )
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 + 1, base_y - 1),
        u"%s" % txt,
        font=font,
        align="center",
        fill="black",
        spacing=10,
    )
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 - 1, base_y + 1),
        u"%s" % txt,
        font=font,
        align="center",
        fill="black",
        spacing=10,
    )
    draw.multiline_text(
        (img.size[0] / 2 - w / 2 + 1, base_y + 1),
        u"%s" % txt,
        font=font,
        align="center",
        fill="black",
        spacing=10,
    )

    # 실제 텍스트
    draw.multiline_text(
        (img.size[0] / 2 - w / 2, base_y),
        u"%s" % txt,
        font=font,
        align="center",
        fill=color,
        spacing=10,
    )

    chat.reply_media([img])


# =========================================
#  URL에서 이미지 가져오기 / 네이버 이미지 검색
# =========================================

def get_image_from_url(url: str) -> Image.Image:
    """
    URL에서 이미지 받아오기
    - User-Agent 헤더 추가해서 google(encrypted-tbn 등) 대응
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception:
        # jpg/png 서로 바꿔가며 한 번 더 시도
        try:
            if url.lower().endswith("jpg"):
                alt = url[:-3] + "png"
            elif url.lower().endswith("png"):
                alt = url[:-3] + "jpg"
            else:
                raise
            response = requests.get(alt, headers=headers, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"[get_image_from_url] failed: {url} / {e}")
            raise

    img = Image.open(BytesIO(response.content))
    img = img.convert("RGBA")
    return img


def get_image_url_from_naver(query: str) -> bool | str:
    url = "https://openapi.naver.com/v1/search/image"
    headers = {
        "X-Naver-Client-Id": os.getenv("X_NAVER_CLIENT_ID"),
        "X-Naver-Client-Secret": os.getenv("X_NAVER_CLIENT_SECRET"),
    }
    params = {
        "query": query,
        "display": "20",
    }

    res = requests.get(url, params=params, headers=headers)
    js = res.json()["items"]
    link = []
    if not len(js) == 0:
        for item in js:
            if not any(
                disallowed_substring in item["link"]
                for disallowed_substring in disallowed_substrings
            ):
                link.append(item["link"])
        if len(link) == 0:
            return False
        else:
            return link[random.randint(0, len(link) - 1)]
    else:
        return False


def get_max_font_size(image_width, text, font_path, max_search_size=500):
    target_width = image_width
    low = 1
    high = max_search_size
    best_size = None

    while low <= high:
        mid = (low + high) // 2
        font = ImageFont.FreeTypeFont(font_path, mid)
        w, h = multiline_textsize(text, font)

        if w <= target_width:
            best_size = mid
            low = mid + 1
        else:
            high = mid - 1

    return best_size


def multiline_textsize(text, font):
    dummy_img = Image.new("RGB", (1, 1), color="white")
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, align="center", spacing=10)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    return (w, h)


def multiline_textsize_old(text, font):
    total_width = 0
    total_height = 0

    lines = text.splitlines()

    for line in lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        total_width = max(total_width, w)
        total_height += h

    return (total_width, total_height)


# =========================================
#  iris.db 안 personal_images 헬퍼
# =========================================

def _get_sender_id(chat: ChatContext) -> str:
    """
    sender 기준으로 개인 이미지를 구분하기 위한 ID 추출
    (프로젝트 구조에 맞게 필드 이름만 맞추면 됨)
    """
    sender_id = getattr(chat.message, "sender_id", None)

    if sender_id is None and getattr(chat.message, "sender", None):
        sender_id = getattr(chat.message.sender, "id", None)

    if sender_id is None:
        sender_id = "unknown"

    return str(sender_id)


def save_personal_image(chat: ChatContext, img: Image.Image) -> None:
    """
    이미지를 PNG로 인코딩해서 BLOB으로 iris.db에 저장
    sender_id 당 1개 (REPLACE)
    """
    sender_id = _get_sender_id(chat)

    buf = BytesIO()
    img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    with PERSONAL_IMG_DB_LOCK:
        conn = sqlite3.connect(IRIS_DB_PATH)
        try:
            conn.execute(
                """
                INSERT INTO personal_images(sender_id, image)
                VALUES(?, ?)
                ON CONFLICT(sender_id) DO UPDATE SET
                    image = excluded.image,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (sender_id, sqlite3.Binary(raw_bytes)),
            )
            conn.commit()
        finally:
            conn.close()


def load_personal_image(chat: ChatContext) -> Optional[Image.Image]:
    """
    iris.db에서 sender_id에 해당하는 이미지를 꺼내서 PIL Image로 반환
    """
    sender_id = _get_sender_id(chat)

    with PERSONAL_IMG_DB_LOCK:
        conn = sqlite3.connect(IRIS_DB_PATH)
        try:
            cur = conn.execute(
                "SELECT image FROM personal_images WHERE sender_id = ?",
                (sender_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()

    if not row:
        return None

    try:
        raw_bytes = row[0]
        img = Image.open(BytesIO(raw_bytes))
        img = img.convert("RGBA")
        return img
    except Exception as e:
        print(f"[load_personal_image] failed: {e}")
        return None


# =========================================
#  URL / 텍스트 파싱 & 업로드(개인 이미지 저장)
# =========================================

def extract_first_url(text: str) -> Optional[str]:
    """
    메시지 안에서 첫 번째 URL 하나만 뽑는 헬퍼
    """
    url_pattern = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
    m = url_pattern.search(text)
    if m:
        return m.group(1)
    return None


def upload_url_image(chat: ChatContext):
    """
    URL 이미지를 '개인 이미지'로 iris.db에 저장하는 기능.

    우선순위:
      1) 답장 대상 메시지에 image.img 가 있으면 그대로 사용
      2) 답장 대상 메시지에 image.url 이 있으면 그 URL에서 다운로드
      3) 답장 대상 메시지 텍스트에서 URL 추출
      4) 위가 없으면, 현재 명령(chat.message)의 텍스트/param에서 URL 추출

    저장:
      - 찾은 이미지를 iris.db personal_images에 sender_id 기준으로 저장
      - 이후 !텍스트 사용 시 이 이미지를 기본 배경으로 활용
    """

    img_obj: Optional[Image.Image] = None

    # 0) 답장 대상 메시지 가져오기 (있을 수도, 없을 수도 있음)
    src_msg = None
    try:
        src_chat = chat.get_source()
        src_msg = src_chat.message
    except Exception:
        src_msg = None

    # 1) 답장 메시지에서 이미지 찾기 (이미지 그대로)
    if src_msg is not None:
        if getattr(src_msg, "image", None):
            if getattr(src_msg.image, "img", None):
                img_obj = src_msg.image.img[0]
            elif getattr(src_msg.image, "url", None):
                try:
                    img_obj = get_image_from_url(src_msg.image.url[0])
                except Exception as e:
                    print(f"[upload_url_image] src_msg.image.url download fail: {e}")
                    img_obj = None

        # 1-2) 아직 없으면, 답장 텍스트에서 URL 추출
        if img_obj is None:
            raw_text = getattr(src_msg, "msg", "") or ""
            url = extract_first_url(raw_text)
            if url:
                try:
                    img_obj = get_image_from_url(url)
                except Exception as e:
                    print(f"[upload_url_image] src_msg text url download fail: {e}")
                    img_obj = None

    # 2) 답장 쪽에서 못 찾으면, 현재 명령 메세지에서 URL 추출
    current_raw_msg = (chat.message.msg or "") + " " + (chat.message.param or "")
    if img_obj is None:
        url = extract_first_url(current_raw_msg)
        if url:
            try:
                img_obj = get_image_from_url(url)
            except Exception as e:
                print(f"[upload_url_image] current msg url download fail: {e}")
                img_obj = None

    if img_obj is None:
        chat.reply(
            "저장할 이미지를 찾을 수 없어요.\n"
            "- 이미지/링크가 있는 메세지에 답장해서 `!업로드`\n"
            "- 또는 `!업로드 https://...` 형태로 사용해주세요."
        )
        return

    # ✅ 여기서부터는 "저장"만 수행 (글씨는 !텍스트에서)
    save_personal_image(chat, img_obj)
    chat.reply("개인 이미지로 저장했어요! 이제 `!텍스트 내용`으로 사용할 수 있어요.")
