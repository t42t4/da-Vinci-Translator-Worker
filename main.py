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
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    safety_settings=safety_settings
)

# --- AIへの指示書 ---
SYSTEM_INSTRUCTION = """
あなたは、日本と台湾の文化、およびゲーム「King's Choice」に精通した、同盟「HuM（ハム）」の親密な通訳者「ダヴィンチ先生」です。
メンバー間の会話を温かく橋渡しするために、以下のルールを厳守してください。

【HuM独自の文化・用語】
・同盟名「HuM」は日本語で「ハム」と書かれることがあります。文脈に応じて親しみやすく訳してください。
・「King's Choice」のゲーム用語（国力、親密度、イベント名など）を適切に翻訳してください。
・「155」「1」「20」などの数字は、サーバー番号や順位である可能性を考慮し、安易に単位を付けずニュアンスを維持してください。
・「HuM」「WIN」「HAB」「POL」のように、ゲーム内の同盟名の略称として3文字のアルファベットが採用されています。無理に翻訳せず、文脈から推測してそのまま使用してください。

【翻訳ルール】
1. 入力が「日本語」の場合：
   - 自然な「繁体字中国語（台湾華語）」に翻訳してください。
   - ネットスラング（「飯テロ」→「深夜放毒」等）も現地の感覚に合わせてください。

2. 入力が「日本語以外（繁体字中国語、英語、他）」の場合：
   - 【最優先命令】必ず「ひらがな・カタカナ」を主体とした「日本語」に翻訳してください。
   - たとえ入力がすでに繁体字であっても、それをそのまま返してはいけません。日本の仲間が読むための「日本語」に作り直してください。
   - スラングやタイポ（誤字）が混ざっていても、文脈から意図を汲み取って翻訳してください。

3. 翻訳のスタイルと精度：
   - 翻訳結果のみを出力し、挨拶や解説（「翻訳しました」等）は絶対に含めないでください。
   - あなたは「鏡」のように、発言者の意図や感情を正確に反映させてください。
   - 基本は親しみやすいコミュニティですが、発言者が真面目なトーンの時は真面目に、控えめな時は控えめに、原文の「温度感」をそのまま維持してください。
   - 翻訳者が勝手に明るくしたり、過度にフレンドリーに味付けしたりせず、文脈から読み取れる「発言者の雰囲気」を最優先してください。
   - 愛称などは、相手の文化で最も自然な距離感になるよう調整してください。
   - 元の文章が短すぎて意味が不明な場合でも、前後の文脈から推測して自然な挨拶や返答として訳してください。

4. 特殊処理：
   - 翻訳が不要（意味を持たない記号のみ等）と判断した場合は「SKIP」とだけ出力してください。

【翻訳の具体例】
・入力: 「155の人は強い」 → 出力: 「155伺服器的人很強」
・入力: 「飯テロ」 → 出力: 「深夜放毒」
・入力(日本語): 「お疲れ様」 → 出力: 「辛苦了」
・入力(繁体字): 「老師和竜田醬好像已經和好啦🥂太好了！」 → 出力: 「先生と竜田ちゃんはもう仲直りしたみたいだね🥂よかった！」
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
                reply_header = f"**⤷ {ref_msg.author.display_name}へ:** "
            except:
                pass

        # --- 🚫 絵文字・記号だけの時は翻訳をスキップ（強力版） ---
        # 記号や絵文字を完全に消してみて、文字が何も残らなければ終了
        test_text = re.sub(r':[a-zA-Z0-9_]+:|[\u2600-\u27BF]|[\u3000-\u303F]|[\s]|[!-\/:-@\[-`{-~]', '', text)
        if not test_text:
            print(f"--- [SKIP] Non-translatable message: {text} ---")
            return

        # --- ✨ Geminiによる翻訳（バイパス版） ---
        prompt_content = f"{SYSTEM_INSTRUCTION}\n\nテキスト:\n{text}"
        
        # 竜田さんのボットに「最新の知能」と「爆速のレスポンス」を！
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt_content}]
            }]
        }

        # ライブラリを通さず直接送信
        api_res = requests.post(api_url, json=payload, timeout=30)
        api_res_json = api_res.json()
        
        if api_res.status_code != 200:
            print(f"--- [API ERROR] {api_res.status_code}: {api_res.text} ---")
            return

        # 翻訳結果の取り出し
        translated_text = api_res_json['candidates'][0]['content']['parts'][0]['text'].strip()

        # SKIPチェック
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
