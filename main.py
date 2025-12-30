import os
import discord
from discord.ext import commands
from googletrans import Translator
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
# --------------------------------------------------

# === Secretsからの読み込み ===
TOKEN = os.environ['DISCORD_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# --- 【追加】LivingチャンネルのID ---
TARGET_CHANNEL_ID = 1361403076560425095

if not WEBHOOK_URL:
    print("🚨🚨🚨 WARNING: WEBHOOK_URL not set. 🚨🚨🚨")

# === ユーザーIDと言語のペルソナ設定 ===
USER_LANG_MAP = {
    1355636991303352362: 'ja',    # 竜田
    1455034055228788737: 'ja',    # kayoko
    1429463236159475792: 'ja',    # Emmanue
    1432596792683528294: 'zh-tw', # 薩摩
    1432334719328059493: 'zh-tw', # Noelle
}

# === 翻訳辞書（ニックネームや特殊用語の矯正） ===
# 左側に「Google翻訳が出しそうな誤訳」、右側に「正しい表記」を書きます
FIX_DICT = {
    'カヨソース': 'かよちゃん',
    '嘉代ソース': 'かよちゃん',
    'kayoソース': 'かよちゃん',
    'Kayoソース': 'かよちゃん',
}

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)
translator = Translator()

def send_webhook_message(username, avatar_url, content):
    if not WEBHOOK_URL:
        return
    data = {"username": username, "avatar_url": avatar_url, "content": content}
    response = requests.post(WEBHOOK_URL, data=json.dumps(data), headers={"Content-Type": "application/json"})
    if response.status_code != 204:
        print(f"Webhook ERROR: {response.status_code}")

@bot.event
async def on_message(message):
    # ボット自身、Webhook、内容なしは無視
    if message.author.bot or message.webhook_id or not message.content:
        return

    # --- 【重要】Livingチャンネル以外での発言は完全にスルーする ---
    if message.channel.id != TARGET_CHANNEL_ID:
        await bot.process_commands(message)
        return

    # 絵文字判定
    text = message.content.strip()
    
    # 文字（言語）が含まれているかチェック
    has_content = re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uAC00-\uD7A3a-zA-Z]', text)

    if not has_content:
        # 絵文字や記号のみの場合はここで終了（翻訳せずに無視）
        return

    try:
        # リプライ先の情報を取得する処理
        reply_header = ""
        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            # リプライ先がメッセージとして存在する場合
            if isinstance(ref_msg, discord.Message):
                # 相手の表示名を「>> @名前」の形式で用意
                reply_header = f"**>> @{ref_msg.author.display_name}**\n"

        detected_lang_code = USER_LANG_MAP.get(message.author.id, 'ja')
        target_lang_code = None

        if detected_lang_code == 'ja':
            target_lang_code = 'zh-tw'
            flag_emoji = "🇹🇼"
        elif detected_lang_code == 'zh-tw':
            target_lang_code = 'ja'
            flag_emoji = "🇯🇵"

        if target_lang_code is None:
            return 
        # --- 翻訳処理（リトライ機能付き） ---
        translated_text = None
        max_retries = 3
        
        for i in range(max_retries):
            try:
                # 翻訳を実行
                translated_result = translator.translate(text, src=detected_lang_code, dest=target_lang_code)
                if translated_result and translated_result.text:
                    translated_text = translated_result.text
                    break
            except Exception as e:
                # 英語でのエラーログ出力
                print(f"Translation attempt {i+1}/{max_retries} failed: {e}")
                if i < max_retries - 1:
                    await asyncio.sleep(1) # 1秒待って再試行

        # 3回試してもダメだった場合の最終警告
        if not translated_text:
            print(f"ERROR: All {max_retries} translation attempts failed for user {message.author.id}")
            return 

        # 翻訳結果を辞書に基づいて置換する
        for wrong, right in FIX_DICT.items():
            translated_text = translated_text.replace(wrong, right)

        if not translated_text:
            return 

        # 先頭に reply_header を合体させる
        quote_prefix = ">>> " if '\n' in text else "> "
        formatted_message = f"{reply_header}{text}\n{quote_prefix}{flag_emoji}：{translated_text}"

        await asyncio.to_thread(
            send_webhook_message,
            message.author.display_name, 
            str(message.author.avatar.url) if message.author.avatar else None,
            formatted_message
        )
        await message.delete()

    except Exception as e:
        print(f"ERROR: {e}")

    await bot.process_commands(message)

# Healthchecks.io への Ping 送信
def send_healthcheck():
    healthcheck_url = os.getenv('HEALTHCHECK_URL')
    if not healthcheck_url:
        return
    while True:
        try:
            requests.get(healthcheck_url, timeout=10)
            print("HEALTHCHECK: Ping sent.")
        except Exception as e:
            print(f"Healthcheck Failre: {e}")
        time.sleep(60)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    bot.loop.run_in_executor(None, send_healthcheck)

if __name__ == '__main__':
    bot.run(TOKEN)
