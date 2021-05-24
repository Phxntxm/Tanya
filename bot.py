import multiprocessing
import typing
from glob import glob

import asyncpg
import discord
from discord.ext import commands

import config
from utils import Context

intents = discord.Intents(
    guild_messages=True,
    guild_reactions=True,
    guilds=True,
)


class MafiaBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.prefix),
            intents=intents,
            owner_ids=config.owner_ids,
            help_command=commands.DefaultHelpCommand(
                command_attrs={"name": "commands", "aliases": ["command"]}
            ),
        )
        self.db: typing.Optional[asyncpg.pool.Pool] = None

    async def get_context(self, message, *, cls=Context):
        return await super().get_context(message, cls=cls)

    async def start(
        self, token: str, *, bot: bool = ..., reconnect: bool = ...
    ) -> None:
        self.db = await asyncpg.create_pool(config.db_uri, min_size=1, max_inactive_connection_lifetime=10)
        return await super().start(token, bot=bot, reconnect=reconnect)


bot = MafiaBot()

if __name__ == "__main__":
    multiprocessing.set_start_method("forkserver")
    for ext in glob("extensions/*.py"):
        bot.load_extension(ext.replace("/", ".")[:-3])

    if getattr(config, "fuck_you_sarc"):
        bot.load_extension("jishaku")

    bot.run(config.token)
