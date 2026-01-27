from datetime import date
import os
import random
import asyncio
from telethon import TelegramClient, events, functions, types, utils, Button
import subprocess
from tortoise import Tortoise, fields, run_async
from tortoise.models import Model
from dotenv import load_dotenv
from db.database import User

load_dotenv()

# ================= CONFIGURATION =================
API_ID = int(os.getenv('API_ID'))       
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_URL = os.getenv('DB_URL')
# Add your admin username here or in .env (without @)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin') 

if not API_ID or not BOT_TOKEN:
    raise ValueError("CRITICAL ERROR: .env file is missing or empty!")

client = TelegramClient('bot_session_db', API_ID, API_HASH)

# ================= DATABASE HELPERS =================
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

# ================= MENU HANDLERS =================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await register_user(event)
    
    text = (
        f"✨ **Hello, {user.first_name}!**\n\n"
        "I create round video notes for you.\n"
        "Send me a video to get started!\n\n"
        "👇 **Choose an option below:**"
    )
    
    # Main Menu Buttons
    buttons = [
        [Button.inline("💎 Premium Features", data=b"menu_premium")],
        [Button.inline("🆘 Help / Support", data=b"menu_help")]
    ]
    
    await event.respond(text, buttons=buttons)

@client.on(events.CallbackQuery)
async def menu_handler(event):
    """Handles all button clicks."""
    data = event.data.decode('utf-8')
    user = await register_user(event) # Ensure user is in DB
    sender_id = event.sender_id

    # --- MAIN MENU ---
    if data == "menu_main":
        text = (
            f"✨ **Hello, {user.first_name}!**\n\n"
            "I create round video notes for you.\n"
            "Send me a video to get started!\n\n"
            "👇 **Choose an option below:**"
        )
        buttons = [
            [Button.inline("💎 Premium Features", data=b"menu_premium")],
            [Button.inline("🆘 Help / Support", data=b"menu_help")]
        ]
        await event.edit(text, buttons=buttons)

    # --- HELP MENU ---
    elif data == "menu_help":
        text = (
            "🆘 **Support**\n\n"
            "If you are having trouble, please contact the admin directly.\n\n"
            f"👤 Admin: @{ADMIN_USERNAME}"
        )
        buttons = [[Button.inline("🔙 Back", data=b"menu_main")]]
        await event.edit(text, buttons=buttons)

    # --- PREMIUM MENU ---
    elif data == "menu_premium":
        text = (
            "💎 **Premium Subscription**\n\n"
            "✅ Unlimited daily video conversions\n"
            "✅ Priority processing\n"
            "✅ No ads/watermarks\n\n"
            "**Price:** 99 RUB / 99 Stars (1 Year)\n"
            "Select a payment method:"
        )
        buttons = [
            [Button.inline("🤖 Pay via Crypto Bot (99 RUB)", data=b"buy_crypto")],
            [Button.inline("⭐️ Pay via Telegram Stars (99 ⭐️)", data=b"buy_stars")],
            [Button.inline("🔙 Back", data=b"menu_main")]
        ]
        await event.edit(text, buttons=buttons)

    # --- ACTION: BUY STARS ---
    elif data == "buy_stars":
        await event.answer("Creating Invoice...", alert=False)
        # Note: You must enable payments in BotFather for this to work.
        # Use currency 'XTR' for Telegram Stars.
        try:
            await client(functions.messages.SendInvoiceRequest(
                peer=event.chat_id,
                title="Premium Subscription (1 Year)",
                description="Unlimited Round Video Notes",
                payload=f"premium_sub_{sender_id}".encode('utf-8'), # Payload to identify after payment
                provider_token="", # Empty for Stars (if using internal stars system) or your provider token
                currency="XTR",    # Currency code for Telegram Stars
                prices=[types.LabeledPrice(label="1 Year", amount=99)], # Amount: 1 Star = 1 Amount unit? Verify specific Stars logic
                start_param="premium_sub",
                photo=None
            ))
        except Exception as e:
            await event.respond(f"Error creating invoice: {e}")

    # --- ACTION: BUY CRYPTO ---
    elif data == "buy_crypto":
        # Placeholder: Integrating Crypto Bot usually requires an API call to create an invoice link.
        # Since we don't have the API key here, we send a message instructions or a static link.
        await event.answer("Redirecting...", alert=False)
        await event.respond(
            "💳 **Pay with Crypto Bot**\n\n"
            "Please send 99 RUB equivalent to the address below or click the link:\n"
            "*(You need to implement the Crypto Pay API integration here to generate a real link)*",
            buttons=[Button.url("Open Crypto Bot", "https://t.me/CryptoBot")]
        )

# ================= VIDEO PROCESSING (FFMPEG) =================
def process_video_v2(input_path, output_path):
    """
    Uses direct FFmpeg for high-performance cropping and resizing.
    """
    command = [
        'ffmpeg',
        '-y',
        '-i', input_path,
        '-vf', "crop='min(iw,ih):min(iw,ih)',scale=400:400",
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '20',
        '-c:a', 'aac',
        '-b:a', '64k',
        '-movflags', '+faststart',
        output_path
    ]

    try:
        subprocess.run(
            command, 
            check=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Error: {e}")
        return False
    except Exception as e:
        print(f"General Error: {e}")
        return False

# ================= VIDEO HANDLER =================
@client.on(events.NewMessage)
async def video_handler(event):
    # 1. Validation
    if event.text and event.text.startswith('/') or not event.video or not event.is_private:
        return

    # 2. User & Limit Checks
    user = await register_user(event)
    today = date.today()

    if user.last_use_date != today:
        user.done_today = 0
        user.last_use_date = today
        await user.save()

    if not user.is_premium and user.done_today >= 3:
        # Send a button to upgrade if limit reached
        await event.respond(
            "🚫 **Daily Limit Reached!**\n\nYou have used your 3 free videos for today.",
            buttons=[Button.inline("💎 Upgrade to Premium", data=b"menu_premium")]
        )
        return

    # 3. Duration Check
    duration = 0
    if hasattr(event.video, 'attributes'):
        for attr in event.video.attributes:
            if isinstance(attr, types.DocumentAttributeVideo):
                duration = attr.duration
                break
    
    if duration > 60:
        return await event.respond("❌ **Video is too long!** Maximum length for round notes is 60 seconds.")

    # 4. Processing
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

        # Only send the warning to non-premium users
        if not user.is_premium:
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

# ================= MAIN LOOP =================
async def main():
    print("Initializing Database...")
    # NOTE: Database init is handled by main.py in your structure, 
    # but if running standalone, ensure init_db() is called.
    
    print("Starting Bot...")
    await client.start(bot_token=BOT_TOKEN)
    
    print("Bot is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())