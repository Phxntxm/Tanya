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


class TestView1(discord.ui.View):
    def __init__(self, orig, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orig = orig

    @discord.ui.button(label="Sub")
    async def s(self, b, i):
        await i.response.edit_message(view=self.orig)
        self.stop()


class TestView2(discord.ui.View):
    @discord.ui.button(label="Parent")
    async def p(self, b, i):
        view = TestView1(self)
        print(self.children)
        await i.response.edit_message(view=view)
        await view.wait()
        print(self.children)


@bot.command()
async def test2(ctx):
    view = TestView2()
    await ctx.send("test", view=view)


@bot.command()
async def test(ctx):
    from buttons import Join

    await Join(1).start(ctx)


if __name__ == "__main__":
    multiprocessing.set_start_method("forkserver")
    for ext in glob("extensions/*.py"):
        bot.load_extension(ext.replace("/", ".")[:-3])

    if hasattr(config, "fuck_you_sarc"):
        bot.load_extension("jishaku")

    bot.run(config.token)
