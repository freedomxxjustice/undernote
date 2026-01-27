from datetime import date
import os
import random
import asyncio
from telethon import TelegramClient, events, functions, types, utils
import subprocess
from tortoise import Tortoise, fields, run_async
from tortoise.models import Model
from dotenv import load_dotenv
from db.database import User

load_dotenv()

# ================= CONFIGURATION =================
API_ID = int(os.getenv('API_ID'))       # Converted to int
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_URL = os.getenv('DB_URL')

# Check if keys are loaded (Optional but recommended)
if not API_ID or not BOT_TOKEN:
    raise ValueError("CRITICAL ERROR: .env file is missing or empty!")

client = TelegramClient('bot_session_db', API_ID, API_HASH)


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


@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await register_user(event)
    welcome_text = (
        f"✨ **Hello, {user.first_name}!**\n\n"
        "I'm ready to convert your videos into round notes.\n"
        "Just send me a video file and I'll do the rest!\n"
        "The result is only visible on mobile version of Telegram.\n"
        "To extend daily 3 videos limit, consider buying 99RUB/year premium."
    )
    await event.respond(welcome_text)

def process_video_v2(input_path, output_path):
    """
    Uses direct FFmpeg for high-performance cropping and resizing.
    1. crop='min(iw,ih):min(iw,ih)': Cuts a perfect square from the center.
    2. scale=400:400: Resizes the square to 400x400 for Telegram Video Notes.
    """
    command = [
        'ffmpeg',
        '-y',                      # Overwrite output file if exists
        '-i', input_path,          # Input file
        '-vf', "crop='min(iw,ih):min(iw,ih)',scale=400:400", # Filter: Center Crop -> Resize
        '-c:v', 'libx264',         # Video Codec
        '-preset', 'fast',         # Encoding speed (fast is a good balance)
        '-crf', '26',              # Quality (lower is better, 23-28 is standard)
        '-c:a', 'aac',             # Audio Codec
        '-b:a', '64k',             # Audio Bitrate (Video notes don't need HQ audio)
        '-movflags', '+faststart', # Optimize for web streaming
        output_path
    ]

    try:
        # Run FFmpeg silently (stdout/stderr to DEVNULL)
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

@client.on(events.NewMessage)
async def video_handler(event):
    # 1. Validation: Must be private, contain video, and not be a command
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
        return await event.respond("🚫 **Limit reached!** Get `/premium` for more.")

    # 3. Duration Check
    duration = 0
    # Safely get duration
    if hasattr(event.video, 'attributes'):
        for attr in event.video.attributes:
            if isinstance(attr, types.DocumentAttributeVideo):
                duration = attr.duration
                break
    
    if duration > 60:
        return await event.respond("❌ **Video is too long!** Maximum length for round notes is 60 seconds.")

    # 4. Processing
    status_msg = await event.respond("⏳ **Processing...**")
    
    # Use random filenames to prevent collision errors
    path_in = f"in_{event.id}_{random.randint(100,999)}.mp4"
    path_out = f"out_{event.id}_{random.randint(100,999)}.mp4"

    try:
        await event.download_media(file=path_in)
        await status_msg.edit("⚙️ **Cropping...**")
        
        # Run FFmpeg in a separate thread to keep bot responsive
        success = await asyncio.to_thread(process_video_v2, path_in, path_out)
        
        if not success or not os.path.exists(path_out):
            raise Exception("FFmpeg processing failed.")
        
        await status_msg.edit("⬆️ **Uploading...**")
        uploaded_file = await client.upload_file(path_out)

        # 5. Sending the Round Note
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

        # Only send the warning to non-premium users (optional tweak)
        if not user.is_premium:
            await client(functions.messages.SendMessageRequest(
                peer=await event.get_input_chat(),
                message="Do not forget, that the result is only visible on mobile version of Telegram!",
                random_id=random.randint(0, 2**63 - 1)
            ))

        user.done_today += 1
        await user.save()
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit(f"❌ **Error:** {str(e)}")
    finally:
        # Cleanup Files
        for p in [path_in, path_out]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

# ================= MAIN LOOP =================
async def main():
    print("Initializing Database...")
    
    print("Starting Bot...")
    await client.start(bot_token=BOT_TOKEN)
    
    print("Bot is running. Press Ctrl+C to stop.")
    await client.run_until_disconnected()

    # Close DB connections on shutdown
    await Tortoise.close_connections()

if __name__ == '__main__':
    asyncio.run(main())