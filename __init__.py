# Ultroid - UserBot
# Copyright (C) 2021-2022 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

# ----------------------------------------------------------#
#                                                           #
#    _   _ _   _____ ____   ___ ___ ____   __     ______    #
#   | | | | | |_   _|  _ \ / _ \_ _|  _ \  \ \   / / ___|   #
#   | | | | |   | | | |_) | | | | || | | |  \ \ / / |       #
#   | |_| | |___| | |  _ <| |_| | || |_| |   \ V /| |___    #
#    \___/|_____|_| |_| \_\\___/___|____/     \_/  \____|   #
#                                                           #
# ----------------------------------------------------------#


import asyncio
import os
import re
import traceback
from time import time
from traceback import format_exc

from pytgcalls import PyTgCalls
from pytgcalls.types import GroupCallConfig
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
from pytgcalls.filters import stream_end
from telethon.errors.rpcerrorlist import (
    ParticipantJoinMissingError,
    ChatSendMediaForbiddenError,
)
from pyUltroid import HNDLR, LOGS, asst, udB, vcClient
from pyUltroid._misc._decorators import compile_pattern
from pyUltroid.fns.helper import (
    bash,
    downloader,
    inline_mention,
    mediainfo,
    time_formatter,
)
from pyUltroid.fns.admins import admin_check
from pyUltroid.fns.tools import is_url_ok
from pyUltroid.fns.ytdl import get_videos_link
from pyUltroid._misc import owner_and_sudos, sudoers
from pyUltroid._misc._assistant import in_pattern
from pyUltroid._misc._wrappers import eod, eor
from pyUltroid.version import __version__ as UltVer
from telethon import events
from telethon.tl import functions, types
from telethon.utils import get_display_name

try:
    from yt_dlp import YoutubeDL
except ImportError:
    YoutubeDL = None
    LOGS.error("'yt-dlp' not found!")

try:
   from youtubesearchpython import VideosSearch
except ImportError:
    VideosSearch = None

from strings import get_string

asstUserName = asst.me.username
LOG_CHANNEL = udB.get_key("LOG_CHANNEL")
ACTIVE_CALLS, VC_QUEUE = [], {}
MSGID_CACHE, VIDEO_ON = {}, {}

# py-tgcalls 2.x: single app instance (Telethon)
_pytgcalls_app = None


def _get_pytgcalls():
    global _pytgcalls_app
    if _pytgcalls_app is None:
        _pytgcalls_app = PyTgCalls(vcClient)
    return _pytgcalls_app


async def _ensure_pytgcalls_started():
    app = _get_pytgcalls()
    if not getattr(app, "_is_running", False):
        await app.start()
    return app


def VC_AUTHS():
    _vcsudos = udB.get_key("VC_SUDOS") or []
    return [int(a) for a in [*owner_and_sudos(), *_vcsudos]]


def _register_stream_end_handler():
    """Register stream-end handler once for queue playback (py-tgcalls 2.x)."""
    app = _get_pytgcalls()
    if getattr(app, "_vcbot_handler_registered", False):
        return
    from pytgcalls.types import StreamEnded

    @app.on_update(stream_end())
    async def _on_stream_ended(client, update: StreamEnded):
        if update.chat_id in VIDEO_ON:
            VIDEO_ON.pop(update.chat_id)
        await _play_from_queue(update.chat_id)

    app._vcbot_handler_registered = True


async def _play_from_queue(chat_id):
    """Play next from queue (used by stream-end handler and skip)."""
    app = _get_pytgcalls()
    current_chat = LOG_CHANNEL
    try:
        song, title, link, thumb, from_user, pos, dur = await get_from_queue(
            chat_id
        )
        try:
            await app.play(chat_id, song, GroupCallConfig(auto_start=True))
        except ParticipantJoinMissingError:
            pass
        except Exception:
            raise
        if MSGID_CACHE.get(chat_id):
            await MSGID_CACHE[chat_id].delete()
            del MSGID_CACHE[chat_id]
        text = f"<strong>🎧 Now playing #{pos}: <a href={link}>{title}</a>\n⏰ Duration:</strong> <code>{dur}</code>\n👤 <strong>Requested by:</strong> {from_user}"

        try:
            xx = await vcClient.send_message(
                current_chat,
                f"<strong>🎧 Now playing #{pos}: <a href={link}>{title}</a>\n⏰ Duration:</strong> <code>{dur}</code>\n👤 <strong>Requested by:</strong> {from_user}",
                file=thumb,
                link_preview=False,
                parse_mode="html",
            )
        except ChatSendMediaForbiddenError:
            xx = await vcClient.send_message(
                current_chat, text, link_preview=False, parse_mode="html"
            )
        MSGID_CACHE.update({chat_id: xx})
        VC_QUEUE[chat_id].pop(pos)
        if not VC_QUEUE[chat_id]:
            VC_QUEUE.pop(chat_id)

    except (IndexError, KeyError):
        try:
            await app.leave_call(chat_id)
        except NotInCallError:
            pass
        if chat_id in ACTIVE_CALLS:
            ACTIVE_CALLS.remove(chat_id)
        await vcClient.send_message(
            current_chat,
            f"• Successfully Left Vc : <code>{chat_id}</code> •",
            parse_mode="html",
        )
    except Exception as er:
        LOGS.exception(er)
        await vcClient.send_message(
            current_chat,
            f"<strong>ERROR:</strong> <code>{format_exc()}</code>",
            parse_mode="html",
        )


