from datetime import date, timedelta
import os
import random
import asyncio
import aiohttp
from telethon import TelegramClient, events, functions, types, Button
import subprocess
from dotenv import load_dotenv
from db.database import User

load_dotenv()

API_ID = int(os.getenv('API_ID'))       
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CRYPTO_BOT_TOKEN = os.getenv('CRYPTO_BOT_TOKEN') 
DB_URL = os.getenv('DB_URL')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin') 

if not API_ID or not BOT_TOKEN:
    raise ValueError("CRITICAL ERROR: .env file is missing or empty!")

client = TelegramClient('bot_session_db', API_ID, API_HASH)

processed_invoices = set()

async def register_user(event):
    """Ensures user exists in DB on every interaction."""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id
    user, _ = await User.get_or_create(
        id=uid,
        defaults={
            'username': getattr(sender, 'username', None), 
            'first_name': getattr(sender, 'first_name', 'User')
        }
    )
    return user

async def create_crypto_invoice(amount, currency, description, payload):
    """
    Creates an invoice using CryptoPay API with Fiat support.
    currency: 'RUB', 'USD', 'EUR' (Fiat) OR 'USDT', 'TON' (Crypto)
    """
    if not CRYPTO_BOT_TOKEN:
        print("Error: CRYPTO_BOT_TOKEN is missing in .env")
        return None
        
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN}
    
    data = {
        "amount": str(amount),
        "description": description,
        "payload": payload,
        "allow_comments": False,
        "allow_anonymous": False,
        "expires_in": 3600 # 1 hour
    }

    known_crypto_assets = ["USDT", "TON", "BTC", "ETH", "USDC", "LTC", "BNB"]
    
    if currency.upper() in known_crypto_assets:
        data["asset"] = currency.upper()
        data["currency_type"] = "crypto"
    else:
        data["fiat"] = currency.upper()
        data["currency_type"] = "fiat"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                result = await response.json()
                if result.get('ok'):
                    return result['result']
                print(f"CryptoBot API Error: {result}")
                return None
    except Exception as e:
        print(f"CryptoBot Connection Error: {e}")
        return None

async def check_crypto_payments():
    """
    Background task: Checks for PAID invoices every 30 seconds.
    """
    print("✅ Crypto Payment Monitor Started...")
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN}
    

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                params = {'status': 'paid', 'count': 20}
                async with session.get(url, headers=headers, params=params) as response:
                    data = await response.json()
                    
                    if data.get('ok'):
                        invoices = data['result']['items']
                        
                        for inv in invoices:
                            invoice_id = inv['invoice_id']
                            payload = inv.get('payload', '')
                            paid_at_str = inv.get('paid_at') 

                            if invoice_id in processed_invoices:
                                continue
                            
                            processed_invoices.add(invoice_id)
                            
                            if payload and payload.startswith('premium_sub_'):
                                try:
                                    user_id = int(payload.split('_')[-1])
                                    
                                    user = await User.get_or_none(id=user_id)
                                    if user:

                                        user.is_premium = True
                                        
                                        current_expiry = user.premium_expiry_date
                                        if current_expiry and current_expiry > date.today():
                                            user.premium_expiry_date = current_expiry + timedelta(days=365)
                                        else:
                                            user.premium_expiry_date = date.today() + timedelta(days=365)
                                            
                                        await user.save()
                                        
                                        await client.send_message(
                                            user_id,
                                            "🎉 **Payment Received (Crypto)!**\n\n"
                                            "You are now a Premium user for 1 Year.\n"
                                            "Thank you for your support!"
                                        )
                                        print(f"💰 Crypto Premium Activated for {user_id} (Inv: {invoice_id})")
                                        
                                except Exception as inner_e:
                                    print(f"Error activating user {payload}: {inner_e}")

            await asyncio.sleep(30)
            
        except Exception as e:
            print(f"Crypto Monitor Error: {e}")
            await asyncio.sleep(30) 


@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await register_user(event)
    
    text = (
        f"✨ **Hello, {user.first_name}!**\n\n"
        "I create round video notes for you with saving of entered caption.\n"
        "Send me a video and text in one message to get started!\n\n"
        "*this bot doesn't support premium emojis, instead consider buying premium subscription (covering premium account expenses) and use @roundnote!*\n\n"
        "👇 **Choose an option below:**"
    )
    
    buttons = [
        [Button.inline("💎 Premium Features", data=b"menu_premium")],
        [Button.inline("🆘 Help / Support", data=b"menu_help")]
    ]
    
    await event.respond(text, buttons=buttons)

