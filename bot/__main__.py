from time import time, monotonic
from datetime import datetime
from sys import executable
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather, run as asyrun
from uuid import uuid4
from base64 import b64decode
from importlib import import_module, reload

from requests import get as rget
from pytz import timezone
from bs4 import BeautifulSoup
from signal import signal, SIGINT
from aiofiles.os import path as aiopath, remove as aioremove
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, private, regex
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import bot, user, bot_name, config_dict, user_data, botStartTime, LOGGER, Interval, DATABASE_URL, QbInterval, INCOMPLETE_TASK_NOTIFIER, scheduler, bot_cache
from bot.version import get_version
from .helper.ext_utils.fs_utils import start_cleanup, clean_all, exit_clean_up
from .helper.ext_utils.bot_utils import get_readable_time, cmd_exec, sync_to_async, new_task, set_commands, update_user_ldata, get_stats
from .helper.ext_utils.db_handler import DbManger
from .helper.telegram_helper.bot_commands import BotCommands
from .helper.telegram_helper.message_utils import sendMessage, editMessage, editReplyMarkup, sendFile, deleteMessage, delete_all_messages
from .helper.telegram_helper.filters import CustomFilters
from .helper.telegram_helper.button_build import ButtonMaker
from .helper.listeners.aria2_listener import start_aria2_listener
from .helper.themes import BotTheme
from .modules import authorize, clone, gd_count, gd_delete, gd_list, cancel_mirror, mirror_leech, status, torrent_search, torrent_select, ytdlp, \
                     rss, shell, eval, users_settings, bot_settings, speedtest, save_msg, images, imdb, anilist, mediainfo, mydramalist, gen_pyro_sess, \
                     gd_clean, broadcast, category_select

async def stats(client, message):
    msg, btns = await get_stats(message)
    await sendMessage(message, msg, btns, photo='IMAGES')

@new_task
async def start(client, message):
    buttons = ButtonMaker()
    buttons.ubutton(BotTheme('ST_BN1_NAME'), BotTheme('ST_BN1_URL'))
    buttons.ubutton(BotTheme('ST_BN2_NAME'), BotTheme('ST_BN2_URL'))
    reply_markup = buttons.build_menu(2)
    cmd_len = len(message.command)
    if cmd_len > 1:
        if message.command[1] == "wzmlx":
            await deleteMessage(message)
            return
        if config_dict['TOKEN_TIMEOUT']:
            userid = message.from_user.id
            encrypted_url = message.command[1]
            try:
                input_token, pre_uid = (b64decode(encrypted_url.encode()).decode()).split('&&')
            except Exception:
                return await sendMessage(message, BotTheme('OWN_TOKEN_GENERATE'))
            if int(pre_uid) != userid:
                return await sendMessage(message, BotTheme('OWN_TOKEN_GENERATE'))
            data = user_data.get(userid, {})
            if 'token' not in data or data['token'] != input_token:
                return await sendMessage(message, BotTheme('USED_TOKEN'))
            elif config_dict['LOGIN_PASS'] is not None and data['token'] == config_dict['LOGIN_PASS']:
                return await sendMessage(message, BotTheme('LOGGED_PASSWORD'))
            buttons.ibutton(BotTheme('ACTIVATE_BUTTON'), f'pass {input_token}', 'header')
            reply_markup = buttons.build_menu(2)
            msg = BotTheme('TOKEN_MSG', token=input_token, validity=get_readable_time(int(config_dict["TOKEN_TIMEOUT"])))
            return await sendMessage(message, msg, reply_markup)
    if await CustomFilters.authorized(client, message):
        start_string = BotTheme('ST_MSG', help_command=f"/{BotCommands.HelpCommand}")
        await sendMessage(message, start_string, reply_markup, photo='IMAGES')
    elif config_dict['BOT_PM']:
        await sendMessage(message, BotTheme('ST_BOTPM'), reply_markup, photo='IMAGES')
    else:
        await sendMessage(message, BotTheme('ST_UNAUTH'), reply_markup, photo='IMAGES')
    await DbManger().update_pm_users(message.from_user.id)

async def token_callback(_, query):
    user_id = query.from_user.id
    input_token = query.data.split()[1]
    data = user_data.get(user_id, {})
    if 'token' not in data or data['token'] != input_token:
        return await query.answer('Already Used, Generate New One', show_alert=True)
    update_user_ldata(user_id, 'token', str(uuid4()))
    update_user_ldata(user_id, 'time', time())
    await query.answer('Activated Temporary Token!', show_alert=True)
    kb = query.message.reply_markup.inline_keyboard[1:]
    kb.insert(0, [InlineKeyboardButton(BotTheme('ACTIVATED'), callback_data='pass activated')])
    await editReplyMarkup(query.message, InlineKeyboardMarkup(kb))

