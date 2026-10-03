#!/usr/bin/env python3
"""A small fake Discord (REST + gateway) for testing Disports on the PC.

REST:    http://127.0.0.1:8811/api/v9/   (token: test-token)
Gateway: ws://127.0.0.1:8812/

One server, "Test Server", where our user (100) has the role "Muted":
  #general        normal
  #muted-hidden   the Muted role is denied View Channel (the role-deny bug)
  #read-only      @everyone is denied Send Messages
  #no-history     @everyone is denied Read Message History
  #slow           slowmode of 10 s
  #no-files       @everyone is denied Attach Files
Roles: Moderators (mentionable), Muted. Members: alice, bob, carol, dave.
A DM with Alice (2001); LIVE_DM=<seconds> makes a new message from her
arrive that long after signing in. #media is read up to 15 messages before
its end; LIVE_MEDIA=<seconds> sends a new message there every that often.

Uploads follow Discord's two steps: POST .../attachments gives an upload
URL, PUT sends the file there, then the message names the upload.
Everything received is logged to stdout, one line per event.
"""
import asyncio
import json
import os
import re
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websockets

TOKEN = "test-token"
BASE = "http://127.0.0.1:8811"


def user(uid, name, glob):
    return {"id": uid, "username": name, "global_name": glob, "avatar": None, "discriminator": "0"}


ME = user("100", "tester", "Test User")
ALICE = user("200", "alice", "Alice")
BOB = user("300", "bob", "Bob")
CAROL = user("400", "carol", "Carol")
DAVE = user("500", "dave", "Dave")
MEMBERS = [ALICE, BOB, CAROL, DAVE]
# Server nicknames (Test Server). History carries no member objects, as on
# Discord: the app must ask for the members to know them.
NICKS = {"200": "Ally", "300": "Bobby"}
# More people, for a full voice channel.
EXTRA = [user(str(600 + i), "guest%d" % i, "Guest %d" % i) for i in range(4)]

GUILD = "1000"
ROLE_MODS = "1900"
ROLE_MUTED = "1901"
VIEW, SEND, HISTORY, ATTACH, MENTION_EVERYONE = 0x400, 0x800, 0x10000, 0x8000, 0x20000
EVERYONE_PERMS = 0x400 | 0x800 | 0x10000 | 0x8000 | 0x40 | 0x100000 | 0x200000 | 0x4000000000

CATEGORY, GENERAL, HIDDEN, READONLY, NOHISTORY, SLOW, NOFILES = "1100", "1101", "1102", "1103", "1104", "1105", "1106"
LOUNGE, EMPTY_VOICE = "1107", "1108"
MEDIA = "1109"
TEXT = "1110"
QUIET, QUIET_CHAN = "5000", "5001"
DM = "2001"
# A DM with Bob, no call: calling him rings, and he declines.
BOB_DM = "2002"
# A group without a picture; INCOMING=1 rings us from it.
GROUP = "2003"


def overwrite(target, allow=0, deny=0, member=False):
    return {"id": target, "type": 1 if member else 0, "allow": str(allow), "deny": str(deny)}


# Threads in #general, sent once we subscribe to the server. Listed: one
# with a message an hour ago, and an old locked one we are in. Not listed:
# an old one we aren't in, and an archived one.
def thread(tid, name, archived=False, locked=False):
    return {"id": tid, "type": 11, "name": name, "guild_id": GUILD, "parent_id": GENERAL, "owner_id": "200",
            "thread_metadata": {"archived": archived, "locked": locked, "auto_archive_duration": 1440}}


THREAD, LOCKED_THREAD, OLD_THREAD, ARCHIVED_THREAD = str((int(time.time() * 1000) - 3600000 - 1420070400000) << 22), "1202", "1203", "1204"
THREADS = [thread(THREAD, "release plans"), thread(LOCKED_THREAD, "announcements chat", locked=True),
           thread(OLD_THREAD, "old chatter"), thread(ARCHIVED_THREAD, "old thread", archived=True)]
THREAD_MEMBERS = [{"id": LOCKED_THREAD, "user_id": "100", "join_timestamp": "2025-01-01T00:00:00+00:00", "flags": 0}]


