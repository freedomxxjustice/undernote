import os
import random
import asyncio
import time
import subprocess
from datetime import date
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from dotenv import load_dotenv

# IMPORTS FROM DB (Fixing the error)
from db.database import User

# Load environment variables
load_dotenv()

# ================= CONFIGURATION =================
API_ID = int(os.getenv('API_ID', 0))       
API_HASH = os.getenv('API_HASH')
DB_URL = os.getenv('DB_URL')
STRING_SESSION = os.getenv('STRING_SESSION')

if not API_ID or not API_HASH:
    raise ValueError("CRITICAL ERROR: API_ID or API_HASH missing in .env!")

if not STRING_SESSION:
    raise ValueError("STRING_SESSION env variable is missing! Run generate_session.py first.")

# Initialize Client
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# Anti-Spam Cache
non_premium_cooldowns = {}
COOLDOWN_SECONDS = 300  # 5 Minutes

# ================= DATABASE HELPERS =================
async def register_user(event):
    """Ensures user exists in DB on every interaction."""
    sender = await event.get_sender()
    uid = sender.id if sender else event.sender_id
    
    # Using the imported User model from db.database
    user, _ = await User.get_or_create(
        id=uid,
        defaults={
            'username': getattr(sender, 'username', None), 
            'first_name': getattr(sender, 'first_name', 'User')
        }
    )
    return user

# ================= VIDEO PROCESSING (FFMPEG) =================
def process_video_v2(input_path, output_path):
    """
    High-performance cropping and resizing using FFmpeg.
    """
    command = [
        'ffmpeg',
        '-y',
        '-i', input_path,
        '-vf', "crop='min(iw,ih):min(iw,ih)',scale=400:400",
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '26',
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
    except Exception as e:
        print(f"FFmpeg Error: {e}")
        return False

# ================= HANDLERS =================

@client.on(events.NewMessage)
async def main_handler(event):
    if not event.is_private or event.out:
        return

    user = await register_user(event)

    # PREMIUM CHECK
    if not user.is_premium:
        now = time.time()
        last_warning = non_premium_cooldowns.get(user.id, 0)
        
        if now - last_warning < COOLDOWN_SECONDS:
            return 
        
        non_premium_cooldowns[user.id] = now
        await event.respond("🔒 **This bot is for Premium users only.**\n\nPlease use the free version or upgrade to continue.")
        return

    # Handle Commands
    if event.text and event.text.startswith('/'):
        if event.text.startswith('/start'):
            welcome_text = (
                f"✨ **Hello, {user.first_name}!**\n\n"
                "I am ready to create Premium Video Notes.\n"
                "Just send me a video!"
            )
            await event.respond(welcome_text)
        return

    if not event.video:
        return

    # Processing Logic
    duration = 0
    if hasattr(event.video, 'attributes'):
        for attr in event.video.attributes:
            if isinstance(attr, types.DocumentAttributeVideo):
                duration = attr.duration
                break
    
    if duration > 60:
        return await event.respond("❌ **Video too long!** Max 60 seconds.")

    status_msg = await event.respond("⏳ **Processing Premium Note...**")
    
    path_in = f"in_{user.id}_{random.randint(1000,9999)}.mp4"
    path_out = f"out_{user.id}_{random.randint(1000,9999)}.mp4"

    try:
        await event.download_media(file=path_in)
        await status_msg.edit("⚙️ **Cropping...**")
        
        success = await asyncio.to_thread(process_video_v2, path_in, path_out)
        
        if not success or not os.path.exists(path_out):
            raise Exception("Processing failed")

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
                file=uploaded_file, 
                mime_type='video/mp4', 
                attributes=[video_attribute]
            ),
            message=event.message.message or "",
            entities=event.message.entities,
            random_id=random.randint(0, 2**63 - 1)
        ))

        user.done_today += 1
        user.last_use_date = date.today()
        await user.save()
        
        await status_msg.delete()

    except Exception as e:
        print(f"Error processing for {user.id}: {e}")
        await status_msg.edit("❌ **Error processing video.**")
    finally:
        for p in [path_in, path_out]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

# ================= STARTUP =================
async def main():
    # Database is already initialized by main.py, so we skip init_db() here
    
    print("Connecting Userbot to Telegram...")
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Userbot Session Invalid! Run generate_session.py locally first.")
        return

    me = await client.get_me()
    print(f"✅ Userbot Started as: {me.first_name} (@{me.username})")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())