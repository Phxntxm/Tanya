import multiprocessing
from glob import glob

import discord

import config
from utils.custom_bot import MafiaBot

intents = discord.Intents(
    guild_messages=True,
    guild_reactions=True,
    guilds=True,
)


bot = MafiaBot(intents)


if __name__ == "__main__":
    multiprocessing.set_start_method("forkserver")
    for ext in glob("extensions/*.py"):
        bot.load_extension(ext.replace("/", ".")[:-3])

    if hasattr(config, "fuck_you_sarc"):
        bot.load_extension("jishaku")

    bot.run(config.token)