class Player:
    """Player using py-tgcalls 2.x (single PyTgCalls app, chat_id per call)."""

    def __init__(self, chat, event=None, video=False):
        self._chat = chat
        self._current_chat = event.chat_id if event else LOG_CHANNEL
        self._video = video

    @property
    def group_call(self):
        """Compat shim: expose is_connected and methods via a small wrapper."""
        return _PlayerCompat(self)

    async def _is_connected(self):
        app = _get_pytgcalls()
        gc = await app.group_calls()
        return self._chat in gc

    async def make_vc_active(self):
        try:
            await vcClient(
                functions.phone.CreateGroupCallRequest(
                    self._chat, title="🎧 Ultroid Music 🎶"
                )
            )
        except Exception as e:
            LOGS.exception(e)
            return False, e
        return True, None

    async def startCall(self):
        app = await _ensure_pytgcalls_started()
        _register_stream_end_handler()
        if VIDEO_ON:
            for c in list(VIDEO_ON):
                try:
                    await app.leave_call(c)
                except NotInCallError:
                    pass
            VIDEO_ON.clear()
            await asyncio.sleep(3)
        if self._video:
            for c in list(ACTIVE_CALLS):
                if c != self._chat:
                    try:
                        await app.leave_call(c)
                    except NotInCallError:
                        pass
                    if c in ACTIVE_CALLS:
                        ACTIVE_CALLS.remove(c)
            VIDEO_ON[self._chat] = True
        if self._chat not in ACTIVE_CALLS:
            try:
                await app.play(
                    self._chat,
                    None,
                    GroupCallConfig(auto_start=True),
                )
                ACTIVE_CALLS.append(self._chat)
            except NoActiveGroupCall as er:
                LOGS.info(er)
                dn, err = await self.make_vc_active()
                if err:
                    return False, err
                await app.play(
                    self._chat,
                    None,
                    GroupCallConfig(auto_start=True),
                )
                ACTIVE_CALLS.append(self._chat)
            except Exception as e:
                LOGS.exception(e)
                return False, e
        return True, None

    async def on_network_changed(self, call, is_connected):
        chat = self._chat
        if is_connected:
            if chat not in ACTIVE_CALLS:
                ACTIVE_CALLS.append(chat)
        elif chat in ACTIVE_CALLS:
            ACTIVE_CALLS.remove(chat)

    async def playout_ended_handler(self, call, source, mtype):
        if os.path.exists(source):
            os.remove(source)
        await self.play_from_queue()

    async def play_from_queue(self):
        await _play_from_queue(self._chat)

    async def vc_joiner(self):
        chat_id = self._chat
        done, err = await self.startCall()

        if done:
            await vcClient.send_message(
                self._current_chat,
                f"• Joined VC in <code>{chat_id}</code>",
                parse_mode="html",
            )

            return True
        await vcClient.send_message(
            self._current_chat,
            f"<strong>ERROR while Joining Vc -</strong> <code>{chat_id}</code> :\n<code>{err}</code>",
            parse_mode="html",
        )
        return False


