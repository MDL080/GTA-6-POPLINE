#!/usr/bin/env python3
"""
auto_pipeline.py - Autonomous GTA 6 Stream Clipper & YouTube Publisher
======================================================================
Monitors: xQc, Adin Ross, Kai Cenat, IShowSpeed.
Filter:   ONLY clips when playing GTA 6 / Grand Theft Auto VI.
Framing:  Gameplay-Only (no facecam, 9:16 phone-format crop).
Features: Detects glitches/bugs/viral moments, generates Vice City themed subtitles,
          and automatically uploads directly to YouTube Shorts.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE_DIR = Path(__file__).resolve().parent
SCRATCH_DIR = BASE_DIR.parent
BRANDING_DIR = SCRATCH_DIR / "gta6_channel_branding"
OUTPUT_DIR = BASE_DIR / "automated_clips"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

YTDLP = shutil.which("yt-dlp") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python312/Scripts/yt-dlp.exe")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

TARGET_STREAMERS = {
    "xqc": {
        "name": "xQc",
        "url": "https://kick.com/xqc",
        "vods_url": "https://kick.com/xqc/videos",
        "platform": "Kick"
    },
    "adinross": {
        "name": "Adin Ross",
        "url": "https://kick.com/adinross",
        "vods_url": "https://kick.com/adinross/videos",
        "platform": "Kick"
    },
    "kaicenat": {
        "name": "Kai Cenat",
        "url": "https://twitch.tv/kaicenat",
        "vods_url": "https://twitch.tv/kaicenat/videos",
        "platform": "Twitch"
    },
    "ishowspeed": {
        "name": "IShowSpeed",
        "url": "https://www.youtube.com/@IShowSpeed/live",
        "vods_url": "https://www.youtube.com/@IShowSpeed/streams",
        "platform": "YouTube"
    }
}

GTA6_KEYWORDS = ["gta 6", "gta vi", "gta6", "grand theft auto vi", "grand theft auto 6", "vice city"]
GLITCH_KEYWORDS = ["glitch", "bug", "secret", "broke", "fail", "stunt", "busted", "easter egg", "insane", "crazy", "unreal", "physics"]


def is_gta6_content(title: str, categories: list = None) -> bool:
    """Verifies that the streamer is currently playing GTA 6 and nothing else."""
    text_to_check = title.lower()
    if categories:
        text_to_check += " " + " ".join(str(c).lower() for c in categories)
    return any(k in text_to_check for k in GTA6_KEYWORDS)


def is_glitch_moment(title: str) -> bool:
    """Detects if stream title points to a glitch, secret, or viral moment."""
    t_lower = title.lower()
    return any(k in t_lower for k in GLITCH_KEYWORDS)


def check_streamer(streamer_id: str) -> dict:
    """Inspects a streamer's live status, current game, and stream title, including ongoing and recent broadcasts."""
    cfg = TARGET_STREAMERS.get(streamer_id)
    if not cfg:
        return {"live": False}

    url = cfg["url"]
    cmd = [YTDLP, "--impersonate", "chrome", "--dump-json", url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip().splitlines()[-1])
            # 1. Ongoing Live Broadcast (captures even if started hours ago)
            if data.get("is_live"):
                title = data.get("fulltitle") or data.get("title") or ""
                categories = data.get("categories") or []
                
                # Filter strictly for GTA 6
                if not is_gta6_content(title, categories):
                    print(f"[-] {cfg['name']} is live but NOT playing GTA 6 (Playing: {title[:40]}). Skipping.")
                    return {"live": False}

                return {
                    "live": True,
                    "id": streamer_id,
                    "name": cfg["name"],
                    "title": title,
                    "is_glitch": is_glitch_moment(title),
                    "viewers": data.get("concurrent_view_count", 0),
                    "url": url,
                    "platform": cfg["platform"]
                }
    except Exception as e:
        print(f"[!] Error checking live for {cfg['name']}: {e}")

    # 2. Recent Past Broadcast / VOD Fallback (if stream already concluded)
    vod_url = cfg.get("vods_url")
    if vod_url:
        try:
            vod_cmd = [YTDLP, "--impersonate", "chrome", "--playlist-items", "1", "--dump-json", vod_url]
            vres = subprocess.run(vod_cmd, capture_output=True, text=True, timeout=30)
            if vres.returncode == 0 and vres.stdout.strip():
                vdata = json.loads(vres.stdout.strip().splitlines()[-1])
                vtitle = vdata.get("fulltitle") or vdata.get("title") or ""
                vcats = vdata.get("categories") or []
                v_web_url = vdata.get("webpage_url") or vod_url
                if is_gta6_content(vtitle, vcats):
                    history_file = OUTPUT_DIR / "processed_vods.json"
                    processed = []
                    if history_file.exists():
                        try:
                            processed = json.loads(history_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    vid_id = str(vdata.get("id") or vtitle)
                    if vid_id not in processed:
                        return {
                            "live": True,
                            "id": streamer_id,
                            "name": cfg["name"],
                            "title": vtitle,
                            "is_glitch": is_glitch_moment(vtitle),
                            "viewers": 0,
                            "url": v_web_url,
                            "platform": cfg["platform"],
                            "is_vod": True,
                            "vod_id": vid_id
                        }
        except Exception as e:
            print(f"[!] Error checking past broadcasts for {cfg['name']}: {e}")

    return {"live": False}


def capture_stream(url: str, duration: int, out_video: Path) -> bool:
    """Losslessly records live stream segment using yt-dlp and FFmpeg."""
    print(f"[*] Resolving live stream: {url}...")
    
    # For Kick / Twitch direct HLS resolution:
    if "youtube.com" not in url:
        resolve_cmd = [YTDLP, "--impersonate", "chrome", "-g", url]
        res = subprocess.run(resolve_cmd, capture_output=True, text=True, timeout=25)
        if res.returncode == 0 and res.stdout.strip():
            stream_url = res.stdout.strip().splitlines()[0]
            print(f"[*] Capturing {duration}s live stream via FFmpeg...")
            cmd = [
                FFMPEG, "-y",
                "-reconnect", "1", "-reconnect_at_eof", "1", "-reconnect_streamed", "1",
                "-i", stream_url,
                "-t", str(duration),
                "-c", "copy",
                str(out_video)
            ]
            rec_res = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 60)
            if rec_res.returncode == 0 and out_video.exists():
                return True

    # Fallback / YouTube live streams:
    print(f"[*] Capturing {duration}s live stream via yt-dlp...")
    dl_cmd = [
        YTDLP,
        url,
        "--downloader", "ffmpeg",
        "--downloader-args", f"ffmpeg_i:-t {duration}",
        "-o", str(out_video)
    ]
    rec_res = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=duration + 60)
    return rec_res.returncode == 0 and out_video.exists()


