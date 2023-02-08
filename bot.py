"""bot.py"""
import importlib
import json
import os
from asyncio import sleep
from random import randint
from traceback import format_exception

from aiohttp import ClientSession
from discord import Intents
from discord.ext import commands
from discord.ext.commands import Bot, errors
from lxml.html import fromstring

import utils

config_file = "config.json"
if config_file in os.listdir():
    with open(config_file, 'r', encoding="utf-8") as file:
        for k, v in json.load(file).items():
            if k and k not in os.environ:
                os.environ[k] = v

utils.initiate_db()
bot = Bot(command_prefix=".", case_insensitive=True, intents=Intents.default())
bot.VERSION = "08/02/2023"
bot.config_file = config_file
bot.sessions = {}
bot.should_break_dict = {}
categories = ("Eco", "Mix", "Social", "War", "Info")


async def create_session() -> ClientSession:
    """create session"""
    return ClientSession(headers={"User-Agent": os.environ["headers"]})


async def get_session(server: str) -> ClientSession:
    """get session"""
    if server not in bot.sessions:
        bot.sessions[server] = await create_session()
    return bot.sessions[server]


async def close_session(server: str) -> None:
    """close session"""
    if server in bot.sessions:
        await bot.sessions[server].close()
        del bot.sessions[server]


