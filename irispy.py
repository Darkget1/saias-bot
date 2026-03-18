from iris import ChatContext, Bot
from iris.bot.models import ErrorContext
from bots.gemini import get_gemini
from bots.pyeval import python_eval, real_eval
from bots.stock import create_stock_image
from bots.imagen import get_imagen
from bots.lyrics import get_lyrics, find_lyrics
from bots.replyphoto import reply_photo
from bots.text2image import draw_text
from bots.coin import get_coin_info


from iris.decorators import *
from helper.BanControl import ban_user, unban_user
from iris.kakaolink import IrisLink

from bots.detect_nickname_change import detect_nickname_change
import sys, threading, random
from bots.party import handle_party_command
from bots.event import handle_event_command
from bots.user_system import handle_user_commands,start_lotto_scheduler
from bots.game import handle_game_input,handle_369_command,handle_reaction_command,handle_game_cancel
iris_url = sys.argv[1]
bot = Bot(iris_url)

# ─────────────────────────────
# 넌센스 퀴즈 데이터 & 상태
# ─────────────────────────────

NONSENSE_QUIZZES = [
    {"q": "백가지 과일이 죽기 직전을 다른 말로?", "a": "백과사전"},
    {"q": "지금 몇 시 몇 분?", "a": "짜장면시키신분"},
    {"q": "A젖소와 B젖소가 싸움을 했는데 B젖소가 이겼다 이유는?", "a": "에이졌소"},
    {"q": "펭귄이 다니는 중학교는?", "a": "냉방중"},
    {"q": "깨뜨리고 칭찬 받는 것은?", "a": "신기록"},
    {"q": "거꾸로 매달린 집에 수십개의 문이 있는 것은?", "a": "벌집"},
    {"q": "청바지를 돋보이게 하는 걸음걸이는?", "a": "진주목걸이"},
    {"q": "[창고에 양초가 꽉 차있는 것]을 세 글자로?", "a": "초만원"},
    {"q": "못 사온다고 해놓고 사온 것은?", "a": "못"},
    {"q": "무가 자기소개를 할 때 하는 말은?", "a": "나무"},
    {"q": "운전하는 사람들이 가장 싫어하는 춤은?", "a": "우선멈춤"},
    {"q": "싸움을 잘하는 오리는?", "a": "을지문덕"},
    {"q": "늘 청바지를 원하는 꽃은?", "a": "진달래"},
    {"q": "비 친구가 비한테 사우디아냐고 물어보는 말은?", "a": "사우디알아비야"},
    {"q": "양 중에서 가장 뜨거운 양은?", "a": "태양"},
    {"q": "고기 먹을 때 따라오는 개는?", "a": "이쑤시개"},
    {"q": "좀비는 왜 멍청할까?", "a": "머리가좀비어서"},
    {"q": "이 세상에서 가장 더운 바다는?", "a": "열바다"},
    {"q": "[힘센 말과 고양이]를 네 글자로?", "a": "슈퍼마켓"},
    {"q": "가수 샤이니가 다니는 고등학교는?", "a": "아미고"},
    {"q": "간짜장이 그냥 짜장보다 비싼 이유는?", "a": "간 때문이야"},
    {"q": "돈인데, 결혼을 해야 생기는 돈은?", "a": "사돈"},
    {"q": "사람들이 가장 좋아하는 영화는?", "a": "부귀영화"},
    {"q": "아기돼지 삼 형제에서 한 마리가 더 늘어나면?", "a": "모두 죽음"},
    {"q": "슬픈 사람들끼리 모여서 노는 것?", "a": "유유상종"},
    {"q": "아마존엔 누가 살까?", "a": "존"},
    {"q": "한국은 원, 일본은 엔, 호주는?", "a": "호주머니"},
    {"q": "사람 세 명이 탄 차를 세 글자로?", "a": "인삼차"},
    {"q": "비가 얼어죽으면?", "a": "비동사"},
    {"q": "닭이 스키니 바지를 입고 하는 말?", "a": "꼬끼오"},
    {"q": "모자 매장 진열대 사이에 신발을 두면?", "a": "캡사이신"},
    {"q": "사과가 웃으면?", "a": "풋사과"},
    {"q": "다정함의 반대는?", "a": "선택장애"},
    {"q": "북 중에서 가장 큰 북은?", "a": "동서남북"},
    {"q": "깨인데, 먹지 못하는 깨는?", "a": "주근깨"},
    {"q": "독수리가 불에 타면 어떤 소리가 날까?", "a": "이글이글"},
    {"q": "공기 1kg와 금 1kg 중, 어느 것이 더 무거울까?", "a": "똑같다"},
    {"q": "평생 부동산 투기만 한 사람이 남긴 유언은?", "a": "저승사자"},
    {"q": "망칠 수록 돈을 버는 사람은?", "a": "어부"},
    {"q": "군인이 돈을 다 쓰면?", "a": "무전병"},
    {"q": "오리인데, 물속에서만 사는 오리는?", "a": "가오리"},
    {"q": "오백에서 백을 빼면?", "a": "오"},
    {"q": "대학생들의 전투력이 높을 때는?", "a": "개강할때"},
    {"q": "일원동보다 싼 동네 이름은?", "a": "삼전동"},
    {"q": "공기만 먹어도 살이 찌는 것은?", "a": "풍선"},
    {"q": "[병에 걸린 가수 호란]을 네글자로?", "a": "병자호란"},
    {"q": "팔이 네개인 사람들이 사는 나라는?", "a": "네팔"},
    {"q": "꽃가게 주인장이 제일 싫어하는 나라는?", "a": "시드니"},
    {"q": "천하장사가 타고 다니는 차는?", "a": "으랏차차"},
    {"q": "교회에 가면 주는 돈은?", "a": "구원"},
    {"q": "가슴에 흑심을 품고 있는 것은?", "a": "연필"},
    {"q": "이상한 사람들이 모이는 곳은?", "a": "치과"},
    {"q": "왕과 처음 만날 때 하는 인사?", "a": "하이킹"},
    {"q": "직접 만든 총은?", "a": "손수건"},
    {"q": "돌하르방이 서커스단을 보고하는 말은?", "a": "제주도좋다"},
    {"q": "얼음이 죽으면?", "a": "다이빙"},
    {"q": "[제발 울지마~]를 한 글자로?", "a": "뚝"},
    {"q": "무엇이든 팔 수 있는 나라는?", "a": "팔라우"},
    {"q": "결정 장애가 많은 대학은?", "a": "고려대학교"},
    {"q": "곰돌이 푸가 차에 치이면?", "a": "카푸치노"},
    {"q": "사자를 넣고 끓인 국은?", "a": "동물의왕국"},
    {"q": "도둑이 훔친 돈을 네 글자로?", "a": "슬그머니"},
    {"q": "떡 중에 가장 빨리 먹는 떡은?", "a": "헐레벌떡"},
    {"q": "고추장 보다 높은 것은?", "a": "초고추장"},
    {"q": "[소 네 마리]를 두 글자로?", "a": "소포"},
    {"q": "우리나라 사람들이 다 같이 쓰는 가위는?", "a": "한가위"},
    {"q": "딩동댕의 반대말은?", "a": "땡"},
    {"q": "만 마리의 소들이 절을하는 것을 세글자로?", "a": "만우절"},
    {"q": "세상에서 가장 잘 깨지는 창문은?", "a": "와장창"},
    {"q": "아재가 좋아하는 악기는?", "a": "아쟁"},
    {"q": "[골뱅이가 무를 때렸다]를 다섯글자로?", "a": "골뱅이무침"},
    {"q": "길면 길 수록 좋은 강은?", "a": "만수무강"},
    {"q": "굴인데 먹을 수 없는 굴은?", "a": "동굴"},
    {"q": "세상에서 가장 더러운 강은?", "a": "요강"},
    {"q": "3월에 대학생이 강한 이유는?", "a": "개강해서"},
    {"q": "엄마가 길을 잃으면?", "a": "맘마미아"},
    {"q": "구리는 구리인데 못 쓰는 구리는?", "a": "멍텅구리"},
    {"q": "가수 설운도가 옷 벗는 순서는?", "a": "상하의"},
    {"q": "모든 사람들이 거짓말만 하는 절은?", "a": "만우절"},
    {"q": "사람이 가장 많이 말하는 소리는?", "a": "숨소리"},
    {"q": "남들과 반대로 생활하는 쥐는?", "a": "박쥐"},
    {"q": "곰은 사과를 어떻게 먹을까?", "a": "베어먹음"},
    {"q": "손을 올리면 멈추는 것은?", "a": "택시"},
    {"q": "우리나라에서 김이 가장 많이나는 곳은?", "a": "목욕탕"},
    {"q": "오래 살 것 같은 연예인은?", "a": "이승깁니다"},
    {"q": "[돼지가 방귀를 뀌면]을 세글자로?", "a": "돈가스"},
    {"q": "술을 좋아하는 사람들이 모인 나라는?", "a": "호주"},
    {"q": "어부가 가장 싫어하는 노래는?", "a": "바다가육지라면"},
    {"q": "[가수 비가 LA에 갈 것이다]를 네 글자로?", "a": "LA갈비"},
    {"q": "송해가 샤워를 하면?", "a": "뽀송뽀송해"},
    {"q": "눈으로 못 보고, 입으로만 보는 것은?", "a": "맛"},
    {"q": "몽골 사람이 땀을 흘리면?", "a": "몽골몽골"},
    {"q": "들어가는 입구는 하나지만, 나오는 입구는 2개인 것은?", "a": "바지"},
    {"q": "사람이 먹을 수 있는 제비는?", "a": "수제비"},
    {"q": "[자식이 아홉명이다]를 세 글자로?", "a": "아이구"},
    {"q": "우리나라까지 석유가 도착하는데 소요되는 시간은?", "a": "오일"},
    {"q": "사람의 몸무게가 가장 많이 나갈 때는?", "a": "철들때"},
    {"q": "곤충의 몸을 삼등분 하면?", "a": "죽는다"},
    {"q": "과자가 자기소개를 하면?", "a": "전과자"},
    {"q": "톱 중에서 가장 유명한 톱은?", "a": "톱스타"},

]

