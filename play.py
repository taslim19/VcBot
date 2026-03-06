# Ultroid - UserBot
# Copyright (C) 2021-2022 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

"""
✘ Commands Available -

• `{i}play <song name/song url/reply to file>`
   Play the song in voice chat, or add the song to queue.

• `{i}playfrom <channel username> ; <limit>`
   Play music from channel files at current chat..

• `{i}radio <link>`
   Stream Live Radio m3u8 links.

• `{i}ytlive <link>`
   Stream Live YouTube
"""

import re,os
from telethon.tl import types
from . import vc_asst, get_string, inline_mention, add_to_queue, mediainfo, file_download, LOGS, is_url_ok, bash, download, Player, VC_QUEUE
from telethon.errors.rpcerrorlist import ChatSendMediaForbiddenError, MessageIdInvalidError


@vc_asst("play")
async def play_music_(event):
    if "playfrom" in event.text.split()[0]:
        return  # For PlayFrom Conflict
    try:
        xx = await event.eor(get_string("com_1"), parse_mode="md")
    except MessageIdInvalidError:
        # Changing the way, things work
        xx = event
        xx.out = False
    chat = event.chat_id
    from_user = inline_mention(event.sender, html=True)
    reply, song = None, None
    if event.reply_to:
        reply = await event.get_reply_message()
    if len(event.text.split()) > 1:
        input = event.text.split(maxsplit=1)[1]
        tiny_input = input.split()[0]
        if tiny_input[0] in ["@", "-"]:
            try:
                chat = await event.client.parse_id(tiny_input)
            except Exception as er:
                LOGS.exception(er)
                return await xx.edit(str(er))
            try:
                song = input.split(maxsplit=1)[1]
            except IndexError:
                pass
            except Exception as e:
                return await event.eor(str(e))
        else:
            song = input
    if not (reply or song):
        return await xx.eor("Please specify a song name or reply to a audio file !", time=5
        )
    await xx.eor(get_string("vcbot_20"), parse_mode="md")
    if reply and reply.media and mediainfo(reply.media).startswith(("audio", "video")):
        song, thumb, song_name, link, duration = await file_download(xx, reply)
    else:
        song, thumb, song_name, link, duration = await download(song)
        if len(link.strip().split()) > 1:
            link = link.strip().split()
    ultSongs = Player(chat, event)
    song_name = f"{song_name[:30]}..."
    if not (await ultSongs.group_call.is_connected_async()):
        if not (await ultSongs.vc_joiner()):
            return
        await ultSongs.group_call.start_audio(song)
        if isinstance(link, list):
            for lin in link[1:]:
                add_to_queue(chat, song, lin, lin, None, from_user, duration)
            link = song_name = link[0]
        text = "🎸 <strong>Now playing: <a href={}>{}</a>\n⏰ Duration:</strong> <code>{}</code>\n👥 <strong>Chat:</strong> <code>{}</code>\n🙋‍♂ <strong>Requested by: {}</strong>".format(
            link, song_name, duration, chat, from_user
        )
        try:
            await xx.reply(
                text,
                file=thumb,
                link_preview=False,
                parse_mode="html",
            )
            await xx.delete()
        except ChatSendMediaForbiddenError:
            await xx.eor(text, link_preview=False)
        if thumb and os.path.exists(thumb):
            os.remove(thumb)
    else:
        if not (
            reply
            and reply.media
            and mediainfo(reply.media).startswith(("audio", "video"))
        ):
            song = None
        if isinstance(link, list):
            for lin in link[1:]:
                add_to_queue(chat, song, lin, lin, None, from_user, duration)
            link = song_name = link[0]
        add_to_queue(chat, song, song_name, link, thumb, from_user, duration)
        return await xx.eor(
            f"▶ Added 🎵 <a href={link}>{song_name}</a> to queue at #{list(VC_QUEUE[chat].keys())[-1]}.",
            parse_mode="html",
        )