@client.on(events.CallbackQuery)
async def menu_handler(event):
    """Handles all button clicks."""
    data = event.data.decode('utf-8')
    user = await register_user(event) 
    sender_id = event.sender_id

    if data == "menu_main":
        text = (
            f"✨ **Hello, {user.first_name}!**\n\n"
            "I create round video notes for you with saving of entered caption.\n"
            "Send me a video and text in one message to get started!\n\n"
            "*this bot doesn't support premium emojis, instead consider buying premium subscription (covering premium account expenses) and use @roundnote!*\n\n"
            "👇 **Choose an option below:**"
        )
        buttons = [
            [Button.inline("💎 Premium Features", data=b"menu_premium")],
            [Button.inline("🆘 Help / Support", data=b"menu_help")]
        ]
        await event.edit(text, buttons=buttons)

    elif data == "menu_help":
        text = (
            "🆘 **Support**\n\n"
            "If you are having trouble, please contact the admin directly.\n\n"
            f"👤 Admin: @{ADMIN_USERNAME}"
        )
        buttons = [[Button.inline("🔙 Back", data=b"menu_main")]]
        await event.edit(text, buttons=buttons)

    elif data == "menu_premium":
        is_active = (
            user.is_premium and 
            user.premium_expiry_date and 
            user.premium_expiry_date >= date.today()
        )

        if is_active:
            expiry_str = user.premium_expiry_date.strftime("%Y-%m-%d")
            text = (
                "💎 **Premium Status Active**\n\n"
                "✅ You are already a Premium user!\n"
                f"📅 Expires on: **{expiry_str}**\n\n"
                "Enjoy unlimited video conversions, priority processing and access to @roundnote."
            )
            buttons = [[Button.inline("🔙 Back", data=b"menu_main")]]
            await event.edit(text, buttons=buttons)
        else:
            if user.is_premium:
                user.is_premium = False
                await user.save()
                
            text = (
                "💎 **Premium Subscription**\n\n"
                "✅ Unlimited daily video conversions\n"
                "✅ Priority processing\n"
                "✅ No ads\n\n"
                "✅ !!! Access to @undernote bot, that supports premium emojis as captions\n\n"
                "**Select a payment method:**\n"
                "• 🇷🇺 RUB: 99₽ (via Crypto)\n"
                "• 🌍 USD: $1.70 (via Crypto)\n"
                "• ⭐️ Stars: 100"
            )
            buttons = [
                [Button.inline("🇷🇺 Pay 99 RUB", data=b"buy_crypto_rub"),
                 Button.inline("🌍 Pay $1.70", data=b"buy_crypto_usd")],
                
                [Button.inline("⭐️ Pay 100 Stars", data=b"buy_stars")],
                [Button.inline("🔙 Back", data=b"menu_main")]
            ]
            await event.edit(text, buttons=buttons)

    elif data == "buy_stars":
        await event.answer("Creating Invoice...", alert=False)
        try:
            invoice_media = types.InputMediaInvoice(
                title="Premium Subscription",
                description="1 Year Access",
                invoice=types.Invoice(
                    currency="XTR",
                    prices=[types.LabeledPrice(label="1 Year", amount=100)],
                    test=False, 
                ),
                payload=f"premium_sub_{sender_id}".encode('utf-8'),
                provider="",
                provider_data=types.DataJSON(data="{}"),
                start_param="premium_sub"
            )

            await client(functions.messages.SendMediaRequest(
                peer=event.chat_id,
                media=invoice_media,
                message="",
                random_id=random.randint(0, 2**63 - 1)
            ))
            
        except Exception as e:
            print(f"Stars Error: {e}")
            await event.respond(f"Error creating Stars invoice: {e}")

    elif data == "buy_crypto_rub":
        await event.answer("Generating Link (RUB)...", alert=False)
        
        invoice = await create_crypto_invoice(
            amount=99.00,
            currency="RUB",
            description="Premium Subscription (1 Year)",
            payload=f"premium_sub_{sender_id}"
        )
        
        if invoice:
            pay_url = invoice['bot_invoice_url']
            await event.respond(
                "💳 **Pay 99 RUB via Crypto**\n\n"
                "The bot will automatically convert RUB to USDT/TON for you.",
                buttons=[[Button.url("👉 Pay 99 RUB", pay_url)]]
            )
        else:
            await event.respond("⚠️ Error generating invoice. Please check bot settings.")

    elif data == "buy_crypto_usd":
        await event.answer("Generating Link (USD)...", alert=False)
        
        invoice = await create_crypto_invoice(
            amount=1.70,
            currency="USD",
            description="Premium Subscription (1 Year)",
            payload=f"premium_sub_{sender_id}"
        )
        
        if invoice:
            pay_url = invoice['bot_invoice_url']
            await event.respond(
                "💳 **Pay $1.70 via Crypto**\n\n"
                "The bot will automatically convert USD to USDT/TON for you.",
                buttons=[[Button.url("👉 Pay $1.70", pay_url)]]
            )
        else:
            await event.respond("⚠️ Error generating invoice. Please check bot settings.")

