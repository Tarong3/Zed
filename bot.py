import discord
from discord.ext import commands
from discord.ui import View, Button
import requests
import random
import itertools
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
from player_data import player_data
import asyncio
import re
import time
import os
import io  # 이미지를 메모리에 저장하기 위해 사용

# 서버 구동시
from keep_alive import keep_alive
keep_alive()

# 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True
intents.message_content = True 

chrome_driver_path = './chromedriver.exe'
bot = commands.Bot(command_prefix='!', intents=intents)

# 수면 예약 관리용 딕셔너리
sleep_tasks = {}

# 시간 파싱 함수
def parse_time_string(time_str):
    match = re.match(r'(\d+)\s*(초|분|시간)', time_str)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)

    if unit == "초":
        return value
    elif unit == "분":
        return value * 60
    elif unit == "시간":
        return value * 60 * 60
    return None

async def sleep_task(ctx, target: discord.Member, seconds: int, is_self: bool):
    try:
        await asyncio.sleep(seconds)

        voice_state = target.voice
        if voice_state and voice_state.channel:
            try:
                await target.move_to(None)
                if is_self:
                    await ctx.send(f"{target.mention} 잘 자요! 💤")
                else:
                    await ctx.send(f"{target.mention} 잘 자요! 💤")
            except discord.Forbidden:
                await ctx.send("권한이 없어서 멤버를 내보낼 수 없어요 ㅠㅠ")
        else:
            await ctx.send(f"{target.mention} 님이 이미 음성 채널에서 나갔네요!")

    except asyncio.CancelledError:
        # 딕셔너리에서 silent_cancel 확인
        cancel_info = sleep_tasks.get(target.id, {})
        if not cancel_info.get('silent_cancel', False):
            await ctx.send(f"{target.mention} 님은 아직 잘 때가 아닌가 보네요!")

    finally:
        sleep_tasks.pop(target.id, None)

@bot.command(name='수면')
async def sleep_timer(ctx, time: str, target: discord.Member = None):
    author = ctx.author

    if target is None:
        target = author
        is_self = True
    else:
        is_self = False

    if not is_self and not author.guild_permissions.administrator:
        await ctx.send(f"{author.mention} 님은 다른 사람을 수면시킬 권한이 없어요!")
        return

    voice_state = target.voice
    if not voice_state or not voice_state.channel:
        await ctx.send(f"{target.mention} 음성 채널에 있어야만 수면시킬 수 있어요!")
        return

    seconds = parse_time_string(time)
    if seconds is None:
        await ctx.send("시간 형식이 잘못됐어요! `!수면 30초`, `!수면 10분` 또는 `!수면 1시간` 이렇게 입력해 주세요.")
        return

    # 기존 예약이 있으면 덮어씌움 (silent_cancel=True)
    existing_task_info = sleep_tasks.get(target.id)
    if existing_task_info:
        existing_task_info['silent_cancel'] = True
        existing_task_info['task'].cancel()
        await ctx.send(f"{target.mention} 기존 예약에 덮어씌웁니다.")

    if is_self:
        await ctx.send(f"{author.mention} {time} 뒤에 음성 채널에서 내보낼게요. 편히 쉬어요!")
    else:
        await ctx.send(f"{target.mention} {time} 뒤에 음성 채널에서 내보낼게요. 편히 쉬어요!")

    task = asyncio.create_task(sleep_task(ctx, target, seconds, is_self))
    sleep_tasks[target.id] = {
        'task': task,
        'silent_cancel': False  # 기본은 취소 메시지 띄우기
    }

@bot.command(name='수면취소')
async def cancel_sleep(ctx, target: discord.Member = None):
    author = ctx.author

    if target is None:
        target = author
        is_self = True
    else:
        is_self = False

    if not is_self and not author.guild_permissions.administrator:
        await ctx.send(f"{author.mention} 님은 다른 사람의 수면을 취소할 권한이 없어요!")
        return

    task_info = sleep_tasks.get(target.id)
    if not task_info:
        await ctx.send(f"{target.mention} 님은 현재 수면 예약이 없어요!")
        return

    # 취소할 때는 silent_cancel=False로 설정!
    task_info['silent_cancel'] = False
    task_info['task'].cancel()

    # 취소 메시지는 sleep_task() 안에서 처리됨!


def menu_recommendation_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            menus = [line.strip() for line in file if line.strip()]
        
        if not menus:
            return "메뉴 리스트가 비어있어요!"
        
        return random.choice(menus)
    
    except FileNotFoundError:
        return "메뉴 파일이 존재하지 않습니다!"
    except Exception as e:
        return f"오류 발생: {e}"
    
