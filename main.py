import os
import discord
from threading import Thread
from discord.ext import commands
from googletrans import Translator
import requests
import json
import asyncio
import time

# === Secretsからの読み込み (DISCORD_TOKEN, WEBHOOK_URL) ===
TOKEN = os.environ['DISCORD_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# WEBHOOK_URLが設定されていない場合はログを出力
if not WEBHOOK_URL:
    print("🚨🚨🚨 WARNING: WEBHOOK_URL not set. Check configuration. 🚨🚨🚨")

# === ユーザーIDと言語のペルソナ設定 ===
# 設定されていないユーザーは自動判定（フォールバック）します
USER_LANG_MAP = {
    # ユーザーIDをキーに、話す言語コード（'ja' または 'zh-tw'）を設定します
    # 日本語ユーザー
    1355636991303352362: 'ja', 
    # 台湾華語ユーザー
    1432596792683528294: 'zh-tw', 
}
# =========================================================

# 1. ボットの初期設定
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix='!', intents=intents)

# 2. 翻訳クラスのインスタンス化
translator = Translator()

# 4. Webhookを使ったメッセージ送信関数
def send_webhook_message(username, avatar_url, content):
    """Webhookを使って、指定されたユーザー名とアイコンでメッセージを送信します。"""
    if not WEBHOOK_URL:
        print("Webhook URL is missing, skipping message send.")
        return
        
    data = {
        "username": username,
        "avatar_url": avatar_url,
        "content": content
    }
    
    response = requests.post(
        WEBHOOK_URL,
        data=json.dumps(data),
        headers={"Content-Type": "application/json"}
    )
    
    if response.status_code != 204:
        print(f"Webhook ERROR: status code {response.status_code}, response: {response.text}")

# 5. メッセージ受信時の自動翻訳イベント
@bot.event
async def on_message(message):
    # 1. ボット自身のメッセージ、Webhook、または空のメッセージは無視
    if message.author.bot or message.webhook_id or not message.content:
        return

    text = message.content 

    try:
        # === A. ユーザーIDマップから言語を取得 (ペルソナ設定を絶対視) ===
        # if message.author.id not in USER_LANG_MAP:
        #     return # ペルソナ設定のないユーザーは処理しない
        
        # ペルソナ設定を検出言語コードとして強制適用
        detected_lang_code = USER_LANG_MAP.get(message.author.id, 'ja')

        # === B. 翻訳ペアの決定 ===
        
        # 日本語ペルソナ ➡️ 台湾華語
        if detected_lang_code == 'ja':
            target_lang_code = 'zh-tw'
            target_lang_name = "Taiwanese Mandarin"
            
        # 台湾華語ペルソナ ➡️ 日本語
        elif detected_lang_code == 'zh-tw':
            target_lang_code = 'ja'
            target_lang_name = "Japanese"

        # 翻訳ペアがない場合は処理終了（USER_LANG_MAPにja/zh-tw以外が設定された場合など）
        if target_lang_code is None:
            return 

        # 翻訳の実行
        translated_result = translator.translate(text, src=detected_lang_code, dest=target_lang_code)
        translated_text = translated_result.text

        # 翻訳結果が空だった場合は、エラーメッセージを返すことで、ユーザーに問題を知らせ、処理を中断する
        if not translated_text:
            print("🚨🚨🚨 WARNING: Translator returned empty text.")
            # メッセージの削除を防ぐため、ここで return
            return 

        # Webhookで再投稿するためのメッセージを作成 (Markdownによる整形)
        
        # 1. 翻訳先の国旗絵文字の決定
        flag_emoji = ""
        if target_lang_code == 'ja':
            flag_emoji = "🇯🇵"
        elif target_lang_code == 'zh-tw':
            flag_emoji = "🇹🇼"
            
        # 2. 引用装飾の決定 (原文に改行が1つでも含まれていたら >>> を使用)
        if '\n' in text:
            quote_prefix = ">>> "
        else:
            quote_prefix = "> "
            
        # 3. メッセージの整形（原文 + 1行改行 + 引用訳文）
        formatted_message = (
            f"{text}" # 原文
            f"\n{quote_prefix}{flag_emoji}：{translated_text}"
        )

        # Webhook送信を別スレッドで実行
        # Webhookの実行をメッセージ削除の前に行うことで、競合を防ぎます
        await asyncio.to_thread(
            send_webhook_message,
            message.author.display_name, 
            str(message.author.avatar.url) if message.author.avatar else None,
            formatted_message
        )
        
        # 元のメッセージを削除
        # Webhookが完了した後に削除を実行
        await message.delete()

    except Exception as e:
        # 翻訳や削除、Webhook送信に失敗した場合のログ
        print(f"ERROR: Translation process failed: {e}")

    # Webhook URLが設定されていない場合の致命的エラー警告
    if WEBHOOK_URL is None:
        print("🚨🚨🚨 FATAL: Auto-transration failed. WEBHOOK_URL not set. 🚨🚨🚨")

    await bot.process_commands(message)

# === 24時間稼働用のWebサーバー設定（IPチェック機能なしの簡易版）===
from flask import Flask, request

app = Flask('')

# === Healthchecks.io への1分ごとの Ping 送信関数 ===
def send_healthcheck():
    healthcheck_url = os.getenv('HEALTHCHECK_URL')
    if not healthcheck_url:
        print("HEALTHCHECK_URL not set.")
        return

    while True:
        try:
            # Ping URL にアクセスすることで、生存信号を送る
            requests.get(healthcheck_url, timeout=10)

            # 常時稼働を確認
            print("HEALTHCHECK: Ping sent. Bot is running.")

        except requests.exceptions.RequestException as e:
            print(f"Healthcheck Ping Failre: {e}")

        # 1分（60秒）待機
        time.sleep(60)

@bot.event
async def on_ready():
    print('Logged in')
    print('Auto-translation mode is now active')

    # スレッドを直接立てるのをやめ、イベントループにタスクとして登録
    bot.loop.run_in_executor(None, send_healthcheck)
# -----------------------------------------------------------------

# 24時間稼働開始
if __name__ == '__main__':

# 6. ボットを実行 (Flaskサーバーは bot.run の実行とは関係なく、Renderのヘルスチェックを受ける)
    bot.run(TOKEN)
