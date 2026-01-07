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
    "max_output_tokens": 500,     # 【重要】ウノさん推奨の出力制限
    "top_p": 0.95,
    "top_k": 40,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# モデルの定義
model = genai.GenerativeModel(
    model_name='gemini-2.5-flash',
    safety_settings=safety_settings,
    generation_config=generation_config
)

# --- AIへの指示書 (Gemini 2.5 Flash 最終調教版) ---
SYSTEM_INSTRUCTION = """
あなたはKing's Choiceで活動する同盟「HuM」の専属通訳「ダヴィンチ先生」です。
以下の【鉄の掟】を遵守し、発言者の感情を映す「鏡」として機能してください。

【鉄の掟：出力形式】
・**「翻訳後のテキストのみ」**を出力せよ。
・挨拶、解説、補足、代案、文法説明、辞書のような羅列は【厳禁】。
・「〜という意味です」「〜とも言えます」などの余計な一言は一切不要。
・原文が記号のみ、「www」などの場合は「SKIP」とだけ出力。

【鉄の掟：翻訳ルール】
・日本語以外の入力 → 自然な「日本語」へ翻訳。
・日本語の入力 → 台湾で使われる自然な「繁体字中国語」へ翻訳。
・**「オウム返し」の禁止**：日本語を日本語のまま、繁体字を繁体字のまま出力することは避け、必ず指定の言語へ翻訳すること。

【用語とスタイル】
・同盟名 (HuM, WIN, HAB, POL等) やサーバー番号 (155等) はそのまま維持。
・ゲーム用語は文脈に合わせる。
・原文の温度感を死守（無理に丁寧にせず、文脈に沿う場合はネットスラングも活用）。

【出力イメージ】
入力：うそぉ…🤣
出力：不會吧…🤣
"""

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
        # 以前の api_url や payload などの処理は、この下の model.generate_content がすべて兼ねています！
        translated_text = None
        for i in range(3): 
            try:
                # 2.5-flashモデルに指示文とテキストを送る
                response = model.generate_content(
                    f"SYSTEM_INSTRUCTION:\n{SYSTEM_INSTRUCTION}\n\nINPUT:\n{text}"
                )
                translated_text = response.text.strip()
                break 
            except Exception as e:
                if "429" in str(e) and i < 2:
                    print(f"【API制限】{i+1}回目のリトライ中... (3秒待機)")
                    time.sleep(3) 
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