CHANNELS = [
    {"id": CATEGORY, "type": 4, "name": "Text Channels", "position": 0},
    {"id": GENERAL, "type": 0, "name": "general", "position": 0, "parent_id": CATEGORY},
    {"id": HIDDEN, "type": 0, "name": "muted-hidden", "position": 1, "parent_id": CATEGORY,
     "permission_overwrites": [overwrite(ROLE_MUTED, deny=VIEW)]},
    {"id": READONLY, "type": 0, "name": "read-only", "position": 2, "parent_id": CATEGORY,
     "permission_overwrites": [overwrite(GUILD, deny=SEND)]},
    {"id": NOHISTORY, "type": 0, "name": "no-history", "position": 3, "parent_id": CATEGORY,
     "permission_overwrites": [overwrite(GUILD, deny=HISTORY)]},
    {"id": SLOW, "type": 0, "name": "slow", "position": 4, "parent_id": CATEGORY, "rate_limit_per_user": 10},
    {"id": NOFILES, "type": 0, "name": "no-files", "position": 5, "parent_id": CATEGORY,
     "permission_overwrites": [overwrite(GUILD, deny=ATTACH)]},
    {"id": LOUNGE, "type": 2, "name": "Lounge", "position": 6, "parent_id": CATEGORY},
    {"id": EMPTY_VOICE, "type": 2, "name": "Quiet room", "position": 7, "parent_id": CATEGORY},
    {"id": MEDIA, "type": 0, "name": "media", "position": 8, "parent_id": CATEGORY},
    {"id": TEXT, "type": 0, "name": "text", "position": 9, "parent_id": CATEGORY},
]
# Seven people in the Lounge: five are listed, then "and 2 more".
LOUNGE_PEOPLE = [ALICE, BOB, CAROL, DAVE] + EXTRA[:3]
# Bob is muted, Carol deafened (and so muted too).
def lounge_state(u):
    return {"guild_id": GUILD, "user_id": u["id"], "channel_id": LOUNGE, "session_id": "x",
            "self_mute": u in (BOB, CAROL), "self_deaf": u is CAROL}


def snowflake_at(ms):
    return str((int(ms) - 1420070400000) << 22)


# A DM call with Alice, started three minutes ago.
DM_CALL_MESSAGE = snowflake_at(time.time() * 1000 - 180000)

HISTORY_MSGS = {}
UPLOADS = {}
seq = 0
clients = set()
loop = None
next_id = 3000


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def new_id():
    global next_id
    next_id += 1
    return str(next_id)


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime(ts))


def message(channel, author, content, **extra):
    m = {"id": new_id(), "channel_id": channel, "author": author, "content": content,
         "timestamp": iso(time.time()), "edited_timestamp": None, "tts": False,
         "mention_everyone": False, "mentions": [], "mention_roles": [], "attachments": [],
         "embeds": [], "pinned": False, "type": 0}
    m.update(extra)
    return m


for ch in (GENERAL, NOHISTORY, SLOW, NOFILES, READONLY, DM, THREAD):
    HISTORY_MSGS[ch] = [message(ch, ALICE, "Hello from Alice in %s" % ch)]
HISTORY_MSGS[GROUP] = [message(GROUP, ALICE, "Who's coming on Saturday?")]
# Markdown in #general: heading, quote, subtext, list, code and a spoiler.
HISTORY_MSGS[GENERAL].append(message(GENERAL, BOB, "## Plans\n> Meet at the station\n> at **ten**\n-# small print here\n"
                                     "- bring `snacks`\n- and *water*\n```\nlet x = 1;\nlet y = 2;\n```\n"
                                     "The surprise is ||a cake||."))