# 방(또는 채팅)별 진행 중인 퀴즈 상태
# key: room_id, value: {"q": str, "a": str}
NONSENSE_STATE = {}


def get_room_id(chat: ChatContext) -> str:
    """
    방/채팅을 구분할 수 있는 고유값.
    iris 버전에 맞게 필요하면 수정해서 사용.
    """
    if hasattr(chat, "room") and hasattr(chat.room, "id"):
        return str(chat.room.id)
    # 방 정보가 없다면, 보낸 사람 기준으로라도 구분
    return str(chat.sender.id)


def start_nonsense_quiz(chat: ChatContext):
    room_id = get_room_id(chat)
    quiz = random.choice(NONSENSE_QUIZZES)
    NONSENSE_STATE[room_id] = quiz

    chat.reply(
        "🧠 넌센스 퀴즈 나갑니다!\n\n"
        f"Q. {quiz['q']}\n\n"
        "정답은 `/답 답` 이런 식으로 보내줘!\n"
        "예) `/답 열받아`"
    )


def check_nonsense_answer(chat: ChatContext):
    room_id = get_room_id(chat)
    quiz = NONSENSE_STATE.get(room_id)

    if not quiz:
        chat.reply("지금 진행 중인 넌센스 퀴즈가 없어요 😅\n`/넌센스`로 새 문제를 시작해줘!")
        return

    # ✅ iris 구조 그대로 사용
    # - chat.message.command  = "!정답"
    # - chat.message.param    = "열받아"
    user_answer = getattr(chat.message, "param", "").strip()

    if not user_answer:
        chat.reply("정답 뒤에 내용을 같이 써줘! 예: `!정답 열받아`")
        return

    correct = quiz["a"].strip().lower()
    user_norm = user_answer.lower()

    if user_norm == correct:
        chat.reply(
            f"🎉 정답! 정답은 `{quiz['a']}` 맞아요!\n"
            "또 풀고 싶으면 `/넌센스`라고 보내줘!"
        )
        NONSENSE_STATE.pop(room_id, None)
    else:
        chat.reply(
            f"❌ 아쉽다... `{user_answer}` 는 정답이 아니야.\n"
            "다시 한 번 생각해볼래?\n"
            "포기하고 싶으면 `/포기` 라고 보내줘!"
        )

