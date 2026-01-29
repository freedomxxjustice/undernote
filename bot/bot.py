from datetime import date, timedelta
import os
import random
import asyncio
import aiohttp
from telethon import TelegramClient, events, functions, types, Button
from telethon.errors import UserIsBlockedError, FloodWaitError
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
ADMIN_ID = os.getenv('ADMIN_ID', '012345678') 

if not API_ID or not BOT_TOKEN:
    raise ValueError("CRITICAL ERROR: .env file is missing or empty!")

client = TelegramClient('bot_session_db', API_ID, API_HASH)
ad_states = {}
INVOICE_FILE = "processed_invoices.txt"

def load_processed_invoices():
    """Loads invoice IDs from a file on startup."""
    if not os.path.exists(INVOICE_FILE):
        return set()
    with open(INVOICE_FILE, "r") as f:
        # Read lines, strip whitespace, and return as a set
        return set(line.strip() for line in f if line.strip())

def save_invoice_id(invoice_id):
    """Appends a new invoice ID to the file."""
    try:
        with open(INVOICE_FILE, "a") as f:
            f.write(f"{invoice_id}\n")
    except Exception as e:
        print(f"Error saving invoice ID: {e}")

# Initialize the set from the file instead of creating an empty one
processed_invoices = load_processed_invoices()
print(f"📂 Loaded {len(processed_invoices)} processed invoices from file.")

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
                # We fetch the last 20 paid invoices
                params = {'status': 'paid', 'count': 20}
                async with session.get(url, headers=headers, params=params) as response:
                    data = await response.json()
                    
                    if data.get('ok'):
                        invoices = data['result']['items']
                        
                        for inv in invoices:
                            invoice_id = str(inv['invoice_id']) # Ensure it's a string
                            payload = inv.get('payload', '')

                            # 1. Check if we already processed this ID
                            if invoice_id in processed_invoices:
                                continue
                            
                            # 2. Add to memory AND save to file immediately
                            processed_invoices.add(invoice_id)
                            save_invoice_id(invoice_id)
                            
                            # 3. Process the premium activation
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
        "*this bot doesn't support premium emojis, instead consider buying premium subscription (covering premium account expenses) and use @undernote!*\n\n"
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
            "*this bot doesn't support premium emojis, instead consider buying premium subscription (covering premium account expenses) and use @undernote!*\n\n"
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
                "Enjoy unlimited video conversions, priority processing and access to @undernote."
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

    if event.sender_id in ad_states:
        return

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


@client.on(events.NewMessage(pattern='/broadcast'))
async def start_broadcast_handler(event):
    """Step 1: Admin starts the broadcast sequence."""
    user = await register_user(event)
    
    # Security: Check if sender is ADMIN
    if str(user.id) != str(ADMIN_ID):
        return # Ignore non-admins
    sender_id = event.sender_id
    
    # Initialize state
    ad_states[sender_id] = {
        'state': 'waiting_content',
        'content': [], # Stores message objects
        'grouped_id': None # To track albums
    }
    
    await event.respond(
        "📢 **Broadcast Setup**\n\n"
        "Please send the **Post Content** now.\n"
        "You can send:\n"
        "• Text\n"
        "• Photo/Video (with caption)\n"
        "• Album (up to 9 media items)\n\n"
        "👉 **If sending an Album (Multiple Photos):**\n"
        "Send them now, wait for them to upload, then send **/next** to finish.\n\n"
        "Send /cancel to stop."
    )

@client.on(events.NewMessage(pattern='/cancel'))
async def cancel_broadcast(event):
    sender_id = event.sender_id
    if sender_id in ad_states:
        del ad_states[sender_id]
        await event.respond("❌ Broadcast cancelled.")