# #media: 200 messages of pictures, videos, several pictures, link previews,
# for scrolling tests. The files are build/test/files/sticker.png (any
# picture), served under /files/.
def media_messages():
    out = []
    for i in range(200):
        kind = i % 4
        def att(n, w, h, video=False):
            return {"id": new_id(), "filename": "file%d-%d.%s" % (i, n, "mp4" if video else "png"),
                    "size": 1000, "width": w, "height": h,
                    "url": "%s/files/media/%d-%d.png" % (BASE, i, n), "proxy_url": "%s/files/media/%d-%d.png" % (BASE, i, n),
                    "content_type": "video/mp4" if video else "image/png"}
        if kind == 0:
            extra = {"attachments": [att(0, 1200, 800)]}
        elif kind == 1:
            extra = {"attachments": [att(0, 720, 1280, video=True)]}
        elif kind == 2:
            extra = {"attachments": [att(0, 800, 800), att(1, 640, 480), att(2, 480, 640)]}
        else:
            extra = {"embeds": [{"type": "link", "url": "https://example.com/%d" % i, "title": "A link %d" % i,
                                 "description": "Some text about the link, long enough to wrap onto a second line.",
                                 "thumbnail": {"url": "%s/files/media/%d-t.png" % (BASE, i),
                                               "proxy_url": "%s/files/media/%d-t.png" % (BASE, i), "width": 400, "height": 300}}]}
        out.append(message(MEDIA, [ALICE, BOB, CAROL][i % 3], "Message %d with media" % i, **extra))
    return out


HISTORY_MSGS[MEDIA] = media_messages()
# #text: 200 plain messages, to compare scrolling with #media.
HISTORY_MSGS[TEXT] = [message(TEXT, [ALICE, BOB, CAROL][i % 3],
                              "Plain message %d, long enough to take a couple of lines on a phone screen." % i)
                      for i in range(400)]
# The newest two reply to an earlier message: a recent one, and one 390
# messages back (far enough to ask whether to keep looking).
for i, text in ((395, "Replying to a recent one"), (10, "Replying to an old one")):
    old = HISTORY_MSGS[TEXT][i]
    HISTORY_MSGS[TEXT].append(message(TEXT, ME, text, type=19, referenced_message=old,
                                      message_reference={"type": 0, "message_id": old["id"], "channel_id": TEXT}))
# Quiet Server's #chat: links to channels and to a message, as the official
# client shares them; #muted-hidden can't be opened, so it stays a link.
HISTORY_MSGS[QUIET_CHAN] = [
    message(QUIET_CHAN, ALICE, "Channels: <#1105>, https://discord.com/channels/%s/%s and "
                               "https://discord.com/channels/%s/%s" % (GUILD, TEXT, GUILD, HIDDEN)),
    message(QUIET_CHAN, ALICE, "Look at this: https://discord.com/channels/%s/%s/%s"
                               % (GUILD, TEXT, HISTORY_MSGS[TEXT][395]["id"])),
]

def apng():
    """The APNG sticker: 64x64, red, then a green square drawn over its middle
    (blend over, area 32x32 at 16,16), then blue (replacing), half a second each."""
    def chunk(kind, body):
        return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")

    def pixels(w, h, rgba):
        return zlib.compress(b"".join(b"\0" + bytes(rgba) * w for _ in range(h)))

    def fctl(seq, w, h, x, y, blend):
        return chunk(b"fcTL", b"".join(v.to_bytes(4, "big") for v in (seq, w, h, x, y))
                     + (1).to_bytes(2, "big") + (2).to_bytes(2, "big") + bytes([0, blend]))

    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", (64).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0]))
    out += chunk(b"acTL", (3).to_bytes(4, "big") + (0).to_bytes(4, "big"))
    out += fctl(0, 64, 64, 0, 0, 0) + chunk(b"IDAT", pixels(64, 64, (220, 40, 40, 255)))
    out += fctl(1, 32, 32, 16, 16, 1) + chunk(b"fdAT", (2).to_bytes(4, "big") + pixels(32, 32, (40, 200, 40, 255)))
    out += fctl(3, 64, 64, 0, 0, 0) + chunk(b"fdAT", (4).to_bytes(4, "big") + pixels(64, 64, (40, 40, 220, 255)))
    return out + chunk(b"IEND", b"")


# Stickers, one of each format (1 PNG, 2 APNG, 3 Lottie, 4 GIF), in the DM.
# The fake CDN answers /stickers/<id>.png|gif with a small picture (and
# nothing for Lottie, which only exists as JSON).
STICKERS = [{"id": "7001", "name": "PNG sticker", "format_type": 1},
            {"id": "7002", "name": "APNG sticker", "format_type": 2},
            {"id": "7003", "name": "Wumpus wave", "format_type": 3},
            {"id": "7004", "name": "GIF sticker", "format_type": 4}]
