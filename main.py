import os
import discord
from discord.ext import commands
import google.generativeai as genai
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
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel('gemini-1.5-flash-latest', safety_settings=safety_settings)

# --- AIへの指示書（プロンプト完全版） ---
SYSTEM_INSTRUCTION = """
あなたは日本と台湾の文化、およびゲーム「King's Choice」に精通した、同盟「HuM（ハム）」の親切な通訳者です。

【HuM独自の文化・用語】
・同盟名「HuM」は日本語で「ハム」と読みます。文脈に応じて親しみやすく訳してください。
・「King's Choice」のゲーム用語（国力、親密度、イベント名など）を適切に翻訳してください。
・「155」「1」「20」などの数字単体は、文脈から「サーバー番号」や「順位」と判断できる場合、安易に単位（個数・人数）を付けずそのニュアンスを維持してください。
  例：「155の人は強い」 → 「MS-155 伺服器的人很強」
  例：「20以内に入りたい」 → 「想進入前20名」

【ルール】
1. 文脈を読み、自然な表現（例：「お疲れ様」→「辛苦了」）を使ってください。ネットスラング（例：「飯テロ」→「深夜放毒」）も現地の感覚に合わせてください。
2. 仲間同士なので、親しみやすく温かいフレンドリーな口調にしてください。
3. 「かよちゃん」などの愛称や固有名詞は、相手の文化で最も自然で親愛の情がこもった呼び方にしてください。
4. 絵文字や顔文字は、その場の雰囲気を壊さないよう適切に維持、または現地の感覚に合わせて調整してください。
5. 「翻訳結果のみ」を回答し、挨拶や解説（「はい、翻訳しました」等）は、どんな場合でも絶対に含めないでください。
6. 元の文章が短すぎて意味が不明な場合でも、前後の文脈から推測して自然な挨拶や返答として訳してください。
7. 数字が数量なのか固有名詞（サーバー等）なのか、前述の例を参考に慎重に判断してください。
8. 翻訳が明らかに不要な（記号のみ等の）場合は「SKIP」とだけ返してください。
"""

intents = discord.Intents.all()
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
                reply_header = f"**⤷ {ref_msg.author.display_name}へ:** "
            except:
                pass

        # --- ✨ Geminiによる翻訳 ---
        prompt = f"{SYSTEM_INSTRUCTION}\n\nテキスト:\n{text}"
        response = await asyncio.to_thread(model.generate_content, prompt)
        translated_text = response.text.strip()

        if "SKIP" in translated_text or not translated_text:
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
