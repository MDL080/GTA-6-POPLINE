#!/usr/bin/env python3
"""
youtube_uploader.py - Automated YouTube Shorts Uploader
=======================================================
Uploads video files directly to YouTube with automated metadata, gaming category,
tags, and custom thumbnail support using the official Google YouTube Data API v3.
"""

import os
import sys
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "youtube_token.json"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"
if not CLIENT_SECRETS_FILE.exists() and (BASE_DIR / "clientsecret.json").exists():
    CLIENT_SECRETS_FILE = BASE_DIR / "clientsecret.json"


def get_authenticated_service():
    """Authenticates using stored token or runs a one-time OAuth browser authorization."""
    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            print(f"[!] Warning reading token: {e}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[*] Refreshing expired YouTube token...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                print(f"[!] Error: {CLIENT_SECRETS_FILE.name} not found in {BASE_DIR}.", file=sys.stderr)
                print("    Please place your Google Cloud OAuth client_secrets.json file in this directory.", file=sys.stderr)
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
            print(f"[+] Saved authorization to {TOKEN_FILE.name}")

    return build("youtube", "v3", credentials=creds)


def upload_short(video_path: Path, title: str, description: str, tags: list = None,
                 thumbnail_path: Path = None, privacy: str = "public") -> str:
    """Uploads a video to YouTube as a Short."""
    if not video_path.exists():
        print(f"[!] Video not found: {video_path}")
        return None

    youtube = get_authenticated_service()
    if not youtube:
        return None

    if tags is None:
        tags = ["GTA6", "GTAVI", "Shorts", "Gaming", "GTA6Gameplay", "KickStreamer", "6Clips"]

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "20"  # 20 = Gaming
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    print(f"[*] Uploading '{video_path.name}' to YouTube ({privacy})...")
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    video_url = f"https://youtube.com/shorts/{video_id}"
    print(f"[🎉] Upload Complete! Video ID: {video_id}")
    print(f"     URL: {video_url}")

    if thumbnail_path and thumbnail_path.exists():
        try:
            print(f"[*] Setting custom thumbnail: {thumbnail_path.name}...")
            thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            print("[+] Custom thumbnail applied!")
        except Exception as e:
            print(f"[!] Warning setting thumbnail: {e}")

    return video_url


if __name__ == "__main__":
    if len(sys.argv) > 1:
        v_path = Path(sys.argv[1])
        t_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        upload_short(v_path, "GTA 6 GAMEPLAY LIVE #shorts", "Watch this insane GTA 6 moment!", thumbnail_path=t_path)
    else:
        print("Usage: python youtube_uploader.py video.mp4 [thumbnail.jpg]")