def get_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\arialbd.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return ImageFont.load_default()


def create_dynamic_overlay(streamer_name: str, stream_title: str, is_glitch: bool, out_overlay: Path):
    """Generates a custom branded 1080x1920 overlay reflecting the real gameplay moment."""
    base_png = BRANDING_DIR / "gta6_shorts_overlay.png"
    img = Image.open(base_png).convert("RGBA") if base_png.exists() else Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Top Banner
    draw.rounded_rectangle([100, 245, 980, 340], radius=16, fill=(14, 0, 26, 245))
    f_top = get_font(42)
    top_header = f"GTA 6 GLITCH FOUND?! 😱" if is_glitch else f"{streamer_name.upper()} PLAYS GTA 6! 🔥"
    draw.text((540, 280), top_header, font=f_top, fill=(255, 229, 0), anchor="mm")
    
    f_sub = get_font(22)
    top_sub = "UNREAL GLITCH & SECRET" if is_glitch else "VICE CITY OFFICIAL GAMEPLAY"
    draw.text((540, 322), top_sub, font=f_sub, fill=(0, 240, 255), anchor="mm")

    # Lower Third Box
    draw.rounded_rectangle([160, 1380, 900, 1470], radius=10, fill=(8, 0, 18, 230))
    f_bot1 = get_font(28)
    draw.text((170, 1410), f"LIVE GAMEPLAY • {streamer_name.upper()}", font=f_bot1, fill=(255, 255, 255), anchor="lm")
    f_bot2 = get_font(20)
    clean_sub = "CRAZY GLITCH DISCOVERY" if is_glitch else "OFFICIAL GTA 6 GAMEPLAY & REACTION"
    draw.text((170, 1445), clean_sub, font=f_bot2, fill=(255, 136, 0), anchor="lm")

    img.save(out_overlay, format="PNG")