async def login(_, message):
    if config_dict['LOGIN_PASS'] is None:
        return
    if len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]
        if user_data.get(user_id, {}).get('token', '') == config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('LOGGED_IN'))
        if input_pass != config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('INVALID_PASS'))
        update_user_ldata(user_id, 'token', config_dict['LOGIN_PASS'])
        return await sendMessage(message, BotTheme('PASS_LOGGED'))
    await sendMessage(message, BotTheme('LOGIN_USED'))

async def restart(client, message):
    restart_message = await sendMessage(message, BotTheme('RESTARTING'))
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await delete_all_messages()
    for interval in [QbInterval, Interval]:
        if interval:
            interval[0].cancel()
    await sync_to_async(clean_all)
    proc1 = await create_subprocess_exec('pkill', '-9', '-f', f'gunicorn|{bot_cache["pkgs"][-1]}')
    proc2 = await create_subprocess_exec('python3', 'update.py')
    await gather(proc1.wait(), proc2.wait())
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
    osexecl(executable, executable, "-m", "bot")

async def ping(_, message):
    start_time = monotonic()
    reply = await sendMessage(message, BotTheme('PING'))
    end_time = monotonic()
    await editMessage(reply, BotTheme('PING_VALUE', value=int((end_time - start_time) * 1000)))

async def log(_, message):
    buttons = ButtonMaker()
    user_id = message.from_user.id
    buttons.ibutton(BotTheme('LOG_DISPLAY_BT'), f'wzmlx {user_id} logdisplay')
    buttons.ibutton(BotTheme('WEB_PASTE_BT'), f'wzmlx {user_id} webpaste')
    await sendFile(message, 'log.txt', buttons=buttons.build_menu(1))

async def search_images():
    query_list = config_dict.get('IMG_SEARCH', [])
    if not query_list:
        return
    try:
        total_pages = config_dict.get('IMG_PAGE', 1)
        base_url = "https://www.wallpaperflare.com/search"
        # Use a set to reduce duplicates temporarily
        new_images = set()
        existing_images = set(config_dict.get('IMAGES', []))
        for query in query_list:
            q = query.strip().replace(" ", "+")
            for page in range(1, total_pages + 1):
                url = f"{base_url}?wallpaper={q}&width=1280&height=720&page={page}"
                r = rget(url)
                soup = BeautifulSoup(r.text, "html.parser")
                images = soup.select('img[data-src^="https://c4.wallpaperflare.com/wallpaper"]')
                if not images:
                    LOGGER.info("Maybe Site is Blocked on your Server, Add Images Manually !!")
                for img in images:
                    img_url = img['data-src']
                    if img_url not in existing_images and img_url not in new_images:
                        new_images.add(img_url)
        if new_images:
            config_dict.setdefault('IMAGES', []).extend(new_images)
            config_dict['STATUS_LIMIT'] = 2
            if DATABASE_URL:
                await DbManger().update_config({'IMAGES': config_dict['IMAGES'], 'STATUS_LIMIT': config_dict['STATUS_LIMIT']})
    except Exception as e:
        LOGGER.error(f"An error occurred: {e}")

async def bot_help(client, message):
    buttons = ButtonMaker()
    user_id = message.from_user.id
    buttons.ibutton(BotTheme('BASIC_BT'), f'wzmlx {user_id} guide basic')
    buttons.ibutton(BotTheme('USER_BT'), f'wzmlx {user_id} guide users')
    buttons.ibutton(BotTheme('MICS_BT'), f'wzmlx {user_id} guide miscs')
    buttons.ibutton(BotTheme('O_S_BT'), f'wzmlx {user_id} guide admin')
    buttons.ibutton(BotTheme('CLOSE_BT'), f'wzmlx {user_id} close')
    await sendMessage(message, BotTheme('HELP_HEADER'), buttons.build_menu(2))

