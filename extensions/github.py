from aiohttp import web
import asyncio
from discord.ext import commands, tasks
import json


class Github(commands.Cog):
    def __init__(self, bot):
        self.app = web.Application()
        self.app.add_routes([web.post("/github-push", self.receive_push)])
        self.bot = bot
        self.runner = web.AppRunner(app)
        self.app_runner.start()


    def cog_unload(self):
        asyncio.create_task(self.stop_runner())
        self.app_runner.close()


    async def stop_runner(self):
        await self.runner.cleanup()


    @tasks.loop(count=1)
    async def app_runner(self):
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', 5000)
        await self.site.start()


    async def receive_push(self, request):
        response = await request.json()
        # First pull from github
        proc = await asyncio.create_subprocess_shell(
            "git pull", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        await proc.communicate()
        # Now load/reload/unload based on added/removed/modified
        loaded = set()
        reloaded = set()
        unloaded = set()

        for commit in response["commits"]:
            for c in commit["added"]:
                if not c.startswith("extensions/"):
                    continue
                c = c.replace("/", ".")[:-3]
                self.bot.load_extension(c)
                loaded.add(c)
            for c in commit["removed"]:
                if not c.startswith("extensions/"):
                    continue
                c = c.replace("/", ".")[:-3]
                self.bot.unload_extension(c)
                unloaded.add(c)
            for c in commit["modified"]:
                if not c.startswith("extensions/"):
                    continue
                c = c.replace("/", ".")[:-3]
                self.bot.reload_extension(c)
                reloaded.add(c)

        channel = self.bot.get_channel(840698427755069475)
        message = ""
        loaded = ", ".join(f"`{c}`" for c in loaded)
        unloaded = ", ".join(f"`{c}`" for c in unloaded)
        reloaded = ", ".join(f"`{c}`" for c in reloaded)
        if loaded:
            message += f"Loaded: {loaded}"
        if unloaded:
            message += f"Unloaded: {unloaded}"
        if reloaded:
            message += f"Reloaded: {reloaded}"
        if message:
            await channel.send(message)
        return web.Response(text="Okay")


def setup(bot):
    bot.add_cog(Github(bot))