def create_ass_subtitles(out_ass: Path, streamer_name: str, is_glitch: bool):
    """Generates Vice City themed kinetic subtitles centered in the safe dock."""
    if is_glitch:
        dialogues = [
            ("0:00:01.00", "0:00:05.00", "ViceGold", f"😱 {streamer_name.upper()} DISCOVERS GTA 6 GLITCH!"),
            ("0:00:05.10", "0:00:10.00", "VicePink", "💀 THE GAME COMPLETELY BROKE!"),
            ("0:00:10.10", "0:00:16.00", "ViceCyan", "🔥 HOW DID THIS EVEN HAPPEN?!"),
            ("0:00:16.10", "0:00:22.00", "ViceGold", "⚡ LOOK AT THE MAP COLLISION!"),
            ("0:00:22.10", "0:00:28.00", "VicePink", "🚨 VEHICLE LAUNCHED INTO THE SKY!"),
            ("0:00:28.10", "0:00:35.00", "ViceCyan", "💥 SECRET EASTER EGG UNLOCKED?!"),
            ("0:00:35.10", "0:00:42.00", "ViceGold", "👀 THIS NEEDS TO BE PATCHED NOW!"),
            ("0:00:42.10", "0:00:50.00", "VicePink", "💀 HIS REACTION WAS UNREAL!"),
            ("0:00:50.10", "0:00:59.50", "ViceGold", "🔔 SUBSCRIBE TO 6 CLIPS FOR MORE!"),
        ]
    else:
        dialogues = [
            ("0:00:01.00", "0:00:05.00", "ViceGold", f"🌴 {streamer_name.upper()} EXPLORING VICE CITY!"),
            ("0:00:05.10", "0:00:10.00", "ViceCyan", "🔥 THIS GAMEPLAY IS NEXT LEVEL!"),
            ("0:00:10.10", "0:00:16.00", "VicePink", "😱 THE GRAPHICS ARE UNBELIEVABLE!"),
            ("0:00:16.10", "0:00:22.00", "ViceGold", "⚡ NEXT-GEN VEHICLE PHYSICS!"),
            ("0:00:22.10", "0:00:28.00", "ViceCyan", "🚨 5-STAR WANTED LEVEL RUN!"),
            ("0:00:28.10", "0:00:35.00", "VicePink", "💥 MAXIMUM CHAOS ON STREAM!"),
            ("0:00:35.10", "0:00:42.00", "ViceGold", "👀 CAN HE ESCAPE THE COPS?!"),
            ("0:00:42.10", "0:00:50.00", "ViceCyan", "🌴 6 CLIPS EXCLUSIVE MOMENT"),
            ("0:00:50.10", "0:00:59.50", "ViceGold", "🔔 DROP A LIKE & SUBSCRIBE!"),
        ]

    events_str = ""
    for start, end, style, text in dialogues:
        events_str += f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}\n"

    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ViceGold,Impact,62,&H0000D4FF,&H00000000,&H00120224,&H00000000,-1,0,0,0,100,100,2,0,1,6,4,2,40,40,580,1