def process_video_v2(input_path, output_path):
    command = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', "crop='min(iw,ih):min(iw,ih)',scale=400:400",
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
        '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart',
        output_path
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"FFmpeg Error: {e}")
        return False

@client.on(events.NewMessage)
async def video_handler(event):
    if event.text and event.text.startswith('/') or not event.video or not event.is_private:
        return

    user = await register_user(event)
    today = date.today()

    if user.last_use_date != today:
        user.done_today = 0
        user.last_use_date = today
        await user.save()

    is_subscription_active = (
        user.is_premium and 
        user.premium_expiry_date and 
        user.premium_expiry_date >= date.today()
    )
    
    if not is_subscription_active and user.is_premium:
        user.is_premium = False
        await user.save()

    if not is_subscription_active and user.done_today >= 3:
        await event.respond(
            "🚫 **Daily Limit Reached!**\n\nYou have used your 3 free videos for today.",
            buttons=[Button.inline("💎 Upgrade to Premium", data=b"menu_premium")]
        )
        return

    duration = 0
    if hasattr(event.video, 'attributes'):
        for attr in event.video.attributes:
            if isinstance(attr, types.DocumentAttributeVideo):
                duration = attr.duration
                break
    
    if duration > 60:
        return await event.respond("❌ **Video is too long!** Maximum length for round notes is 60 seconds.")

    status_msg = await event.respond("⏳ **Processing...**")
    
    path_in = f"in_{event.id}_{random.randint(100,999)}.mp4"
    path_out = f"out_{event.id}_{random.randint(100,999)}.mp4"

    try:
        await event.download_media(file=path_in)
        await status_msg.edit("⚙️ **Cropping...**")
        
        success = await asyncio.to_thread(process_video_v2, path_in, path_out)
        
        if not success or not os.path.exists(path_out):
            raise Exception("FFmpeg processing failed.")
        
        await status_msg.edit("⬆️ **Uploading...**")
        uploaded_file = await client.upload_file(path_out)

        video_attribute = types.DocumentAttributeVideo(
            duration=duration, 
            w=400, h=400, 
            round_message=True 
        )

        await client(functions.messages.SendMediaRequest(
            peer=await event.get_input_chat(),
            media=types.InputMediaUploadedDocument(
                file=uploaded_file, mime_type='video/mp4', attributes=[video_attribute]
            ),
            message=event.message.message or "",
            entities=event.message.entities,
            random_id=random.randint(0, 2**63 - 1)
        ))

        if not is_subscription_active:
            await client(functions.messages.SendMessageRequest(
                peer=await event.get_input_chat(),
                message="💡 Result only visible on Telegram Mobile.",
                random_id=random.randint(0, 2**63 - 1)
            ))

        user.done_today += 1
        await user.save()
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** {str(e)}")
    finally:
        for p in [path_in, path_out]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

@client.on(events.Raw)
async def pre_checkout_handler(event):
    """
    Approves the payment immediately when the user clicks 'Pay'.
    """
    if isinstance(event, types.UpdateBotPrecheckoutQuery):
        try:
            await client(functions.messages.SetBotPrecheckoutResultsRequest(
                query_id=event.query_id,
                success=True,
                error=None
            ))
        except Exception as e:
            print(f"Pre-checkout Error: {e}")

@client.on(events.Raw)
async def raw_payment_handler(event):
    """
    Catches the low-level 'UpdateNewMessage' to ensure we never miss a payment.
    """
    if isinstance(event, types.UpdateNewMessage):
        message = event.message
        
        if isinstance(message, types.MessageService):
            
            if isinstance(message.action, types.MessageActionPaymentSentMe):
                payment = message.action
                
                print(f"Payment Event Detected! Payload: {payment.payload}")
                
                try:
                    payload = payment.payload.decode('utf-8')
                    
                    charge_id = None
                    if hasattr(payment, 'charge') and payment.charge:
                        charge_id = payment.charge.id

                    if payload.startswith('premium_sub_'):
                        user_id = int(payload.split('_')[-1])
                        user = await User.get(id=user_id)
                        
                        user.is_premium = True
                        user.premium_expiry_date = date.today() + timedelta(days=365)
                        await user.save()
                        
                        await client.send_message(
                            user_id,
                            "🎉 **Payment Received!**\n\n"
                            "You are now a Premium user for 1 Year.\n"
                            "Thank you for your support!"
                        )
                        print(f"Premium activated for user {user_id}")

                except Exception as e:
                    print(f"CRITICAL ERROR in Payment Handler: {e}")

async def main():
    print("Initializing Database...")
    
    print("Starting Bot...")
    await client.start(bot_token=BOT_TOKEN)
    

    client.loop.create_task(check_crypto_payments())

    print("Bot is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())