@bot.command(name='저메추')
async def menu_recommend(ctx):
    file_path = './texts/foodmenu.txt'  # 메뉴 리스트 파일 경로
    result = menu_recommendation_from_file(file_path)
    
    # 결과를 임베드로 보낼 수도 있고, 그냥 텍스트로도 가능!
    embed = discord.Embed(title="🍴 오늘의 메뉴 추천!", description=result, color=0x00ff00)
    await ctx.send(embed=embed)
    
def 생성_조합(참여플레이어, 제외포지션=None, 고정포지션=None):
    if 제외포지션 is None:
        제외포지션 = []
    if 고정포지션 is None:
        고정포지션 = {}

    후보_리스트 = {}

    # 각 플레이어별 캐릭터 후보 만들기
    for 플레이어 in 참여플레이어:
        후보캐릭 = player_data.get(플레이어, [])
        포지션별_캐릭터 = []

        # 고정 포지션이 있으면 해당 포지션만 남김
        if 플레이어 in 고정포지션:
            고정포 = 고정포지션[플레이어]

            for 캐릭 in 후보캐릭:
                # 주포지션 검사
                if 캐릭["주포지션"] == 고정포 and 고정포 not in 제외포지션:
                    포지션별_캐릭터.append({
                        "이름": 캐릭["이름"],
                        "선택포지션": 캐릭["주포지션"],
                        "수비": 캐릭["수비"]
                    })

                # 부포지션 검사
                if 고정포 in 캐릭["부포지션"] and 고정포 not in 제외포지션:
                    포지션별_캐릭터.append({
                        "이름": 캐릭["이름"],
                        "선택포지션": 고정포,
                        "수비": 캐릭["수비"]
                    })

        else:
            # 고정포지션이 없으면 기존 방식으로 후보 생성
            for 캐릭 in 후보캐릭:
                # 주포지션 추가
                if 캐릭["주포지션"] not in 제외포지션:
                    포지션별_캐릭터.append({
                        "이름": 캐릭["이름"],
                        "선택포지션": 캐릭["주포지션"],
                        "수비": 캐릭["수비"]
                    })

                # 부포지션 추가
                for 부포 in 캐릭["부포지션"]:
                    if 부포 not in 제외포지션:
                        포지션별_캐릭터.append({
                            "이름": 캐릭["이름"],
                            "선택포지션": 부포,
                            "수비": 캐릭["수비"]
                        })

        후보_리스트[플레이어] = 포지션별_캐릭터

    # 플레이어별 후보 조합 만들기
    플레이어_캐릭_조합들 = [
        [(플레이어, 캐릭) for 캐릭 in 후보_리스트[플레이어]]
        for 플레이어 in 참여플레이어
    ]

    가능한_조합들 = []
    for 조합 in itertools.product(*플레이어_캐릭_조합들):
        포지션셋 = set([캐릭['선택포지션'] for _, 캐릭 in 조합])

        # 포지션 중복 체크
        if len(포지션셋) != len(참여플레이어):
            continue

        # 최소 한 명 수비 On인지 체크
        if not any(캐릭['수비'] == 'On' for _, 캐릭 in 조합):
            continue

        # 조건 충족한 조합 저장
        조합결과 = {플레이어: 캐릭 for 플레이어, 캐릭 in 조합}
        가능한_조합들.append(조합결과)

    if 가능한_조합들:
        return random.choice(가능한_조합들)
    else:
        return None

