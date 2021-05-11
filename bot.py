import discord
from discord.ext import commands
from glob import glob

import config

intents = discord.Intents(
    guild_messages=True,
    guild_reactions=True,
    guilds=True,
)
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(">>"),
    intents=intents,
    owner_ids=[115997555619266561, 204306127838642176],
)
bot.error_channel = 840770815498649660


for ext in glob("extensions/*.py"):
    bot.load_extension(ext.replace("/", ".")[:-3])


bot.run(config.token)
