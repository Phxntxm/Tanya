import multiprocessing
from glob import glob

import discord
from discord.ext import commands

import config
from utils import Context


class MafiaBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.prefix),
            intents=discord.Intents(
                guild_messages=True,
                guild_reactions=True,
                guilds=True,
            ),
            owner_ids=config.owner_ids,
            help_command=commands.DefaultHelpCommand(
                command_attrs={"name": "commands", "aliases": ["command"]}
            ),
        )

    async def get_context(self, message, *, cls=Context):
        return await super().get_context(message, cls=cls)


bot = MafiaBot()

if __name__ == "__main__":
    multiprocessing.set_start_method("forkserver")
    for ext in glob("extensions/*.py"):
        bot.load_extension(ext.replace("/", ".")[:-3])

    bot.run(config.token)
