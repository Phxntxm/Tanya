import discord
from discord.ext import commands
from glob import glob

import config

intents = discord.Intents(
    guild_messages=True,
    guild_reactions=True,
    guilds=True,
)


class Bot(commands.Bot):
    error_channel = config.error_channel_id

    async def get_context(self, message, *, cls=commands.Context):
        if hasattr(self, "custom_context"):
            return await super().get_context(message, cls=self.custom_context)
        else:
            return await super().get_context(message, cls=cls)


bot = Bot(
    command_prefix=commands.when_mentioned_or(config.prefix),
    intents=intents,
    owner_ids=config.owner_ids,
    help_command=commands.DefaultHelpCommand(
        command_attrs={"name": "commands", "aliases": ["command"]}
    ),
)


for ext in glob("extensions/*.py"):
    bot.load_extension(ext.replace("/", ".")[:-3])


bot.run(config.token)
