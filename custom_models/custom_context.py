from __future__ import annotations

import asyncio
import traceback
import typing
from contextlib import asynccontextmanager

import asyncpg
import config
import discord
from discord.ext import commands

if typing.TYPE_CHECKING:
    from custom_models import MafiaBot


class Context(commands.Context):
    _error_channel_id = config.error_channel_id
    _error_channel: typing.Optional[discord.TextChannel] = None
    bot: MafiaBot

    @property
    def error_channel(self) -> typing.Optional[discord.TextChannel]:
        if self._error_channel is not None:
            return self._error_channel
        self._error_channel = self.bot.get_channel(self._error_channel_id)
        return self._error_channel

    def create_task(self, *args, **kwargs):
        """A shortcut to creating a task with a callback of logging the error"""
        task = self.bot.loop.create_task(*args, **kwargs)
        task.add_done_callback(self._log_future_error)

        return task

    def _log_future_error(self, future: asyncio.Future):
        # Technically the task housing the task this callback is for is what's
        # usually cancelled, therefore cancelled() doesn't actually catch this case
        try:
            if future.cancelled():
                return
            elif exc := future.exception():
                self.bot.loop.create_task(self.log_error(exc))
        except asyncio.CancelledError:
            return

    async def log_error(self, error: BaseException):
        # Format the error message
        discord.Message
        fmt = f"""
Guild ID: {self.guild.id}
```
{''.join(traceback.format_tb(error.__traceback__)).strip()}
{error.__class__.__name__}: {error}
```
"""
        # If the channel has been set, use it
        if isinstance(self.error_channel, discord.TextChannel):
            await self.error_channel.send(fmt)
        else:
            raise error

    @asynccontextmanager
    async def acquire(self) -> typing.AsyncIterator[asyncpg.Connection]:
        conn = await self.bot.db.acquire()
        try:
            yield conn
        finally:
            await self.bot.db.release(conn)