Style: ViceCyan,Impact,62,&H00FFF500,&H00000000,&H00120224,&H00000000,-1,0,0,0,100,100,2,0,1,6,4,2,40,40,580,1
Style: VicePink,Impact,64,&H00800FFF,&H00000000,&H00120224,&H00000000,-1,0,0,0,100,100,2,0,1,7,4,2,40,40,580,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events_str}
"""
    with open(out_ass, "w", encoding="utf-8") as f:
        f.write(content)


def montage_video(raw_video: Path, overlay_img: Path, ass_file: Path, out_short: Path):
    """Crops center gameplay to phone 9:16 (cutting off facecam), applies branding & subtitles."""
    print(f"[*] Rendering phone-cropped gameplay Short: {out_short.name}...")
    clean_ass = str(ass_file).replace("\\", "/").replace(":", "\\:")
    cmd = [
        FFMPEG, "-y",
        "-i", str(raw_video),
        "-i", str(overlay_img),
        "-filter_complex",
        f"[0:v]crop=ih*9/16:ih:(iw-ow)/2:0,scale=1080:1920[v0];"
        f"[v0][1:v]overlay=0:0[v1];"
        f"[v1]ass='{clean_ass}'[outv];"
        f"[0:a]loudnorm=I=-14:LRA=7:TP=-1.5[outa]",
        "-map", "[outv]", "-map", "[outa]",
        "-t", "59.8",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "192k",
        str(out_short)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and out_short.exists()


def create_thumbnails(raw_video: Path, streamer_name: str, is_glitch: bool, out_thumb: Path, out_cover: Path):
    """Builds landscape thumbnail and vertical cover with high-CTR styling."""
    temp_frame = raw_video.parent / f"{raw_video.stem}_frame.jpg"
    subprocess.run([
        FFMPEG, "-y", "-ss", "00:00:15", "-i", str(raw_video),
        "-vframes", "1", "-q:v", "2", str(temp_frame)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not temp_frame.exists():
        return

    # Landscape 1280x720
    w, h = 1280, 720
    bg = ImageOps.fit(Image.open(temp_frame).convert("RGB"), (w, h))
    bg = Image.alpha_composite(bg.convert("RGBA"), Image.new("RGBA", (w, h), (10, 2, 25, 75)))
    draw = ImageDraw.Draw(bg)

    badge_txt = f"  🔴 GTA 6 GLITCH  " if is_glitch else f"  🔴 {streamer_name.upper()} GTA 6  "
    bbox = draw.textbbox((40, 40), badge_txt, font=get_font(28))
    draw.rounded_rectangle([bbox[0]-5, bbox[1]-5, bbox[2]+5, bbox[3]+5], radius=8, fill=(255, 15, 128, 240), outline=(0, 245, 255), width=2)
    draw.text((40, 40), badge_txt, font=get_font(28), fill=(255, 255, 255))

    line1 = "GAME BROKE?!" if is_glitch else f"{streamer_name.upper()} PLAYS GTA 6!"
    line2 = "CRAZY GLITCH" if is_glitch else "OFFICIAL GAMEPLAY"

    draw.text((46, 116), line1, font=get_font(76), fill=(0, 0, 0))
    draw.text((40, 110), line1, font=get_font(76), fill=(255, 212, 0))

    draw.text((46, 221), line2, font=get_font(56), fill=(0, 0, 0))
    draw.text((40, 215), line2, font=get_font(56), fill=(0, 245, 255))

    logo_path = BRANDING_DIR / "gta6_vi_clips_logo.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((260, 260), Image.Resampling.LANCZOS)
        bg.paste(logo, (w - logo.width - 40, 40), mask=logo)

    bg.convert("RGB").save(out_thumb, quality=95)

    # Vertical Cover 1080x1920
    vw, vh = 1080, 1920
    raw = Image.open(temp_frame).convert("RGB")
    cw = int(raw.height * 9 / 16)
    cx = (raw.width - cw) // 2
    vbg = raw.crop((cx, 0, cx + cw, raw.height)).resize((vw, vh), Image.Resampling.LANCZOS).convert("RGBA")

    overlay_path = BRANDING_DIR / "gta6_shorts_overlay.png"
    if overlay_path.exists():
        vbg = Image.alpha_composite(vbg, Image.open(overlay_path).convert("RGBA"))

    vdraw = ImageDraw.Draw(vbg)
    cov_line = "GTA 6 GLITCH" if is_glitch else "GTA 6 GAMEPLAY"
    vdraw.text((66, 246), cov_line, font=get_font(84), fill=(0, 0, 0))
    vdraw.text((60, 240), cov_line, font=get_font(84), fill=(255, 212, 0))

    vbg.convert("RGB").save(out_cover, quality=95)
    temp_frame.unlink(missing_ok=True)


def upload_to_youtube(video_path: Path, thumbnail_path: Path, streamer_name: str, is_glitch: bool):
    """Attempts direct automated upload to YouTube Shorts."""
    try:
        import youtube_uploader
        title = f"{streamer_name} DISCOVERS CRAZY GTA 6 GLITCH! 😱 #shorts" if is_glitch else f"{streamer_name} JUST PLAYED GTA 6 LIVE! 🌴🔥 #shorts"
        desc = f"{streamer_name} streaming GTA 6 gameplay live! Watch this crazy moment.\n\nSubscribe to 6 CLIPS for daily viral GTA 6 gameplay and highlights!\n\n#GTA6 #GTAVI #{streamer_name.replace(' ', '')} #Shorts #Gaming"
        tags = ["GTA6", "GTAVI", streamer_name, "Shorts", "Gaming", "GTA6Gameplay", "6Clips"]
        
        print(f"[*] Posting to YouTube: {title}")
        url = youtube_uploader.upload_short(video_path, title, desc, tags=tags, thumbnail_path=thumbnail_path, privacy="public")
        if url:
            print(f"[✓] Published successfully: {url}")
        else:
            print(f"[*] Video and thumbnails saved in automated_clips/ for GitHub artifact download.")
        return url
    except Exception as e:
        print(f"[!] YouTube upload step encountered: {e}")
        return None


def process_live_streamer(streamer_info: dict, num_clips: int = 3):
    """Executes capture, montage, thumbnails, and YouTube upload for a verified GTA 6 stream (num_clips times)."""
    name = streamer_info["name"]
    is_glitch = streamer_info["is_glitch"]

    for clip_idx in range(1, num_clips + 1):
        print(f"\n[*] Processing Clip {clip_idx}/{num_clips} for {name}...")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{streamer_info['id']}_{ts}_clip{clip_idx}"

        raw_path = OUTPUT_DIR / f"{prefix}_raw.mp4"
        overlay_path = OUTPUT_DIR / f"{prefix}_overlay.png"
        ass_path = OUTPUT_DIR / f"{prefix}_subs.ass"
        short_path = OUTPUT_DIR / f"{prefix}_short_1min.mp4"
        thumb_path = OUTPUT_DIR / f"{prefix}_thumb_1280x720.jpg"
        cover_path = OUTPUT_DIR / f"{prefix}_cover_1080x1920.jpg"

        # 1. Capture 60s stream
        success = capture_stream(streamer_info["url"], 60, raw_path)
        if not success:
            print(f"[!] Could not capture clip {clip_idx}. Moving to next.")
            continue

        # 2. Build assets
        create_dynamic_overlay(name, streamer_info["title"], is_glitch, overlay_path)
        create_ass_subtitles(ass_path, name, is_glitch)
        create_thumbnails(raw_path, name, is_glitch, thumb_path, cover_path)

        # 3. Montage 9:16 phone gameplay
        montaged = montage_video(raw_path, overlay_path, ass_path, short_path)
        overlay_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)

        if montaged:
            print(f"\n[🎉] SHORT {clip_idx}/{num_clips} READY: {short_path.name}")
            # 4. Upload to YouTube
            upload_to_youtube(short_path, thumb_path, name, is_glitch)

    if streamer_info.get("is_vod") and streamer_info.get("vod_id"):
        history_file = OUTPUT_DIR / "processed_vods.json"
        processed = []
        if history_file.exists():
            try:
                processed = json.loads(history_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        processed.append(streamer_info["vod_id"])
        history_file.write_text(json.dumps(processed), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Autonomous GTA 6 Stream Clipper & YouTube Publisher")
    parser.add_argument("--streamers", default="xqc,adinross,kaicenat,ishowspeed", help="Streamer IDs to monitor")
    parser.add_argument("--interval", default=600, type=int, help="Check interval in seconds (default: 600)")
    parser.add_argument("--clips-per-stream", default=3, type=int, help="Number of clips to generate per live stream (default: 3)")
    parser.add_argument("--oneshot", action="store_true", help="Check once and exit")
    args = parser.parse_args()

    active_ids = [s.strip().lower() for s in args.streamers.split(",") if s.strip()]
    print(f"[*] GTA 6 Clipper Active. Monitoring streamers: {', '.join(active_ids)}")
    print(f"[*] Rule: ONLY clipping when playing GTA 6 / Grand Theft Auto VI.")
    print(f"[*] Framing: 9:16 Phone Center-Crop (Gameplay Only, No Facecam).")
    print(f"[*] Publishing Target: YouTube Shorts ONLY.")
    print(f"[*] Target Clips per Stream: {args.clips_per_stream}")

    while True:
        for sid in active_ids:
            info = check_streamer(sid)
            if info.get("live"):
                print(f"[🔥] {info['name']} IS LIVE PLAYING GTA 6! (Glitch mode: {info['is_glitch']})")
                process_live_streamer(info, num_clips=args.clips_per_stream)
            else:
                pass

        if args.oneshot:
            break

        print(f"[*] Sleeping for {args.interval}s until next check...")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