@vc_asst("playfrom")
async def play_music_(event):
    msg = await event.eor(get_string("com_1"))
    chat = event.chat_id
    limit = 10
    from_user = inline_mention(await event.get_sender(), html=True)
    if len(event.text.split()) <= 1:
        return await msg.edit(
            "Use in Proper Format\n`.playfrom <channel username> ; <limit>`"
        )
    input = event.text.split(maxsplit=1)[1]
    if ";" in input:
        try:
            limit = input.split(";")
            input = limit[0].strip()
            limit = int(limit[1].strip()) if limit[1].strip().isdigit() else 10
            input = await event.client.parse_id(input)
        except (IndexError, ValueError):
            pass
    try:
        fromchat = (await event.client.get_entity(input)).id
    except Exception as er:
        return await msg.eor(str(er))
    await msg.eor("`• Started Playing from Channel....`")
    send_message = True
    ultSongs = Player(chat, event)
    count = 0
    async for song in event.client.iter_messages(
        fromchat, limit=limit, wait_time=5, filter=types.InputMessagesFilterMusic
    ):
        count += 1
        song, thumb, song_name, link, duration = await file_download(
            msg, song, fast_download=False
        )
        song_name = f"{song_name[:30]}..."
        if not (await ultSongs.group_call.is_connected_async()):
            if not (await ultSongs.vc_joiner()):
                return
            await ultSongs.group_call.start_audio(song)
            text = "🎸 <strong>Now playing: <a href={}>{}</a>\n⏰ Duration:</strong> <code>{}</code>\n👥 <strong>Chat:</strong> <code>{}</code>\n🙋‍♂ <strong>Requested by: {}</strong>".format(
                link, song_name, duration, chat, from_user
            )
            try:
                await msg.reply(
                    text,
                    file=thumb,
                    link_preview=False,
                    parse_mode="html",
                )
            except ChatSendMediaForbiddenError:
                await msg.reply(text, link_preview=False, parse_mode="html")
            if thumb and os.path.exists(thumb):
                os.remove(thumb)
        else:
            add_to_queue(chat, song, song_name, link, thumb, from_user, duration)
            if send_message and count == 1:
                await msg.eor(
                    f"▶ Added 🎵 <strong><a href={link}>{song_name}</a></strong> to queue at <strong>#{list(VC_QUEUE[chat].keys())[-1]}.</strong>",
                    parse_mode="html",
                )
                send_message = False


@vc_asst("radio")
async def radio_mirchi(e):
    xx = await e.eor(get_string("com_1"))
    if len(e.text.split()) <= 1:
        return await xx.eor("Are You Kidding Me?\nWhat to Play?")
    input = e.text.split()
    if input[1][0] in ["-", "@"]:
        try:
            chat = await e.client.parse_id(input[1])
        except Exception as er:
            return await xx.edit(str(er))
        song = e.text.split(maxsplit=2)[2]
    else:
        song = e.text.split(maxsplit=1)[1]
        chat = e.chat_id
    if not is_url_ok(song):
        return await xx.eor(f"`{song}`\n\nNot a playable link.🥱")
    ultSongs = Player(chat, e)
    if not (await ultSongs.group_call.is_connected_async()) and not (await ultSongs.vc_joiner()):
        return
    await ultSongs.group_call.start_audio(song)
    await xx.reply(
        f"• Started Radio 📻\n\n• Station : `{song}`",
        file="https://telegra.ph/file/d09d4461199bdc7786b01.mp4",
    )
    await xx.delete()


@vc_asst("(live|ytlive)")
async def live_stream(e):
    xx = await e.eor(get_string("com_1"))
    if len(e.text.split()) <= 1:
        return await xx.eor("Are You Kidding Me?\nWhat to Play?")
    input = e.text.split()
    if input[1][0] in ["@", "-"]:
        chat = await e.client.parse_id(input[1])
        song = e.text.split(maxsplit=2)[2]
    else:
        song = e.text.split(maxsplit=1)[1]
        chat = e.chat_id
    if not is_url_ok(song):
        return await xx.eor(f"`{song}`\n\nNot a playable link.🥱")
    is_live_vid = False
    if re.search("youtu", song):
        is_live_vid = (await bash(f'youtube-dl -j "{song}" | jq ".is_live"'))[0]
    if is_live_vid != "true":
        return await xx.eor(f"Only Live Youtube Urls supported!\n{song}")
    file, thumb, title, link, duration = await download(song)
    ultSongs = Player(chat, e)
    if not (await ultSongs.group_call.is_connected_async()) and not (await ultSongs.vc_joiner()):
        return
    from_user = inline_mention(e.sender)
    await xx.reply(
        "🎸 **Now playing:** [{}]({})\n⏰ **Duration:** `{}`\n👥 **Chat:** `{}`\n🙋‍♂ **Requested by:** {}".format(
            title, link, duration, chat, from_user
        ),
        file=thumb,
        link_preview=False,
    )
    await xx.delete()
    await ultSongs.group_call.start_audio(file)