def giveup_nonsense_quiz(chat: ChatContext):
    room_id = get_room_id(chat)
    quiz = NONSENSE_STATE.get(room_id)

    if not quiz:
        chat.reply("포기할 퀴즈가 없어요 😅\n`/넌센스`로 새 문제를 시작해줘!")
        return

    chat.reply(
        f"📝 정답 공개!\n\n"
        f"Q. {quiz['q']}\nA. {quiz['a']}\n\n"
        "또 풀고 싶으면 `/넌센스`!"
    )
    NONSENSE_STATE.pop(room_id, None)



@bot.on_event("message")
@is_not_banned
def on_message(chat: ChatContext):
    try:
        # command 속성이 없을 수도 있으니 getattr로 안전하게 가져오는 것을 추천합니다.
        cmd = getattr(chat.message, "command", None)
        if handle_user_commands(chat):
            return
        match cmd:
            case "/넌센스":
                start_nonsense_quiz(chat)
            case "/답":
                check_nonsense_answer(chat)
            case "/포기":
                giveup_nonsense_quiz(chat)

            case "/파티" | "/파티참가" | "/파티참여" | "/파티목록" | "/파티탈퇴" | "/파티삭제" | "/레이드파티" | "/파티홍보" | "/파티멤버추가" | "/파티추방" | "/파티도움말":
                handle_party_command(chat)

            case "/이벤트생성" | "/내이벤트" | "/이벤트삭제" | "/이벤트참여" | "/이벤트참가" | "/이벤트탈퇴" | "/이벤트취소" | "/이벤트목록" | "/이벤트현황" | "/이벤트도움말"|"/이벤트멤버삭제"|"/이벤트탈퇴"|"/이벤트홍보":
                handle_event_command(chat)

            case "/반응참가" | "/반응시작":
                handle_reaction_command(chat)

            case "/369시작" | "/369끝" | "/369상태":
                handle_369_command(chat)
            case "/게임삭제" | "/게임취소":
                handle_game_cancel(chat)
            case _:
                # 위에서 정의한 명령어(/)가 아닌 모든 일반 채팅(숫자, 'ㅉ' 등)은
                # 여기서 통합으로 처리합니다.
                handle_game_input(chat)

    except Exception as e:
        print(f"Error in on_message: {e}")
# 입장감지
@bot.on_event("new_member")
def on_newmem(chat: ChatContext):
    # chat.reply(f"Hello {chat.sender.name}")
    pass


# 퇴장감지
@bot.on_event("del_member")
def on_delmem(chat: ChatContext):
    # chat.reply(f"Bye {chat.sender.name}")
    pass


@bot.on_event("error")
def on_error(err: ErrorContext):
    print(err.event, "이벤트에서 오류가 발생했습니다", err.exception)
    # sys.stdout.flush()


if __name__ == "__main__":
    # 닉네임감지를 사용하지 않는 경우 주석처리
    nickname_detect_thread = threading.Thread(
        target=detect_nickname_change,
        args=(bot.iris_url,),
    )
    nickname_detect_thread.start()
    start_lotto_scheduler(bot)

    # 카카오링크를 사용하지 않는 경우 주석처리
    kl = IrisLink(bot.iris_url)

    bot.run()