HISTORY_MSGS[DM] += [message(DM, ALICE, "", sticker_items=[s]) for s in STICKERS]
# ...and a forwarded one (its sticker is in the snapshot).
HISTORY_MSGS[DM].append(message(DM, ALICE, "", message_reference={"type": 1, "channel_id": GENERAL, "message_id": "1"},
                                message_snapshots=[{"message": {"content": "", "timestamp": iso(time.time()),
                                                                "sticker_items": [STICKERS[0]]}}]))


# MANY_SERVERS=<n>: that many more servers, to scroll the server rail.
MANY_SERVERS = int(os.environ.get("MANY_SERVERS", "0"))


def varint(n):
    out = b""
    while True:
        byte, n = n & 0x7F, n >> 7
        out += bytes([byte | (0x80 if n else 0)])
        if not n:
            return out


def field(number, data):
    return varint(number << 3 | 2) + varint(len(data)) + data


# FOLDER=1: both test servers in a folder (the user settings protobuf).
def user_settings():
    if not os.environ.get("FOLDER"):
        return ""
    import base64
    import struct
    ids = b"".join(struct.pack("<Q", int(g)) for g in (GUILD, QUIET))
    folder = (field(1, ids) + field(2, varint(1 << 3) + varint(77)) + field(3, field(1, b"Folder"))
              + field(4, varint(1 << 3) + varint(0x3498DB)))
    return base64.b64encode(field(14, field(1, folder))).decode()


def extra_servers(everyone):
    return [{"id": str(6000 + i * 10), "properties": {"name": "Server %d" % (i + 1), "icon": None, "owner_id": "300"},
             "channels": [{"id": str(6001 + i * 10), "type": 0, "name": "chat", "position": 0}],
             "roles": [dict(everyone, id=str(6000 + i * 10))], "emojis": [], "voice_states": []}
            for i in range(MANY_SERVERS)]


def ready():
    for ch in CHANNELS:
        if ch["id"] in HISTORY_MSGS:
            ch["last_message_id"] = HISTORY_MSGS[ch["id"]][-1]["id"]
    roles = [
        {"id": GUILD, "name": "@everyone", "permissions": str(EVERYONE_PERMS), "position": 0,
         "color": 0, "hoist": False, "managed": False, "mentionable": False},
        {"id": ROLE_MODS, "name": "Moderators", "permissions": "0", "position": 2,
         "color": 0x3498db, "hoist": True, "managed": False, "mentionable": True},
        {"id": ROLE_MUTED, "name": "Muted", "permissions": "0", "position": 1,
         "color": 0, "hoist": False, "managed": False, "mentionable": False},
    ]
    return {
        "v": 9, "session_id": "s1", "session_type": "normal",
        "resume_gateway_url": "ws://127.0.0.1:8812",
        "user": ME,
        "user_settings_proto": user_settings(),
        "guilds": [{"id": GUILD, "properties": {"name": "Test Server", "icon": None, "owner_id": "300"},
                    "channels": CHANNELS, "roles": roles, "emojis": [], "member_count": 9,
                    "voice_states": [lounge_state(u) for u in LOUNGE_PEOPLE]},
                   {"id": QUIET, "properties": {"name": "Quiet Server", "icon": None, "owner_id": "300"},
                    "channels": [{"id": QUIET_CHAN, "type": 0, "name": "chat", "position": 0}],
                    "roles": [dict(roles[0], id=QUIET)], "emojis": [], "voice_states": []}]
                  + extra_servers(roles[0]),
        "users": MEMBERS,
        "merged_members": [[{"user_id": "100", "roles": [ROLE_MUTED], "nick": None}],
                           [{"user_id": "100", "roles": [], "nick": None}]]
                          + [[{"user_id": "100", "roles": [], "nick": None}] for _ in range(MANY_SERVERS)],
        "private_channels": [{"id": DM, "type": 1, "recipient_ids": ["200"],
                              "last_message_id": HISTORY_MSGS[DM][-1]["id"]},
                             {"id": BOB_DM, "type": 1, "recipient_ids": ["300"], "last_message_id": None},
                             {"id": GROUP, "type": 3, "name": "Weekend plans with the whole family and everyone else", "icon": None,
                              "recipient_ids": ["200", "300"], "last_message_id": None}],
        # #media was read up to 15 messages before its end.
        "read_state": {"entries": [{"id": MEDIA, "last_message_id": HISTORY_MSGS[MEDIA][-16]["id"],
                                    "mention_count": 0}], "version": 1},
        "relationships": [{"id": "200", "user_id": "200", "type": 1, "user": ALICE},
                          {"id": "300", "user_id": "300", "type": 1, "user": BOB}],
        "user_guild_settings": {"entries": [], "version": 0},
        "sessions": [], "guild_join_requests": [], "connected_accounts": [],
    }


