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
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"Health Check Server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# === Secretsからの読み込み ===
TOKEN = os.environ['DISCORD_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# --- チャンネルIDの設定 ---
TARGET_CHANNEL_ID = 1361403076560425095

# === Geminiの設定 ===
genai.configure(api_key=GEMINI_API_KEY)
# 安全性フィルターを「すべて許可」に設定（日常会話でエラーを防ぐため）
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel('gemini-1.5-flash', safety_settings=safety_settings)

# --- AIへの指示書 ---
SYSTEM_INSTRUCTION = """
あなたは日本と台湾の文化、およびゲーム「King's Choice」に精通した、同盟「HuM」の親切な通訳者です。

【HuM独自の文化・用語】
・同盟名の「HuM」は日本語で「ハム」と読みます。文脈に応じて親しみやすく訳してください。
・「King's Choice」のゲーム用語（国力、親密度、イベント名など）を適切に翻訳してください。

【ルール】
1. 文脈を読み、自然な表現（例：「飯テロ」→「深夜放毒」、「お疲れ様」→「辛苦了」）を使ってください。
2. 仲間同士なので、親しみやすく温かいフレンドリーな口調にしてください。
3. 「かよちゃん」などの愛称や固有名詞は、相手の文化で最も自然で親愛の情がこもった呼び方にしてください。
4. 絵文字や顔文字は、その場の雰囲気を壊さないよう適切に維持、または現地の感覚に合わせて調整してください。
5. 「翻訳結果のみ」を回答し、挨拶や「はい、翻訳しました」「〜という意味です」といった解説は、どんな場合でも絶対に含めないでください。
6. もし元の文章が短すぎて意味が不明な場合でも、推測して最も自然な挨拶や返答として訳してください。

"""

# === ユーザーと言語の設定 ===
USER_LANG_MAP = {
    1355636991303352362: 'ja',    # 竜田
    1455034055228788737: 'ja',    # kayoko
    1429463236159475792: 'ja',    # Emmanue
    1432596792683528294: 'zh-tw', # 薩摩
    1432334719328059493: 'zh-tw', # Noelle
}

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

def send_webhook_with_embed(username, avatar_url, embed):
    """Webhook経由でEmbed（カード）を送信する関数"""
    if not WEBHOOK_URL:
        return
    data = {
        "username": username,
        "avatar_url": avatar_url,
        "embeds": [embed.to_dict()]
    }
    requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})

@bot.event
async def on_message(message):
    if message.author.bot or message.webhook_id or not message.content:
        return

    if message.channel.id != TARGET_CHANNEL_ID:
        await bot.process_commands(message)
        return

    text = message.content.strip()
    
    # 文字が含まれているかチェック
    if not re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7A3a-zA-Z]', text):
        return

    try:
        detected_lang = USER_LANG_MAP.get(message.author.id, 'ja')
        
        # ターゲット情報の組み立て
        if detected_lang == 'ja':
            target_lang = "繁体字中国語(台湾)"
            embed_color = 0xFDB933  # 鬱金色
            flag = "🇹🇼"
        else:
            target_lang = "日本語"
            embed_color = 0xE6EAEF  # 白緑柱石
            flag = "🇯🇵"

        # --- ✨ Geminiによる翻訳 ---
        prompt = f"{SYSTEM_INSTRUCTION}\n\n以下の文章を{target_lang}に翻訳して:\n{text}"
        # 非同期でGeminiを呼び出す
        response = await asyncio.to_thread(model.generate_content, prompt)
        translated_text = response.text.strip()

        # --- 🎨 Embed（カード）の作成 ---
        # 翻訳テキストだけを載せた、カラーラインつきのシンプルなカード
        embed = discord.Embed(
            description=translated_text,
            color=embed_color
        )

        # フッターに国旗の絵文字だけを添える
        embed.set_footer(text=flag)

        # Webhookで送信するデータを作成
        # contentに「原文（＋リプライ先）」を、embedsに「翻訳カード」をセットします
        formatted_content = f"{reply_header}{text}"

        data = {
            "username": message.author.display_name,
            "avatar_url": str(message.author.avatar.url) if message.author.avatar else None,
            "content": formatted_content,  # カードの上に原文を表示
            "embeds": [embed.to_dict()]    # 原文の下に翻訳カードを表示
        }
        
        # Webhook送信（URLにデータを飛ばします）
        requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})

        # 送信が終わったら、ユーザーが打った元のメッセージを削除して画面を整理
        await message.delete()

    except Exception as e:
        print(f"ERROR: {e}")

    await bot.process_commands(message)

# --- 以下、Healthcheckなどの関数は変更なし ---
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
    print(f'Logged in as {bot.user.name}')
    bot.loop.run_in_executor(None, send_healthcheck)

if __name__ == '__main__':
    bot.run(TOKEN)
