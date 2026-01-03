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

# 2026-01-03: デバッグ用ログを英語に変更して再デプロイテスト

# --- 🚀 Render専用：ポートエラー回避用のダミーサーバー ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health Check Server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# === Secretsからの読み込み ===
TOKEN = os.environ['DISCORD_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# --- 📌 チャンネルIDの設定 ---
TARGET_CHANNEL_ID = 1361403076560425095

# === Geminiの設定 ===
genai.configure(api_key=GEMINI_API_KEY)
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel('gemini-1.5-flash', safety_settings=safety_settings)

# --- AIへの指示書（プロンプト） ---
SYSTEM_INSTRUCTION = """
あなたは日本と台湾の文化、およびゲーム「King's Choice」に精通した、同盟「HuM」の親切な通訳者です。

【HuM独自の文化・用語】
・同盟名の「HuM」は日本語で「ハム」と読みます。文脈に応じて親しみやすく訳してください。
・「King's Choice」のゲーム用語（国力、親密度、イベント名など）を適切に翻訳してください。
・文脈の中で「155」や「1」「20」など、数字単体で特定の番号（サーバー番号やランキング順位）を指している場合、安易に「個数」や「人数」などの単位を付け加えないでください。文脈から「場所（サーバー）」や「順位」だと判断できる場合は、そのニュアンスを維持して翻訳してください。
  例：「155の人は強い」 → 「MS-155 伺服器的人很強」
  例：「20以内に入りたい」 → 「想進入前20名」

【ルール】
1. 文脈を読み、自然な表現（例：「飯テロ」→「深夜放毒」、「お疲れ様」→「辛苦了」）を使ってください。
2. 仲間同士なので、親しみやすく温かいフレンドリーな口調にしてください。
3. 「かよちゃん」などの愛称や固有名詞は、相手の文化で最も自然で親愛の情がこもった呼び方にしてください。
4. 絵文字や顔文字は、その場の雰囲気を壊さないよう適切に維持、または現地の感覚に合わせて調整してください。
5. 「翻訳結果のみ」を回答し、挨拶や「はい、翻訳しました」「〜という意味です」といった解説は、どんな場合でも絶対に含めないでください。
6. もし元の文章が短すぎて意味が不明な場合でも、推測して最も自然な挨拶や返答として訳してください。
7. 数字が含まれる場合、それが数量（個数・人数）なのか、固有名詞（サーバー番号・順位）なのかを文脈から慎重に判断してください。
"""

# === 🛡️ Intentsの修正（ここを all に変更しました） ===
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_message(message):
    # --- 🔍 Renderログ用実況（IDチェックの前に移動） ---
    # これにより、どのチャンネルで発言しても必ずログに表示されます
    if not message.author.bot:
        print(f"--- [DEBUG] Received message from: {message.author.id} ---")
                                                                                     
    # ボット自身、または内容が空の場合は無視
    if message.author == bot.user or not message.content:
        return

    # 指定チャンネル以外は無視（ログで確認できるよう、この下に配置）
    if message.channel.id != TARGET_CHANNEL_ID:
        return

    text = message.content.strip()
    
    # 翻訳対象の文字（日本語・繁体字・ハングル）が含まれているかチェック
    if not re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7A3]', text):
        return

    try:
        # --- リプライ情報の取得 ---
        reply_header = ""
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                reply_header = f"**⤷ {ref_msg.author.display_name}へ:** "
            except:
                pass

        # --- ✨ Geminiによる翻訳 ---
        prompt = (
            f"{SYSTEM_INSTRUCTION}\n\n"
            f"以下のルールで翻訳してください：\n"
            f"1. 入力が日本語なら、繁体字中国語(台湾)に翻訳してください。\n"
            f"2. 入力が中国語なら、日本語に翻訳してください。\n"
            f"3. 翻訳が不要な場合は「SKIP」とだけ返してください。\n\n"
            f"テキスト:\n{text}"
        )
        
        response = await asyncio.to_thread(model.generate_content, prompt)
        translated_text = response.text.strip()

        if "SKIP" in translated_text:
            return

        # --- 🎨 翻訳後の文字を見てカードのデザインを決定 ---
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', translated_text):
            embed_color = 0xE6EAEF  # 日本語宛
            flag = "🇯🇵"
        else:
            embed_color = 0xFDB933  # 台湾宛
            flag = "🇹🇼"

        # --- 🎨 Embed（カード）の作成 ---
        embed = discord.Embed(description=translated_text, color=embed_color)
        embed.set_footer(text=flag)

        # Webhookで送信
        formatted_content = f"{reply_header}{text}"
        data = {
            "username": message.author.display_name,
            "avatar_url": str(message.author.avatar.url) if message.author.avatar else None,
            "content": formatted_content,
            "embeds": [embed.to_dict()]
        }
        
        webhook_res = requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})
        
        if webhook_res.status_code in [200, 204]:
            await message.delete()
            print(f"SUCCESS: Translated for {message.author.name}")
        else:
            print(f"ERROR: Webhook returned {webhook_res.status_code}")

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

    await bot.process_commands(message)

# --- サーバー維持・起動 ---
def send_healthcheck():
    healthcheck_url = os.getenv('HEALTHCHECK_URL')
    if not healthcheck_url: return
    while True:
        try:
            requests.get(healthcheck_url, timeout=10)
        except: pass
        time.sleep(60)

@bot.event
async def on_ready():
    print("--- BOT IS READY ---")
    # ヘルスチェック用の別スレッドを開始
    t = threading.Thread(target=send_healthcheck, daemon=True)
    t.start()

if __name__ == '__main__':
    bot.run(TOKEN)