class _PlayerCompat:
    """Compat layer so group_call.is_connected and group_call.start_audio etc. work with py-tgcalls 2.x."""

    def __init__(self, player: Player):
        self._player = player

    @property
    def is_connected(self):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return None
            return loop.run_until_complete(self._player._is_connected())
        except Exception:
            return False

    async def is_connected_async(self):
        return await self._player._is_connected()

    async def start_audio(self, source):
        app = await _ensure_pytgcalls_started()
        _register_stream_end_handler()
        await app.play(
            self._player._chat,
            source,
            GroupCallConfig(auto_start=True),
        )
        if self._player._chat not in ACTIVE_CALLS:
            ACTIVE_CALLS.append(self._player._chat)

    async def start_video(self, source, with_audio=True):
        app = await _ensure_pytgcalls_started()
        _register_stream_end_handler()
        await app.play(
            self._player._chat,
            source,
            GroupCallConfig(auto_start=True),
        )
        if self._player._chat not in ACTIVE_CALLS:
            ACTIVE_CALLS.append(self._player._chat)
        VIDEO_ON[self._player._chat] = True

    async def stop(self):
        app = _get_pytgcalls()
        try:
            await app.leave_call(self._player._chat)
        except NotInCallError:
            pass
        if self._player._chat in ACTIVE_CALLS:
            ACTIVE_CALLS.remove(self._player._chat)
        if self._player._chat in VIDEO_ON:
            VIDEO_ON.pop(self._player._chat)

    async def stop_video(self):
        if self._player._chat in VIDEO_ON:
            VIDEO_ON.pop(self._player._chat)

    async def set_my_volume(self, vol: int):
        app = _get_pytgcalls()
        await app.change_volume_call(self._player._chat, vol)

    async def reconnect(self):
        app = _get_pytgcalls()
        try:
            await app.leave_call(self._player._chat)
        except NotInCallError:
            pass
        await app.play(
            self._player._chat,
            None,
            GroupCallConfig(auto_start=True),
        )

    async def set_is_mute(self, muted: bool):
        app = _get_pytgcalls()
        if muted:
            await app.mute(self._player._chat)
        else:
            await app.unmute(self._player._chat)

    async def set_pause(self, paused: bool):
        app = _get_pytgcalls()
        if paused:
            await app.pause(self._player._chat)
        else:
            await app.resume(self._player._chat)

    def restart_playout(self):
        asyncio.ensure_future(
            self._player.play_from_queue(), loop=asyncio.get_event_loop()
        )


# --------------------------------------------------


def vc_asst(dec, **kwargs):
    def ult(func):
        kwargs["func"] = (
            lambda e: not e.is_private and not e.via_bot_id and not e.fwd_from
        )
        handler = udB.get_key("VC_HNDLR") or HNDLR
        kwargs["pattern"] = compile_pattern(dec, handler)
        vc_auth = kwargs.get("vc_auth", True)
        key = udB.get_key("VC_AUTH_GROUPS") or {}
        if "vc_auth" in kwargs:
            del kwargs["vc_auth"]

        async def vc_handler(e):
            VCAUTH = list(key.keys())
            if not (
                (e.out)
                or (e.sender_id in VC_AUTHS())
                or (vc_auth and e.chat_id in VCAUTH)
            ):
                return
            elif vc_auth and key.get(e.chat_id):
                cha, adm = key.get(e.chat_id), key[e.chat_id]["admins"]
                if adm and not (await admin_check(e)):
                    return
            try:
                await func(e)
            except Exception:
                LOGS.exception(Exception)
                await asst.send_message(
                    LOG_CHANNEL,
                    f"VC Error - <code>{UltVer}</code>\n\n<code>{e.text}</code>\n\n<code>{format_exc()}</code>",
                    parse_mode="html",
                )

        vcClient.add_event_handler(
            vc_handler,
            events.NewMessage(**kwargs),
        )

    return ult


# --------------------------------------------------


def add_to_queue(chat_id, song, song_name, link, thumb, from_user, duration):
    try:
        n = sorted(list(VC_QUEUE[chat_id].keys()))
        play_at = n[-1] + 1
    except BaseException:
        play_at = 1
    stuff = {
        play_at: {
            "song": song,
            "title": song_name,
            "link": link,
            "thumb": thumb,
            "from_user": from_user,
            "duration": duration,
        }
    }
    if VC_QUEUE.get(chat_id):
        VC_QUEUE[int(chat_id)].update(stuff)
    else:
        VC_QUEUE.update({chat_id: stuff})
    return VC_QUEUE[chat_id]


def list_queue(chat):
    if VC_QUEUE.get(chat):
        txt, n = "", 0
        for x in list(VC_QUEUE[chat].keys())[:18]:
            n += 1
            data = VC_QUEUE[chat][x]
            txt += f'<strong>{n}. <a href={data["link"]}>{data["title"]}</a> :</strong> <i>By: {data["from_user"]}</i>\n'
        txt += "\n\n....."
        return txt


