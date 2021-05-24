import asyncio
import traceback
import types
import typing

import config
import discord
from discord.ext import commands

from utils import Cog


class Context(commands.Context):
    error_channel = config.error_channel_id

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

    def reload_module_across_extensions(self, name):
        """Handles hot reloading a module across all the extensions that use it"""
        for key, extension in self.bot.extensions.items():
            # Try to get the module from the extension
            lib = getattr(extension, name, None)

            # If it exists and it's a module, we'll reload
            if isinstance(lib, types.ModuleType):
                # Find the cog that's in this extension and reload it
                for _, cog in self.bot.cogs.items():
                    cog = typing.cast(Cog, cog)
                    if cog.__module__ == key:
                        cog.reload(lib)

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
        # Otherwise if it hasn't been set yet, try to set it
        elif isinstance(self.error_channel, int):
            channel = typing.cast(
                discord.TextChannel,
                await self.bot.fetch_channel(self.error_channel),
            )
            if channel is not None:
                self.error_channel = channel
                await self.error_channel.send(fmt)