async def dispatch(ws, event, data):
    global seq
    seq += 1
    await ws.send(json.dumps({"op": 0, "t": event, "s": seq, "d": data}))


def broadcast(event, data):
    for ws in list(clients):
        asyncio.run_coroutine_threadsafe(dispatch(ws, event, data), loop)


async def gateway(ws):
    log("GATEWAY connect")
    await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 41250}}))
    try:
        async for raw in ws:
            msg = json.loads(raw)
            op, d = msg.get("op"), msg.get("d")
            if op == 1:
                await ws.send(json.dumps({"op": 11}))
            elif op == 2:
                if d.get("token") != TOKEN:
                    await ws.close(4004, "Authentication failed")
                    return
                clients.add(ws)
                await dispatch(ws, "READY", ready())
                others = [str(6000 + i * 10) for i in range(MANY_SERVERS)]
                await dispatch(ws, "READY_SUPPLEMENTAL", {"guilds": [{"id": g} for g in [GUILD, QUIET] + others],
                               "merged_presences": {"friends": [], "guilds": [[] for _ in range(2 + len(others))]}})
                # LIVE_DM=<seconds>: a new DM from Alice arrives then (unread).
                if os.environ.get("LIVE_DM"):
                    async def live_dm(ws=ws):
                        await asyncio.sleep(float(os.environ["LIVE_DM"]))
                        msg = message(DM, ALICE, "A new message from Alice")
                        HISTORY_MSGS[DM].append(msg)
                        log("LIVE dm", msg["id"])
                        await dispatch(ws, "MESSAGE_CREATE", msg)
                    asyncio.create_task(live_dm())
                # LIVE_MEDIA=<seconds>: a new message in #media then, and
                # again every that many seconds.
                if os.environ.get("LIVE_MEDIA"):
                    async def live_media(ws=ws):
                        for n in range(5):
                            await asyncio.sleep(float(os.environ["LIVE_MEDIA"]))
                            msg = message(MEDIA, BOB, "Live message %d in #media" % n)
                            HISTORY_MSGS[MEDIA].append(msg)
                            log("LIVE media", msg["id"])
                            await dispatch(ws, "MESSAGE_CREATE", dict(msg, guild_id=GUILD))
                    asyncio.create_task(live_media())
                if os.environ.get("INCOMING"):
                    await dispatch(ws, "CALL_CREATE", {"channel_id": GROUP, "message_id": new_id(), "region": "x",
                                   "ringing": [ME["id"]], "voice_states": [
                                       {"user_id": "200", "channel_id": GROUP, "session_id": "z"}]})
                # Calls going on in DMs arrive after READY.
                await dispatch(ws, "CALL_CREATE", {"channel_id": DM, "message_id": DM_CALL_MESSAGE,
                               "region": "x", "ringing": [], "voice_states": [
                                   {"user_id": "200", "channel_id": DM, "session_id": "y"}]})
            elif op == 4:
                # Joining a voice channel: our voice state, and who is there.
                # (No voice server: the call stays connecting.)
                log("VOICE join", d.get("channel_id"))
                await dispatch(ws, "VOICE_STATE_UPDATE", dict(guild_id=d.get("guild_id"), user_id=ME["id"],
                               channel_id=d.get("channel_id"), session_id="me",
                               self_mute=d.get("self_mute", False), self_deaf=d.get("self_deaf", False)))
                if d.get("channel_id") == LOUNGE:
                    for u in LOUNGE_PEOPLE[:4]:
                        await dispatch(ws, "VOICE_STATE_UPDATE", lounge_state(u))
            elif op == 14:
                log("GATEWAY subscribe", json.dumps(d)[:200])
                if d.get("guild_id") == GUILD:
                    await dispatch(ws, "THREAD_LIST_SYNC", {"guild_id": GUILD, "channel_ids": [GENERAL],
                                                            "threads": THREADS, "members": THREAD_MEMBERS})
            elif op == 8:
                query = (d.get("query") or "").lower()
                ids = d.get("user_ids") or []
                everyone = MEMBERS + EXTRA
                if ids:
                    found = [m for m in everyone if m["id"] in [str(i) for i in ids]]
                else:
                    found = [m for m in MEMBERS if m["username"].startswith(query) or m["global_name"].lower().startswith(query)]
                log("GATEWAY member search", json.dumps(query or ids), "->", [m["username"] for m in found])
                await dispatch(ws, "GUILD_MEMBERS_CHUNK", {
                    "guild_id": d.get("guild_id") if isinstance(d.get("guild_id"), str) else GUILD,
                    "members": [{"user": m, "roles": [ROLE_MODS] if m is BOB else [], "nick": NICKS.get(m["id"]),
                                 "joined_at": iso(0)} for m in found],
                    "not_found": [], "chunk_index": 0, "chunk_count": 1})
            else:
                log("GATEWAY op", op, json.dumps(d)[:200])
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.discard(ws)