@bot.command(name="NBA")
async def nba(ctx, *args):
    참여플레이어 = []
    고정포지션 = {}

    # 자유로운 입력 파싱
    for arg in args:
        if "=" in arg:
            # 고정 포지션 입력
            try:
                플레이어, 포지션 = arg.split("=")
                플레이어 = 플레이어.strip()
                포지션 = 포지션.strip().upper()

                고정포지션[플레이어] = 포지션

                # 중복 방지하고 참여플레이어 추가
                if 플레이어 not in 참여플레이어:
                    참여플레이어.append(플레이어)

            except ValueError:
                await ctx.send(f"❌ `{arg}` 잘못된 입력입니다! `플레이어=포지션` 형태로 입력해주세요.")
                return
        else:
            플레이어 = arg.strip()

            # 중복 방지하고 참여플레이어 추가
            if 플레이어 not in 참여플레이어:
                참여플레이어.append(플레이어)

    # 최소 인원 체크
    if not 참여플레이어:
        await ctx.send("❌ 플레이어를 최소 1명 이상 입력해주세요!")
        return

    # 포지션 제외 질문
    await ctx.send(
        f"제외해야 할 포지션이 있나요? (예: PG SF)\n"
        f"없으면 '없음'이라고 입력해주세요!"
    )

    def check(m):
        return (
            m.author == ctx.author and
            m.channel == ctx.channel
        )

    try:
        msg = await bot.wait_for('message', timeout=30.0, check=check)
        제외포지션입력 = msg.content.upper()

        if 제외포지션입력 == "없음".upper():
            제외포지션 = []
        else:
            제외포지션 = 제외포지션입력.split()

        # 조합 생성 함수 호출 (고정포지션 + 제외포지션 포함)
        조합 = 생성_조합(참여플레이어, 제외포지션, 고정포지션)

        if 조합:
            결과텍스트 = "🏀 **추천 조합입니다!**\n"
            for 플레이어, 캐릭 in 조합.items():
                결과텍스트 += (
                    f"- {플레이어}: {캐릭['이름']} "
                    f"({캐릭['선택포지션']}) "
                    f"{'🛡️' if 캐릭['수비'] == 'On' else ''}\n"
                )
            await ctx.send(결과텍스트)
        else:
            await ctx.send("❌ 조건을 만족하는 조합을 찾을 수 없습니다!")

    except asyncio.TimeoutError:
        await ctx.send("⏰ 시간이 초과되었습니다! 다시 시도해주세요.")

