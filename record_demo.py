import asyncio
import os
import subprocess
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/config/.gemini/antigravity/brain/b1f9db86-49b2-428f-bc80-0732cb47fd48"
APP_URL = "https://itvara-frontend-30471912245.us-east1.run.app"

async def main():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    temp_video_dir = "/tmp/demo_videos"
    os.makedirs(temp_video_dir, exist_ok=True)

    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=temp_video_dir,
            record_video_size={"width": 1280, "height": 800}
        )

        page = await context.new_page()
        print(f"Navigating to {APP_URL}...")
        await page.goto(APP_URL, wait_until="networkidle")
        await asyncio.sleep(2)

        # 1. Greet / Prompt 1 (What the app does best: Solo travel welcome & quick prompt)
        print("Clicking example prompt 'Nepal Trekking'...")
        prompt_pills = await page.query_selector_all(".prompt-pill")
        if prompt_pills:
            await prompt_pills[0].click()
            await asyncio.sleep(8)
        else:
            input_box = await page.query_selector("#user-input")
            if input_box:
                await input_box.fill("Hi! I am planning a solo trekking trip to Nepal on a budget.")
                await page.keyboard.press("Enter")
                await asyncio.sleep(8)

        # 2. Prompt 2 (Richer prompt: tool calls, weather lookup, and image generation)
        print("Sending rich prompt with live weather and image generation...")
        input_box = await page.query_selector("#user-input")
        if input_box:
            await input_box.fill("Check live weather for Pokhara and generate a destination image for the Annapurna Circuit trek.")
            send_btn = await page.query_selector("#send-btn")
            if send_btn:
                await send_btn.click()
            else:
                await page.keyboard.press("Enter")
            
            # Wait for tools, weather fetch, and image generation
            print("Waiting for response and image generation...")
            await asyncio.sleep(15)

        print("Closing context to finalize video recording...")
        await context.close()
        await browser.close()

        # Locate recorded video file
        videos = [os.path.join(temp_video_dir, f) for f in os.listdir(temp_video_dir) if f.endswith(".webm")]
        if not videos:
            print("Error: No video file found!")
            return

        raw_video = videos[0]
        output_mp4 = os.path.join(ARTIFACT_DIR, "itvara_demo.mp4")
        output_webm = os.path.join(ARTIFACT_DIR, "itvara_demo.webm")

        # Copy/convert using Playwright's installed ffmpeg
        ffmpeg_bin = "/config/.cache/ms-playwright/ffmpeg-1011/ffmpeg-linux"
        if os.path.exists(ffmpeg_bin):
            print(f"Converting video to MP4 using ffmpeg: {output_mp4}")
            subprocess.run([
                ffmpeg_bin, "-y", "-i", raw_video,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", output_mp4
            ], check=True)
            print("MP4 conversion successful!")
        else:
            # Fallback copy to webm
            import shutil
            shutil.copyfile(raw_video, output_webm)
            print(f"Saved demo video to: {output_webm}")

if __name__ == "__main__":
    asyncio.run(main())
