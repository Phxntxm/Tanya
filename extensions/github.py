from aiohttp import web
import asyncio
from discord.ext import commands
import json


class Github(commands.Cog):
    def __init__(self, bot):
        self.app = web.Application()
        self.app.add_routes([web.post("/github-push", self.receive_push)])
        self.bot = bot
        loop = asyncio.get_event_loop()
        # Why the fuck is this private? I'm using it, idc
        self.task = loop.create_task(web._run_app(self.app))

    def cog_unload(self):
        self.task.cancel()

    async def receive_push(self, request):
        response = await request.json()
        # First pull from github
        await asyncio.create_subprocess_shell(
            "git pull", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        # Now load/reload/unload based on added/removed/modified
        loaded = []
        reloaded = []
        unloaded = []

        for commit in response["commits"]:
            for c in commit["added"]:
                if c.startswith("extensions/"):
                    c = c.replace("/", ".")[:-3]
                    self.bot.load_extension(c)
                    loaded.append(c)
            for c in commit["removed"]:
                if c.startswith("extensions/"):
                    c = c.replace("/", ".")[:-3]
                    self.bot.unload_extension(c)
                    unloaded.append(c)
            for c in commit["modified"]:
                if c.startswith("extensions/"):
                    c = c.replace("/", ".")[:-3]
                    self.bot.reload_extension(c)
                    reloaded.append(c)

        channel = self.bot.get_channel(840698427755069475)
        message = ""
        loaded = ", ".join(f"`{c}`" for c in loaded)
        unloaded = ", ".join(f"`{c}`" for c in unloaded)
        reloaded = ", ".join(f"`{c}`" for c in reloaded)
        if loaded:
            message += f"Loaded: {loaded}"
        if unloaded:
            message += f"Loaded: {unloaded}"
        if reloaded:
            message += f"Loaded: {reloaded}"
        if message:
            await channel.send(message)
        return web.Response(text="Okay")


def setup(bot):
    bot.add_cog(Github(bot))