# Captchas, with hCaptcha's test site key: its solution is always this.
CAPTCHA_SOLUTION = "10000000-aaaa-bbbb-cccc-000000000001"
CAPTCHA = {"captcha_key": ["captcha-required"], "captcha_service": "hcaptcha",
           "captcha_sitekey": "10000000-ffff-ffff-ffff-000000000001", "captcha_session_id": "test-session",
           "captcha_rqdata": "test-rqdata", "captcha_rqtoken": "test-rqtoken"}
# Accounts for the password sign-in; mfa@ has two-factor: code 123456 (app
# or SMS), or the backup code abcd1234.
PASSWORD = "hunter22"
MFA_TICKET = "test-ticket"


class Rest(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body=None, raw=None, content_type="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def captcha_solved(self, what):
        """True when this request carries the solved captcha; else answers
        with a captcha challenge."""
        key = self.headers.get("X-Captcha-Key")
        if key is None:
            log("REST captcha asked", what)
            self.reply(400, CAPTCHA)
            return False
        ok = (key == CAPTCHA_SOLUTION and self.headers.get("X-Captcha-Session-Id") == "test-session"
              and self.headers.get("X-Captcha-Rqtoken") == "test-rqtoken")
        log("REST captcha", "solved" if ok else "wrong", what)
        if not ok:
            self.reply(400, CAPTCHA)
        return ok

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length)

    def do_GET(self):
        path = self.path.split("?")[0]
        if re.match(r"/assets/[0-9a-f]+\.mp3$", path):
            log("REST ringtone", path)
            return self.reply(200, raw=b"\xff\xfb" * 2048, content_type="audio/mpeg")
        m = re.match(r"/api/v9/users/(\d+)/profile$", path)
        if m:
            person = next((u for u in MEMBERS + EXTRA if u["id"] == m.group(1)), None)
            if person is None:
                return self.reply(404, {"message": "Unknown User", "code": 10013})
            log("REST profile", m.group(1))
            return self.reply(200, {"user": dict(person, bio="Hi! I test Disports.\nSecond line of my bio."),
                                    "user_profile": {"bio": "Hi! I test Disports.\nSecond line of my bio.",
                                                     "pronouns": "she/her"}})
        if path == "/api/v9/experiments":
            return self.reply(200, {"fingerprint": "test-fingerprint", "assignments": []})
        if path == "/api/v9/gateway":
            return self.reply(200, {"url": "ws://127.0.0.1:8812"})
        m = re.match(r"/api/v9/channels/(\d+)/messages$", path)
        if m:
            # As Discord: newest first, at most `limit`, older than `before`.
            channel = m.group(1)
            query = dict(q.split("=", 1) for q in self.path.split("?", 1)[1].split("&")) if "?" in self.path else {}
            limit = int(query.get("limit", 50))
            before = int(query.get("before", 0) or 0)
            msgs = [x for x in HISTORY_MSGS.get(channel, []) if not before or int(x["id"]) < before]
            page = list(reversed(msgs))[:limit]
            log("REST history", channel, "before", before or "-", "->", len(page), "newest", page[0]["id"] if page else "-")
            return self.reply(200, page)
        # The Lottie sticker: a blue rounded square, turning once a second.
        if path == "/stickers/7003.json":
            spin = {"a": 1, "k": [{"t": 0, "s": [0], "e": [360], "i": {"x": [0.5], "y": [0.5]},
                                   "o": {"x": [0.5], "y": [0.5]}}, {"t": 30}]}
            square = {"ty": "gr", "it": [
                {"ty": "rc", "d": 1, "s": {"a": 0, "k": [90, 90]}, "p": {"a": 0, "k": [0, 0]}, "r": {"a": 0, "k": 14}},
                {"ty": "fl", "c": {"a": 0, "k": [0.35, 0.4, 0.8, 1]}, "o": {"a": 0, "k": 100}},
                {"ty": "tr", "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]},
                 "r": {"a": 0, "k": 0}, "o": {"a": 0, "k": 100}}]}
            lottie = {"v": "5.5.2", "fr": 30, "ip": 0, "op": 30, "w": 160, "h": 160, "nm": "spin", "ddd": 0, "assets": [],
                      "layers": [{"ddd": 0, "ind": 1, "ty": 4, "nm": "square", "sr": 1, "ao": 0, "ip": 0, "op": 30,
                                  "st": 0, "bm": 0, "shapes": [square],
                                  "ks": {"o": {"a": 0, "k": 100}, "r": spin, "p": {"a": 0, "k": [80, 80, 0]},
                                         "a": {"a": 0, "k": [0, 0, 0]}, "s": {"a": 0, "k": [100, 100, 100]}}}]}
            log("REST lottie sticker")
            return self.reply(200, lottie)
        if path == "/stickers/7002.png":
            log("REST apng sticker")
            return self.reply(200, raw=apng(), content_type="image/png")
        m = re.match(r"/stickers/(\d+)\.(png|gif)$", path)
        if m and m.group(1) in ("7001", "7004"):
            picture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "build", "test", "files", "sticker.png")
            # MEDIA_DELAY=<seconds>: pictures arrive late, as on a slow network.
            time.sleep(float(os.environ.get("MEDIA_DELAY", "0")))
            if os.path.exists(picture):
                return self.reply(200, raw=open(picture, "rb").read(), content_type="image/png")
        if path.startswith("/files/media/"):
            picture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "build", "test", "files", "sticker.png")
            # MEDIA_DELAY=<seconds>: pictures arrive late, as on a slow network.
            time.sleep(float(os.environ.get("MEDIA_DELAY", "0")))
            if os.path.exists(picture):
                return self.reply(200, raw=open(picture, "rb").read(), content_type="image/png")
        m = re.match(r"/files/(\d+)/(.+)$", path)
        if m and m.group(1) in UPLOADS:
            return self.reply(200, raw=UPLOADS[m.group(1)]["data"], content_type="application/octet-stream")
        return self.reply(200, {})

    def do_PUT(self):
        m = re.match(r"/upload/(\d+)$", self.path)
        if m and m.group(1) in UPLOADS:
            data = self.body()
            UPLOADS[m.group(1)]["data"] = data
            log("REST upload PUT", m.group(1), len(data), "bytes, content-type",
                self.headers.get("Content-Type"))
            return self.reply(200)
        return self.reply(404, {"message": "Unknown"})

    def do_POST(self):
        raw = self.body()
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        path = self.path
        if path == "/api/v9/auth/login":
            if self.headers.get("X-Fingerprint") != "test-fingerprint":
                log("REST login without fingerprint")
            if not self.captcha_solved("login"):
                return
            login = body.get("login", "")
            if body.get("password") != PASSWORD or login not in ("tester@example.com", "mfa@example.com"):
                log("REST login invalid", login)
                return self.reply(400, {"code": 50035, "message": "Invalid Form Body", "errors": {
                    "login": {"_errors": [{"code": "INVALID_LOGIN", "message": "Login or password is invalid."}]},
                    "password": {"_errors": [{"code": "INVALID_LOGIN", "message": "Login or password is invalid."}]}}})
            if login == "mfa@example.com":
                log("REST login needs mfa")
                return self.reply(200, {"user_id": ME["id"], "mfa": True, "sms": True, "totp": True, "backup": True,
                                        "ticket": MFA_TICKET, "login_instance_id": "test-instance"})
            log("REST login ok", login)
            return self.reply(200, {"user_id": ME["id"], "token": TOKEN,
                                    "user_settings": {"locale": "en-US", "theme": "dark"}})
        if path == "/api/v9/auth/mfa/sms/send":
            log("REST mfa sms")
            return self.reply(200, {"phone": "+*******1234"})
        m = re.match(r"/api/v9/auth/mfa/(totp|sms|backup)$", path)
        if m:
            code = "abcd1234" if m.group(1) == "backup" else "123456"
            if body.get("ticket") != MFA_TICKET or body.get("code") != code:
                log("REST mfa wrong", m.group(1))
                return self.reply(400, {"code": 60008, "message": "Invalid two-factor code"})
            log("REST mfa ok", m.group(1))
            return self.reply(200, {"token": TOKEN, "user_settings": {"locale": "en-US", "theme": "dark"}})
        m = re.match(r"/api/v9/channels/(\d+)/attachments$", path)
        if m:
            results = []
            for f in body.get("files", []):
                upload = new_id()
                UPLOADS[upload] = {"name": f["filename"], "size": f.get("file_size"), "data": b""}
                results.append({"id": int(f["id"]), "upload_url": "%s/upload/%s" % (BASE, upload),
                                "upload_filename": "uploads/%s/%s" % (upload, f["filename"])})
            log("REST attachments", json.dumps(body))
            return self.reply(200, {"attachments": results})
        m = re.match(r"/api/v9/channels/(\d+)/messages$", path)
        if m:
            channel = m.group(1)
            # Messages asking for one get a captcha first (any request can).
            if "captcha" in body.get("content", "") and not self.captcha_solved("send " + channel):
                return
            log("REST send", channel, json.dumps(body, ensure_ascii=False))
            attachments = []
            for a in body.get("attachments", []):
                upload = a["uploaded_filename"].split("/")[1]
                info = UPLOADS.get(upload, {})
                attachments.append({"id": new_id(), "filename": a["filename"], "size": len(info.get("data", b"")),
                                    "url": "%s/files/%s/%s" % (BASE, upload, a["filename"]),
                                    "proxy_url": "%s/files/%s/%s" % (BASE, upload, a["filename"]),
                                    "content_type": "image/png" if a["filename"].endswith(".png") else "text/plain"})
            msg = message(channel, ME, body.get("content", ""), nonce=body.get("nonce"), attachments=attachments)
            if channel != DM:
                msg["guild_id"] = GUILD
            HISTORY_MSGS.setdefault(channel, []).append(msg)
            broadcast("MESSAGE_CREATE", msg)
            return self.reply(200, msg)
        m = re.match(r"/api/v9/channels/(\d+)/call/ring$", path)
        if m:
            channel = m.group(1)
            log("REST ring", channel)
            broadcast("CALL_CREATE", {"channel_id": channel, "message_id": new_id(), "region": "x",
                                      "ringing": ["300"], "voice_states": []})
            # Bob declines after 3 seconds.
            def decline():
                log("LIVE decline", channel)
                broadcast("CALL_UPDATE", {"channel_id": channel, "region": "x", "ringing": [], "voice_states": []})
            threading.Timer(3, decline).start()
            return self.reply(204)
        m = re.match(r"/api/v9/channels/(\d+)/messages/(\d+)/ack$", path)
        if m:
            log("REST ack", m.group(1), m.group(2))
            return self.reply(200, {"token": None})
        if path.endswith("/typing"):
            return self.reply(204)
        log("REST POST (unhandled)", path)
        return self.reply(404, {"message": "Unknown"})


async def main():
    global loop
    loop = asyncio.get_running_loop()
    server = ThreadingHTTPServer(("127.0.0.1", 8811), Rest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    async with websockets.serve(gateway, "127.0.0.1", 8812):
        log("fake discord ready")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