@client.on(events.NewMessage())
async def ad_builder_handler(event):
    """Handles the steps of building the ad (Content -> Button -> Confirm)."""
    
    # 1. Basic checks
    # Allow '/next' to pass through, block other commands
    if event.text and event.text.startswith('/') and event.text != '/next': 
        return 
        
    sender_id = event.sender_id
    if sender_id not in ad_states: return

    state_data = ad_states[sender_id]
    current_state = state_data['state']

    # ==========================
    # STEP 2: RECEIVE CONTENT
    # ==========================
    if current_state == 'waiting_content':
        
        # A) User types "/next" to finish sending an Album
        if event.text == '/next':
            if not state_data['content']:
                await event.respond("⚠️ You haven't sent any content yet!")
                return
            
            # Move to next step
            state_data['state'] = 'waiting_button'
            await event.respond(
                "✅ **Album Received.**\n\n"
                "Now, do you want to add a **URL Button**?\n"
                "Send format: `Button Text - https://link.com`\n\n"
                "Or send **'skip'** to proceed without a button."
            )
            return

        # B) Handle Albums (Multiple media with same grouped_id)
        if event.grouped_id:
            if state_data['grouped_id'] != event.grouped_id:
                state_data['grouped_id'] = event.grouped_id
                state_data['content'] = [] # Reset if new group
            
            state_data['content'].append(event.message)
            # We return here to wait for the next photo in the album.
            # You MUST send /next when done uploading.
            return 
        
        # C) Single message (Text or Single Media)
        else:
            state_data['content'] = [event.message]
            # For single messages, we can auto-advance
            state_data['state'] = 'waiting_button'
            await event.respond(
                "✅ **Content Received.**\n\n"
                "Now, do you want to add a **URL Button**?\n"
                "Send format: `Button Text - https://link.com`\n\n"
                "Or send **'skip'** to proceed without a button."
            )

    # ==========================
    # STEP 3: RECEIVE BUTTON
    # ==========================
    elif current_state == 'waiting_button':
        text = event.text.strip()
        
        button = None
        if text.lower() != 'skip':
            if '-' in text:
                btn_text, btn_url = text.split('-', 1)
                button = [Button.url(btn_text.strip(), btn_url.strip())]
            else:
                await event.respond("⚠️ Format invalid. Use: `Text - URL` or send `skip`.")
                return

        state_data['button'] = button
        state_data['state'] = 'waiting_confirm'
        
        # Generate Preview
        preview_text = "👀 **Preview of your Ad:**\n\n"
        await event.respond(preview_text)

        msgs = state_data['content']
        
        try:
            if len(msgs) > 1: # Album
                # Send the album (text is usually in the first message's caption)
                await client.send_message(event.chat_id, file=[m.media for m in msgs], message=msgs[0].text)
                if button:
                    await event.respond("👇 **Link:**", buttons=button)
            else: # Single Msg
                msg = msgs[0]
                await client.send_message(
                    event.chat_id,
                    message=msg.text,
                    file=msg.media,
                    buttons=button
                )
        except Exception as e:
            await event.respond(f"Error generating preview: {e}")
            return

        await event.respond(
            "➖➖➖➖➖➖➖➖\n"
            "📢 **Ready to Broadcast?**\n"
            "This will send to all **Non-Premium** users.\n\n"
            "Send **/confirm_broadcast** to start.\n"
            "Send **/cancel** to stop."
        )

@client.on(events.NewMessage(pattern='/confirm_broadcast'))
async def execute_broadcast(event):
    """Step 4: Execute the sending loop."""
    sender_id = event.sender_id
    if sender_id not in ad_states or ad_states[sender_id]['state'] != 'waiting_confirm':
        return await event.respond("⚠️ No broadcast pending. Start with /broadcast.")

    data = ad_states[sender_id]
    del ad_states[sender_id] # Clear state
    
    status_msg = await event.respond("🚀 **Starting Broadcast...**\nFetching users...")

    # Fetch Non-Premium Users
    # Note: Tortoise ORM 'filter' returns a QuerySet
    users = await User.filter(is_premium=False).all()
    
    total = len(users)
    sent = 0
    blocked = 0
    errors = 0
    
    await status_msg.edit(f"🚀 **Target:** {total} users.\nSending in background...")

    # Helper to send (Handles Album vs Single logic)
    async def send_ad(target_id):
        msgs = data['content']
        btn = data['button']
        
        if len(msgs) > 1: # Album
            await client.send_message(target_id, file=[m.media for m in msgs], message=msgs[0].text)
            if btn:
                await client.send_message(target_id, "👇", buttons=btn)
        else: # Single
            msg = msgs[0]
            await client.send_message(target_id, message=msg.text, file=msg.media, buttons=btn)

    # Batch Processing
    for i, user in enumerate(users):
        try:
            await send_ad(user.id)
            sent += 1
        except UserIsBlockedError:
            blocked += 1
            # Optional: Delete blocked user from DB to keep it clean
            # await user.delete() 
        except FloodWaitError as e:
            print(f"FloodWait: Sleeping {e.seconds}s")
            await asyncio.sleep(e.seconds)
            try:
                await send_ad(user.id) # Retry once
                sent += 1
            except:
                errors += 1
        except Exception as e:
            print(f"Failed to send to {user.id}: {e}")
            errors += 1
        
        # Anti-Flood Delay: Sleep 1s every 20 messages
        if i % 20 == 0 and i > 0:
            await asyncio.sleep(1.5) 
            # Update admin every 100 users
            if i % 100 == 0:
                await status_msg.edit(f"📊 Progress: {i}/{total}\n✅ Sent: {sent}\n🚫 Blocked: {blocked}")

    await client.send_message(
        sender_id,
        f"✅ **Broadcast Complete!**\n\n"
        f"👥 Total Target: {total}\n"
        f"✅ Successfully Sent: {sent}\n"
        f"🚫 Blocked/Deleted: {blocked}\n"
        f"⚠️ Errors: {errors}"
    )

async def main():
    print("Initializing Database...")
    
    print("Starting Bot...")
    await client.start(bot_token=BOT_TOKEN)
    

    client.loop.create_task(check_crypto_payments())

    print("Bot is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())