async def get_from_queue(chat_id):
    play_this = list(VC_QUEUE[int(chat_id)].keys())[0]
    info = VC_QUEUE[int(chat_id)][play_this]
    song = info.get("song")
    title = info["title"]
    link = info["link"]
    thumb = info["thumb"]
    from_user = info["from_user"]
    duration = info["duration"]
    if not song:
        song = await get_stream_link(link)
    return song, title, link, thumb, from_user, play_this, duration


# --------------------------------------------------


async def download(query):
    if query.startswith("https://") and "youtube" not in query.lower():
        thumb, duration = None, "Unknown"
        title = link = query
    else:
        search = VideosSearch(query, limit=1).result()
        data = search["result"][0]
        link = data["link"]
        title = data["title"]
        duration = data.get("duration") or "♾"
        thumb = f"https://i.ytimg.com/vi/{data['id']}/hqdefault.jpg"
    dl = await get_stream_link(link)
    return dl, thumb, title, link, duration


async def get_stream_link(ytlink):
    """
    info = YoutubeDL({}).extract_info(url=ytlink, download=False)
    k = ""
    for x in info["formats"]:
        h, w = ([x["height"], x["width"]])
        if h and w:
            if h <= 720 and w <= 1280:
                k = x["url"]
    return k
    """
    stream = await bash(f'yt-dlp -g -f "best[height<=?720][width<=?1280]" {ytlink}')
    return stream[0]


async def vid_download(query):
    search = VideosSearch(query, limit=1).result()
    data = search["result"][0]
    link = data["link"]
    video = await get_stream_link(link)
    title = data["title"]
    thumb = f"https://i.ytimg.com/vi/{data['id']}/hqdefault.jpg"
    duration = data.get("duration") or "♾"
    return video, thumb, title, link, duration


async def dl_playlist(chat, from_user, link):
    # untill issue get fix
    # https://github.com/alexmercerind/youtube-search-python/issues/107
    """
    vids = Playlist.getVideos(link)
    try:
        vid1 = vids["videos"][0]
        duration = vid1["duration"] or "♾"
        title = vid1["title"]
        song = await get_stream_link(vid1['link'])
        thumb = f"https://i.ytimg.com/vi/{vid1['id']}/hqdefault.jpg"
        return song[0], thumb, title, vid1["link"], duration
    finally:
        vids = vids["videos"][1:]
        for z in vids:
            duration = z["duration"] or "♾"
            title = z["title"]
            thumb = f"https://i.ytimg.com/vi/{z['id']}/hqdefault.jpg"
            add_to_queue(chat, None, title, z["link"], thumb, from_user, duration)
    """
    links = await get_videos_link(link)
    try:
        search = VideosSearch(links[0], limit=1).result()
        vid1 = search["result"][0]
        duration = vid1.get("duration") or "♾"
        title = vid1["title"]
        song = await get_stream_link(vid1["link"])
        thumb = f"https://i.ytimg.com/vi/{vid1['id']}/hqdefault.jpg"
        return song, thumb, title, vid1["link"], duration
    finally:
        for z in links[1:]:
            try:
                search = VideosSearch(z, limit=1).result()
                vid = search["result"][0]
                duration = vid.get("duration") or "♾"
                title = vid["title"]
                thumb = f"https://i.ytimg.com/vi/{vid['id']}/hqdefault.jpg"
                add_to_queue(chat, None, title, vid["link"], thumb, from_user, duration)
            except Exception as er:
                LOGS.exception(er)


async def file_download(event, reply, fast_download=True):
    thumb = "https://telegra.ph/file/22bb2349da20c7524e4db.mp4"
    title = reply.file.title or reply.file.name or f"{str(time())}.mp4"
    file = reply.file.name or f"{str(time())}.mp4"
    if fast_download:
        dl = await downloader(
            f"vcbot/downloads/{file}",
            reply.media.document,
            event,
            time(),
            f"Downloading {title}...",
        )

        dl = dl.name
    else:
        dl = await reply.download_media()
    duration = (
        time_formatter(reply.file.duration * 1000) if reply.file.duration else "🤷‍♂️"
    )
    if reply.document.thumbs:
        thumb = await reply.download_media("vcbot/downloads/", thumb=-1)
    return dl, thumb, title, reply.message_link, duration


# --------------------------------------------------