async def restart_notification():
    now = datetime.now(timezone(config_dict['TIMEZONE']))

    # Read chat_id and msg_id with low memory usage line by line
    chat_id, msg_id = 0, 0
    if await aiopath.isfile(".restartmsg"):
        async with aiopen(".restartmsg", "r") as f:
            try:
                lines = []
                async for line in f:
                    lines.append(line.strip())
                if len(lines) >= 2:
                    chat_id, msg_id = int(lines[0]), int(lines[1])
            except Exception:
                pass

    async def send_incomplete_task_message(cid, msg):
        try:
            if msg.startswith("⌬ <b><i>Restarted Successfully!</i></b>"):
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=msg, disable_web_page_preview=True)
                await aioremove(".restartmsg")
            else:
                await bot.send_message(chat_id=cid, text=msg, disable_web_page_preview=True, disable_notification=True)
        except Exception as e:
            LOGGER.error(e)

    if INCOMPLETE_TASK_NOTIFIER and DATABASE_URL:
        notifier_dict = await DbManger().get_incomplete_tasks() or {}
        for cid, data in notifier_dict.items():
            # Build messages incrementally rather than one huge string
            msg_chunks = []
            if cid == chat_id:
                header_msg = BotTheme('RESTART_SUCCESS', time=now.strftime('%I:%M:%S %p'), date=now.strftime('%d/%m/%y'), timz=config_dict['TIMEZONE'], version=get_version())
                msg_chunks.append(f"{header_msg}\n\n⌬ <b><i>Incomplete Tasks!</i></b>")
            else:
                msg_chunks.append(BotTheme('RESTARTED') + "\n\n⌬ <b><i>Incomplete Tasks!</i></b>")

            msg_len = len(''.join(msg_chunks).encode())
            for tag, links in data.items():
                chunk = f"\n➲ <b>User:</b> {tag}\n┖ <b>Tasks:</b>"
                for index, link in enumerate(links, start=1):
                    msg_link, source = next(iter(link.items()))
                    chunk += f" {index}. <a href='{source}'>S</a> ->  <a href='{msg_link}'>L</a> |"
                    msg_len += len(chunk.encode())
                    if msg_len > 4000:
                        await send_incomplete_task_message(cid, ''.join(msg_chunks))
                        msg_chunks = []
                        msg_len = len(chunk.encode())
                        chunk = ''
                msg_chunks.append(chunk)
            if msg_chunks:
                await send_incomplete_task_message(cid, ''.join(msg_chunks))

    if await aiopath.isfile(".restartmsg"):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=BotTheme('RESTART_SUCCESS',
                                                      time=now.strftime('%I:%M:%S %p'),
                                                      date=now.strftime('%d/%m/%y'),
                                                      timz=config_dict['TIMEZONE'],
                                                      version=get_version()))
        except Exception as e:
            LOGGER.error(e)
        await aioremove(".restartmsg")

async def log_check():
    leech_ids = config_dict.get('LEECH_LOG_ID', '')
    if not leech_ids:
        return
    bot_id = bot.me.id if bot.me else None
    user_id = user.me.id if user else None

    for chat_str in leech_ids.split():
        chat_id_part, *topic_id = chat_str.split(":")
        try:
            chat_id_int = int(chat_id_part)
        except Exception:
            LOGGER.error(f"Invalid Chat ID format: {chat_str}")
            continue
        try:
            chat = await bot.get_chat(chat_id_int)
        except Exception:
            LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, Make sure the Bot is Added!")
            continue

        try:
            chat_type = chat.type
            bot_member = await chat.get_member(bot_id) if bot_id else None
            user_member = await chat.get_member(user_id) if (user and user_id) else None

            if chat_type == ChatType.CHANNEL:
                if not (bot_member and bot_member.privileges and bot_member.privileges.can_post_messages):
                    LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, Make the Bot is Admin in Channel to Connect!")
                    continue
                if user and not (user_member and user_member.privileges and user_member.privileges.can_post_messages):
                    LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, Make the User is Admin in Channel to Connect!")
                    continue
            elif chat_type == ChatType.SUPERGROUP:
                allowed_statuses = {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}
                if not (bot_member and bot_member.status in allowed_statuses):
                    LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, Make the Bot is Admin in Group to Connect!")
                    continue
                if user and not (user_member and user_member.status in allowed_statuses):
                    LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, Make the User is Admin in Group to Connect!")
                    continue
            LOGGER.info(f"Connected Chat ID : {chat_id_int}")
        except Exception as e:
            LOGGER.error(f"Not Connected Chat ID : {chat_id_int}, ERROR: {e}")

async def main():
    await gather(start_cleanup(), torrent_search.initiate_search_tools(), restart_notification(), search_images(), set_commands(bot), log_check())
    await sync_to_async(start_aria2_listener, wait=False)
    
    bot.add_handler(MessageHandler(start, filters=command(BotCommands.StartCommand) & private))
    bot.add_handler(CallbackQueryHandler(token_callback, filters=regex(r'^pass')))
    bot.add_handler(MessageHandler(login, filters=command(BotCommands.LoginCommand) & private))
    bot.add_handler(MessageHandler(log, filters=command(BotCommands.LogCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(restart, filters=command(BotCommands.RestartCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(ping, filters=command(BotCommands.PingCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(bot_help, filters=command(BotCommands.HelpCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(stats, filters=command(BotCommands.StatsCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    LOGGER.info(f"WZML-X Bot [@{bot_name}] Started!")
    if user:
        LOGGER.info(f"WZ's User [@{user.me.username}] Ready!")
    signal(SIGINT, exit_clean_up)

async def stop_signals():
    if user:
        await gather(bot.stop(), user.stop())
    else:
        await bot.stop()

bot_run = bot.loop.run_until_complete
bot_run(main())
bot_run(idle())
bot_run(stop_signals())