async def start():
    """start function"""
    await bot.wait_until_ready()
    bot.allies = await utils.find_one("allies", "list", os.environ["nick"])
    bot.enemies = await utils.find_one("enemies", "list", os.environ["nick"])
    for extension in categories:
        bot.load_extension(extension)
    print('Logged in as')
    print(bot.user.name)

    # you should change the following line in all your accounts (except for 1) to
    # `"help": ""` https://github.com/akiva0003/eSim/blob/main/config.json#L9
    # this way the bot will send only one help commands.
    if not await utils.is_helper():
        bot.remove_command("help")

    # restart saved long functions
    for d in (await utils.find_one("auto", "work", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(
            bot.get_command("auto_work"), d["work_sessions"], d["chance_to_skip_work"], nicks=d["nick"]))

    for d in (await utils.find_one("auto", "motivate", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(bot.get_command("auto_motivate"), d["chance_to_skip_a_day"], nicks=d["nick"]))

    for d in (await utils.find_one("auto", "fight", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(
            bot.get_command("auto_fight"), d["nick"], d["restores"], d["battle_id"],
            d["side"], d["wep"], d["food"], d["gift"], d["ticket_quality"], d["chance_to_skip_restore"]))

    for d in (await utils.find_one("auto", "hunt", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(
            bot.get_command("hunt"), d["nick"], d["max_dmg_for_bh"], d["weapon_quality"], d["start_time"],
            d["ticket_quality"], d.get("consume_first", "none")))

    for d in (await utils.find_one("auto", "hunt_battle", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(
            bot.get_command("hunt_battle"), d["nick"], d["link"], d["side"], d["dmg_or_hits_per_bh"],
            d["weapon_quality"], d["food"], d["gift"], d["start_time"]))

    for d in (await utils.find_one("auto", "watch", os.environ['nick'])).values():
        channel = bot.get_channel(int(d["channel_id"]))
        message = await channel.fetch_message(int(d["message_id"]))
        ctx = await bot.get_context(message)
        bot.loop.create_task(ctx.invoke(
            bot.get_command("watch"), d["nick"], d["battle"], d["side"], d["start_time"], d["keep_wall"],
            d["let_overkill"], d["weapon_quality"], d["ticket_quality"], d["consume_first"]))


def should_break(ctx):
    """tells the command if it should stop (after sleep)"""
    server = ctx.channel.name
    cmd = str(ctx.command)
    if server not in bot.should_break_dict:
        bot.should_break_dict[server] = {}
    if cmd not in bot.should_break_dict[server]:
        bot.should_break_dict[server][cmd] = False
    res = bot.should_break_dict[server][cmd]
    if res:
        del bot.should_break_dict[server][cmd]
    return res


async def inner_get_content(link: str, server: str, data=None, return_tree=False, return_type=""):
    """inner get content"""
    method = "get" if data is None else "post"
    if not return_type:
        return_type = "json" if "api" in link else "html"

    for _ in range(5):
        try:
            async with (await get_session(server)).get(link, ssl=True) if method == "get" else \
                    (await get_session(server)).post(link, data=data, ssl=True) as respond:
                if "google.com" in str(respond.url) or respond.status == 403:
                    await sleep(5)
                    continue

                if any(t in str(respond.url) for t in ("notLoggedIn", "error")):
                    raise ConnectionError("notLoggedIn")

                if respond.status == 200:
                    if return_type == "json":
                        try:
                            api = await respond.json(content_type=None)
                        except Exception:
                            await sleep(5)
                            continue
                        if "error" in api:
                            raise ConnectionError(api["error"])
                        return api if "apiBattles" not in link else api[0]
                    try:
                        tree = fromstring(await respond.text(encoding='utf-8'))
                    except Exception:
                        tree = fromstring(await respond.text(encoding='utf-8'))[1:]
                    logged = tree.xpath('//*[@id="command"]')
                    if any("login.html" in x.action for x in logged):
                        raise ConnectionError("notLoggedIn")
                    if isinstance(return_tree, str):
                        return tree, str(respond.url)
                    return tree if return_tree else str(respond.url)
                await sleep(5)
        except Exception as exc:
            if isinstance(exc, ConnectionError):
                raise exc
            await sleep(5)

    raise ConnectionError(link)


async def get_content(link, data=None, return_tree=False, return_type=""):
    """get content"""
    link = link.split("#")[0].replace("http://", "https://")
    server = link.split("https://", 1)[1].split(".e-sim.org", 1)[0]
    nick = utils.my_nick(server)
    url = f"https://{server}.e-sim.org/"
    not_logged_in = False
    tree = None
    try:
        tree = await inner_get_content(link, server, data, return_tree, return_type)
    except ConnectionError as exc:
        if "notLoggedIn" != str(exc):
            raise exc
        not_logged_in = True
    if not_logged_in:
        await close_session(server)

        payload = {'login': nick, 'password': os.environ.get(server + "_pw", os.environ['pw']), "submit": "Login"}
        async with (await get_session(server)).get(url, ssl=True) as _:
            async with (await get_session(server)).post(url + "login.html", data=payload, ssl=True) as r:
                print(r.url)
                if "index.html?act=login" not in str(r.url):
                    raise ConnectionError(f"{nick} - Failed to login {r.url}")
        tree = await inner_get_content(link, server, data, return_tree, return_type)
    if tree is None:
        tree = await inner_get_content(link, server, data, return_tree, return_type)
    return tree


@bot.event
async def on_message(message):
    """Allow other bots to invoke commands"""
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.invoke(ctx)


@bot.command()
async def update(ctx, *, nicks):
    """Updates the code from the source.
    You can also use `.update ALL`"""
    server = ctx.channel.name
    async for nick in utils.get_nicks(server, nicks):
        async with (await get_session(server)).get(
                "https://api.github.com/repos/akiva0003/eSim/git/trees/main") as main:
            for file in (await main.json())["tree"]:
                file_name = file["path"]
                if ".py" not in file_name or file_name == "bot.py":
                    continue
                async with (await get_session(server)).get(
                        "https://raw.githubusercontent.com/akiva0003/eSim/main/{file_name}") as r:
                    with open(file_name, "w", encoding="utf-8", newline='') as f:
                        f.write(await r.text())

        importlib.reload(utils)
        for extension in categories:
            bot.reload_extension(extension)
        await ctx.send(f"**{nick}** updated")


@bot.event
async def on_command_error(ctx, error):
    """on command error"""
    error = getattr(error, 'original', error)
    if isinstance(error, commands.NoPrivateMessage):
        return await ctx.send("ERROR: you can't use this command in a private message!")
    if isinstance(error, (commands.CommandNotFound, errors.CheckFailure)):
        return
    if isinstance(error, (errors.MissingRequiredArgument, errors.BadArgument)):
        if await utils.is_helper():
            await ctx.reply(f"```{''.join(format_exception(type(error), error, error.__traceback__))}```"[:1950])
        return
    last_msg = str(list(await ctx.channel.history(limit=1).flatten())[0].content)
    nick = utils.my_nick(ctx.channel.name)
    error_msg = f"**{nick}** ```{''.join(format_exception(type(error), error, error.__traceback__))}```"[:1950]
    if error_msg != last_msg:
        # Don't send from all users.
        try:
            await ctx.reply(error_msg)
        except Exception:
            await ctx.reply(error)

bot.get_content = get_content
bot.should_break = should_break
if os.environ["TOKEN"] != "PASTE YOUR TOKEN HERE":
    bot.loop.create_task(start())  # startup function
    bot.run(os.environ["TOKEN"])
else:
    print("ERROR: please follow those instructions: https://github.com/akiva0003/eSim#setup")
