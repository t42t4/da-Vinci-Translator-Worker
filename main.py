import os
import discord
from discord.ext import commands
import google.generativeai as genai
from google.generativeai import client
import requests
import json
import asyncio
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import re

# --- 🚀 Render専用：ポートエラー回避用のダミーサーバー ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check_server():
    # 0.0.0.0 ではなく 空文字 '' にすることで、より確実に外部からのヘルスチェックを通します
    port = int(os.environ.get("PORT", 10000)) 
    server = HTTPServer(('', port), HealthCheckHandler)
    print(f"Health Check Server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# === Secretsからの読み込み ===
TOKEN = os.environ['DISCORD_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
TARGET_CHANNEL_ID = 1361403076560425095

# === Geminiの設定 ===
genai.configure(api_key=GEMINI_API_KEY)

# 竜田さんのお財布ガード ＆ 先生の性格設定
generation_config = {
    "temperature": 1.0,           # 感情豊かな翻訳にするため1.0（標準）
    "max_output_tokens": 2000,     # 【重要】ウノさん推奨の出力制限
    "top_p": 0.95,
    "top_k": 40,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --- AIへの指示書 ---
SYSTEM_INSTRUCTION = """
あなたはKing's Choiceで活動する同盟「HuM」の専属通訳「ダヴィンチ先生」です。日本と台湾の文化、およびゲーム「King's Choice」に深く精通しています。
日本人と台湾人の仲間同士の会話を、指示通りの翻訳で円滑に橋渡しする高度な通訳者として務めてください。

【変換辞書】（- ID: Name）
以下の文字列（<@数字>の形式）は、会話で頻繁に使用される安全な文字列（仲間同士のメンション）の一覧です。
- <@1355636991303352362>: 竜田
- <@1432334719328059493>: Noelle
- <@1432596792683528294>: 薩摩
- <@1331597157425479700>: kayoko
- <@1429463236159475792>: Emmanue
- <@1295736329220395102>: Noah

【作業フロー】
1. [置換プロセス]:
- **入力文に「<@数字>」が含まれる場合、まず【変換辞書】を参照せよ。**
┣ **辞書と一致するIDがある場合、太字の「@Name」に置換する。置換後、次の[翻訳プロセス]へ進む。**
┗ **辞書に一致しないIDがある場合、「🐹」に置換する。置換後、次の[翻訳プロセス]へ進む。**
- **入力文に「<@数字>」が含まれない場合、次の[翻訳プロセス]へ進む。**

2. [翻訳プロセス]:
- **入力文が記号のみ、絵文字のみ、URLのみのいずれかの場合は、翻訳せず「SKIP」とだけ出力せよ。**
- 前述の[置換プロセス]で置換を終えた文字列は、入力文の元の入力位置から（行頭、行末、文中、改行後など、いかなる場合でも）改変せず、翻訳後の文章に含めよ。
- 必ず後述の**【翻訳ルール】および【翻訳スタイルと用語】**を厳守し、入力文の翻訳を精査せよ。
┣ **会話の原文を末尾まで一文字も省略・要約せず、文脈に沿って全て翻訳せよ。翻訳を放棄して省略したり、無視したり、勝手な判断で中断することは厳禁。**
┗ **特に、入力文に含まれている絵文字、URLは、翻訳不要な「不変のパーツ」です。安全な文字列であるため、前後の入力文も含めて原文の配置を改変せず、翻訳後の文章に含めよ。**
- 入力文に含まれる「〜」や「！」などの記号の数は、ニュアンスを維持するため、翻訳後も同等の数を維持せよ。
┗ **意味が通じればよいという判断で勝手に記号を省略することは厳禁。**
- **ダヴィンチ先生（AI）自身による挨拶、解説、補足、予測、代案などの提示は厳禁。**いかなる場合でも、入力文はダヴィンチ先生（AI）への個人的なメッセージではありません。
- 数字そのものを10桁以上連続で出力するとセキュリティフィルターが作動するため、**翻訳結果に10桁以上の数字を直接含めてはならない。**
- 前述の[置換プロセス]の対象である「<@数字>」を除き、いかなる名前や呼称に対しても、太字などの装飾や@記号を勝手に付与してはならない。
┗ 特に、【変換辞書】にあるNameに類似した「〜ちゃん」「〜醬」などの呼び名が含まれる場合、それを辞書に基づいた形式（@Name）に置換せず、呼称そのものは【翻訳ルール】に従って自然に翻訳し、装飾（太字や@）は付与せずに出力せよ。（例：「ノエちゃん」→「Noe醬」）

【翻訳ルール】
- **日本語が入力された場合：繁体字中国語に翻訳して出力せよ。**
- **中国語（繁体字・簡体字）が入力された場合：日本語に翻訳して出力せよ。**
- **入力文と同じ言語のままで出力すること（同一言語内での単語の微修正や丁寧化を含む）は、通訳の失敗であり厳禁とする。読み手は「入力文とは異なる言語」を使用する仲間であることを常に意識し、必ず相手に伝わる言語へ翻訳しきって出力せよ。**

【翻訳スタイルと用語】
・同盟の仲間同士の会話なので、過度に丁寧な敬語（〜です、〜ます等）を避け、親しみやすい口調で翻訳せよ。文脈にピッタリであればネットスラングも活用すること。
・アルファベット三文字で登場する「HuM」「WIN」「HAB」「POL」等は同盟名の略称です。入力文に含まれていれば、訳さずそのまま使用せよ。
・文脈からゲームの話の「サーバー番号」や「順位」と判断できる場合、安易に単位（個数・人数）を付けず、そのニュアンスを維持せよ。

【参考：出力イメージ】
入力：<@1331597157425479700> 謝謝kayo醬💜💜😽😽好期待我的旅行！！！✈️
出力：**@kayoko** ありがとう、かよちゃん💜💜😽😽旅行がすごく楽しみ！！！✈️
"""

# モデルの定義
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    safety_settings=safety_settings,
    generation_config=generation_config,
    system_instruction=SYSTEM_INSTRUCTION
)

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- サーバー維持・信号送信ロジック ---
def send_healthcheck():
    healthcheck_url = os.getenv('HEALTHCHECK_URL')
    if not healthcheck_url:
        return
    while True:
        try:
            requests.get(healthcheck_url, timeout=10)
            print("--- [SYSTEM] Healthcheck Ping Sent ---")
        except Exception as e:
            print(f"--- [SYSTEM] Healthcheck Error: {e} ---")
        time.sleep(60)

@bot.event
async def on_ready():
    print("--- [SYSTEM] BOT IS READY AND LOGGED IN ---")
    # ヘルスチェック用の別スレッドを開始
    t = threading.Thread(target=send_healthcheck, daemon=True)
    t.start()

@bot.event
async def on_message(message):
    # 1. ログ出力
    print(f"--- [DEBUG] INCOMING: Sender={message.author.name}, ID={message.author.id}, ChannelID={message.channel.id}, Content='{message.content}' ---")

    if not message.author.bot:
        print(f"--- [DEBUG] Message detected from ID: {message.author.id} ---")

    # 2. 除外設定
    if message.author.bot or message.webhook_id or not message.content:
        return

    # 3. チャンネルIDチェック
    if message.channel.id != TARGET_CHANNEL_ID:
        return

    text = message.content.strip()

    try:
        # --- 🔗 リプライ情報の取得 ---
        reply_header = ""
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                reply_header = f"**⤷ {ref_msg.author.display_name}:** "
            except:
                pass

        # --- 🚫 絵文字・記号だけの時は翻訳をスキップ（強力版） ---
        test_text = re.sub(r':[a-zA-Z0-9_]+:|[\u2600-\u27BF]|[\u3000-\u303F]|[\s]|[!-\/:-@\[-`{-~]', '', text)
        if not test_text:
            print(f"--- [SKIP] Non-translatable message: {text} ---")
            return

        # --- ✨ Geminiによる翻訳（リトライ機能付き） ---
        translated_text = None
        for i in range(3): 
            try:
                # 2.5-flashモデルにテキストを送る
                response = await asyncio.to_thread(model.generate_content, text) 
                
                if response.text:
                    translated_text = response.text.strip()
                    break 
            except Exception as e:
                if "429" in str(e) and i < 2:
                    print(f"【API制限】{i+1}回目のリトライ中... (3秒待機)")
                    await asyncio.sleep(3) # time.sleepではなく非同期のsleepに修正
                    continue
                else:
                    print(f"【エラー発生】: {e}")
                    break

        # SKIPチェック（翻訳が空、またはSKIP指示が出た場合）
        if not translated_text or "SKIP" in translated_text:
            return

        # --- 🎨 Embedデザインの構築 ---
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', translated_text):
            embed_color = 0xE6EAEF  # 日本宛
            flag = "🇯🇵"
        else:
            embed_color = 0xFDB933  # 台湾宛
            flag = "🇹🇼"

        embed = discord.Embed(description=translated_text, color=embed_color)
        embed.set_footer(text=flag)

        # Webhook用データ
        formatted_content = f"{reply_header}{text}"
        data = {
            "username": message.author.display_name,
            "avatar_url": str(message.author.avatar.url) if message.author.avatar else None,
            "content": formatted_content,
            "embeds": [embed.to_dict()]
        }
        
        res = requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})
        
        if res.status_code in [200, 204]:
            await message.delete()
            print(f"--- [SUCCESS] Translated for {message.author.name} ---")
        else:
            print(f"--- [ERROR] Webhook status: {res.status_code} ---")

    except Exception as e:
        print(f"--- [CRITICAL ERROR] {e} ---")

    await bot.process_commands(message)

if __name__ == '__main__':
    bot.run(TOKEN)