def create_stat_image(nickname, 전적_데이터, 티어이름):
    img_width = 800
    img_height = 400

    text_color = (255, 255, 255)
    sub_text_color = (180, 180, 180)
    accent_color = (255, 100, 100)

    # 기본 배경
    background_color = (30, 30, 30)
    image = Image.new('RGBA', (img_width, img_height), background_color)

    # 패턴 이미지 넣기
    try:
        pattern_path = './backgrounds/pattern.png'
        pattern_image = Image.open(pattern_path).convert('RGBA')
        pattern_resized = pattern_image.resize((img_width, img_height))

        # 패턴을 배경에 덮기
        image.paste(pattern_resized, (0, 0), pattern_resized)

    except Exception as e:
        print(f"패턴 로드 실패: {e}")

    draw = ImageDraw.Draw(image)

    # 폰트 설정
    font_nickname = ImageFont.truetype('./fonts/SpoqaHanSansNeo-Bold.ttf', 48)
    font_tier = ImageFont.truetype('./fonts/SpoqaHanSansNeo-Regular.ttf', 22)
    font_rp = ImageFont.truetype('./fonts/SpoqaHanSansNeo-Bold.ttf', 28)
    font_small = ImageFont.truetype('./fonts/SpoqaHanSansNeo-Regular.ttf', 20)

    # --- 닉네임 ---
    draw.text((50, 50), f"{nickname}", font=font_nickname, fill=text_color)

    # --- 티어 아이콘 ---
    try:
        icon_path = f'./icons/{티어이름}.png'
        tier_icon = Image.open(icon_path).convert('RGBA')
        tier_icon = tier_icon.resize((100, 100))
        image.paste(tier_icon, (50, 160), tier_icon)
    except Exception as e:
        print(f"아이콘 로드 실패: {e}")

    # --- 티어 / RP ---
    tier_text = 전적_데이터.get('티어', '티어 정보 없음')
    rp_text = 전적_데이터.get('RP', 'RP 정보 없음')

    tier_colors = {
        '아이언': (225, 225, 225),
        '브론즈': (192, 192, 192),
        '실버': (160, 160, 160),
        '골드': (255, 215, 0),
        '플래티넘': (0, 191, 255),
        '다이아몬드': (39, 131, 243),
        '미스릴': (138, 43, 226),
        '이터니티': (255, 69, 0),
        '메테오라이트': (255, 140, 0)
    }

    dynamic_rp_color = tier_colors.get(티어이름, accent_color)

    draw.text((50, 275), tier_text, font=font_tier, fill=text_color)
    draw.text((50, 310), rp_text, font=font_rp, fill=dynamic_rp_color)

    # --- 전적 데이터 ---
    col1_x = 280
    col2_x = 530
    y_start = 120
    y_gap = 40

    전적_리스트 = list(전적_데이터.items())

    for idx, (항목, 값) in enumerate(전적_리스트):
        if 항목 in ['티어', 'RP']:
            continue

        index = idx - 2 if 항목 in ['티어', 'RP'] else idx

        if index % 2 == 0:
            x = col1_x
            y = y_start + (index // 2) * y_gap
        else:
            x = col2_x
            y = y_start + (index // 2) * y_gap

        draw.text((x, y), f"{항목}:", font=font_small, fill=sub_text_color)
        draw.text((x + 150, y), f"{값}", font=font_small, fill=text_color)

    # --- Eternal Return 로고 추가 ---
    try:
        logo_path = './logos/Logo_white.webp'
        logo_image = Image.open(logo_path).convert('RGBA')
        logo_resized = logo_image.resize((192,108))  # 크기 조정
        logo_x = img_width - logo_resized.width - 40  # 우측 여백
        logo_y = 25  # 상단 여백
        image.paste(logo_resized, (logo_x, logo_y), logo_resized)
    except Exception as e:
        print(f"로고 로드 실패: {e}")

    # --- 이미지 저장 ---
    image_bytes = io.BytesIO()
    image.save(image_bytes, format='PNG')
    image_bytes.seek(0)
    return image_bytes


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def 이리(ctx, 닉네임):
    service = Service(chrome_driver_path)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # 필요에 따라 제거 가능
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(service=service, options=options)

    try:
        # URL 인코딩 추가 (한글 닉네임 대응)
        from urllib.parse import quote
        encoded_nickname = quote(닉네임)

        url = f"https://er.dak.gg/profile/{encoded_nickname}"
        driver.get(url)

        # WebDriverWait 사용
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        wait = WebDriverWait(driver, 10)

        # RP 요소 가져오기
        RP_element = wait.until(EC.presence_of_element_located((
            By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[1]/div/b'
        )))
        RP = RP_element.text

        # 티어 + 티어_RP를 포함한 div 요소 가져오기
        티어_div = wait.until(EC.presence_of_element_located((
            By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[1]/div/div[1]'
        )))

        # 전체 텍스트 가져오기
        티어_texts = 티어_div.get_attribute('textContent').strip().split('\n')

        # 디버깅용: 텍스트가 어떻게 들어있는지 확인해보자!
        print("티어_texts:", 티어_texts)

        # 텍스트 노드 순서대로 할당 (index 0부터 시작)
        티어 = 티어_texts[0] if len(티어_texts) > 0 else '알 수 없음'
        티어_RP = 티어_texts[2] if len(티어_texts) > 2 else '알 수 없음'

        평균_TK = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[1]/div[2]')
        )).text

        승률 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[2]/div[2]')
        )).text

        게임수 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[3]/div[2]')
        )).text

        평균_킬 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[4]/div[2]')
        )).text

        TOP2 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[5]/div[2]')
        )).text

        평균_딜량 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[6]/div[2]')
        )).text

        평균_어시 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[7]/div[2]')
        )).text

        TOP3 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[8]/div[2]')
        )).text

        평균_순위 = wait.until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="content-container"]/div[2]/div[1]/section/div[2]/div[9]/div[2]')
        )).text

        # 전적 데이터 딕셔너리
        전적_데이터 = {
            "티어": 티어,            # 예: '미스릴 - 68 RP'
            "RP": RP,                # 예: '7068 RP'
            "평균 TK": 평균_TK,
            "게임 수": 게임수,
            "평균 킬": 평균_킬,
            "승률": 승률,
            "평균 어시스트": 평균_어시,
            "TOP 2 비율": TOP2,
            "평균 딜량": 평균_딜량,
            "TOP 3 비율": TOP3,
            "평균 순위": 평균_순위
        }

        티어_전체 = 전적_데이터["티어"]                  # 예: '골드 2 - 68 RP'
        티어_부분 = 티어_전체.split(" - ")[0]            # '골드 2'
        티어이름 = 티어_부분.split(" ")[0]               # '골드'

        # 이미지 생성
        img_file = create_stat_image(nickname=닉네임, 전적_데이터=전적_데이터, 티어이름=티어이름)

        # 디스코드 전송
        await ctx.send(file=discord.File(img_file, filename=f"{닉네임}_전적.png"))

    except Exception as e:
        print(f"❌ 전적 크롤링 실패: {e}")
        await ctx.send(f"❌ {닉네임}님의 전적 정보를 가져오지 못했어요!")

    finally:
        driver.quit()

load_dotenv()  # .env 파일 읽기
TOKEN = os.getenv('DISCORD_TOKEN')  # .env에서 토큰 값 가져오기
bot.run(TOKEN)
