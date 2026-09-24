import asyncio
import os
import subprocess
import imageio_ffmpeg
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/config/.gemini/antigravity/brain/b1f9db86-49b2-428f-bc80-0732cb47fd48"
APP_URL = "https://itvara-frontend-30471912245.us-east1.run.app"
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

async def main():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    temp_video_dir = "/tmp/demo_videos"
    if os.path.exists(temp_video_dir):
        for f in os.listdir(temp_video_dir):
            try:
                os.remove(os.path.join(temp_video_dir, f))
            except Exception:
                pass
    os.makedirs(temp_video_dir, exist_ok=True)

    # Record browser interaction
    async with async_playwright() as p:
        print("Launching Playwright Chromium...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=temp_video_dir,
            record_video_size={"width": 1280, "height": 800}
        )

        page = await context.new_page()
        print(f"Navigating to {APP_URL}...")
        await page.goto(APP_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        # Step 1: Send setup greeting ("Hi")
        print("Step 1: Typing 'Hi' to trigger welcome greeting & setup questions...")
        await page.fill("#input", "Hi")
        await page.keyboard.press("Enter")
        print("Waiting for welcome response with setup options...")
        await asyncio.sleep(7)

        # Step 2: Answer setup question ("1. Trekking & Hiking in Nepal")
        print("Step 2: Responding to setup question: '1. Trekking & Hiking in Nepal under $50 per day'...")
        await page.fill("#input", "1. Trekking & Hiking in Nepal under $50 per day")
        await page.keyboard.press("Enter")
        print("Waiting for database search & recommendations...")
        await asyncio.sleep(8)

        # Step 3: Richer prompt (Weather lookup + Image generation)
        print("Step 3: Sending rich prompt for weather lookup & destination image generation...")
        await page.fill("#input", "Check live weather for Pokhara and generate a destination image for the Annapurna Circuit trek.")
        await page.keyboard.press("Enter")
        print("Waiting for live weather tool and image generation model...")
        await asyncio.sleep(16)

        await asyncio.sleep(3)
        print("Closing browser context...")
        await context.close()
        await browser.close()

    # Find recorded raw video
    videos = [os.path.join(temp_video_dir, f) for f in os.listdir(temp_video_dir) if f.endswith(".webm")]
    if not videos:
        print("Error: No recorded video file found!")
        return

    raw_video = sorted(videos, key=os.path.getmtime)[-1]
    output_mp4 = os.path.join(ARTIFACT_DIR, "itvara_demo.mp4")
    output_webm = os.path.join(ARTIFACT_DIR, "itvara_demo.webm")

    print(f"Exporting silent demo video (no audio stream) using FFmpeg ({FFMPEG_BIN})...")
    
    # Generate silent MP4 version (-an removes audio completely)
    subprocess.run([
        FFMPEG_BIN, "-y",
        "-i", raw_video,
        "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        output_mp4
    ], check=True)

    # Generate silent WebM version (-an removes audio completely)
    subprocess.run([
        FFMPEG_BIN, "-y",
        "-i", raw_video,
        "-an",
        "-c:v", "libvpx-vp9",
        output_webm
    ], check=True)

    print(f"Silent demo video (no audio) successfully created:\n- MP4: {output_mp4}\n- WebM: {output_webm}")

if __name__ == "__main__":
    asyncio.run(main())
