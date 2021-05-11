import discord
from discord.ext import menus


class MafiaPages(menus.ListPageSource):
    def __init__(self, data, ctx):
        self.ctx = ctx
        super().__init__(data, per_page=5)

    async def format_page(self, menu, entries):
        embed = discord.Embed(
            title="Choose special roles",
            description="Choose the corresponding emote to the role you want to modify, "
            "then provide the amount you want this role to have\n\n",
        )
        embed.description += "\n".join(
            f"{self.ctx.bot.to_keycap(count)} **{role.__name__} - {'Citizens' if role.is_citizen else 'Mafia'}**: {amt}"
            for count, (role, amt) in enumerate(entries)
        )
        return embed


class MafiaMenu(menus.MenuPages):
    amount_of_players = 0
    amount_of_mafia = 0

    @property
    def total_mafia(self):
        return sum([v for k, v in self.source.entries if k.is_mafia])

    @property
    def total_citizens(self):
        return sum([v for k, v in self.source.entries if k.is_citizen])

    @property
    def amount_of_citizens(self):
        return self.amount_of_players - self.amount_of_mafia

    def should_add_reactions(self):
        return True

    def _should_not_paginate(self):
        return not self._source.is_paginating()

    def _should_skip_0(self):
        return len(self._get_pages(self.current_page)) < 1

    def _should_skip_1(self):
        return len(self._get_pages(self.current_page)) < 2

    def _should_skip_2(self):
        return len(self._get_pages(self.current_page)) < 3

    def _should_skip_3(self):
        return len(self._get_pages(self.current_page)) < 4

    def _should_skip_4(self):
        return len(self._get_pages(self.current_page)) < 5

    def _get_pages(self, page_number):
        base = page_number * self.source.per_page
        return self.source.entries[base : base + self.source.per_page]

    @menus.button(
        "0\N{variation selector-16}\N{combining enclosing keycap}",
        skip_if=_should_skip_0,
    )
    async def _0_click_passthrough(self, payload):
        await self.handle_click(payload)

    @menus.button(
        "1\N{variation selector-16}\N{combining enclosing keycap}",
        skip_if=_should_skip_1,
    )
    async def _1_click_passthrough(self, payload):
        await self.handle_click(payload)

    @menus.button(
        "2\N{variation selector-16}\N{combining enclosing keycap}",
        skip_if=_should_skip_2,
    )
    async def _2_click_passthrough(self, payload):
        await self.handle_click(payload)

    @menus.button(
        "3\N{variation selector-16}\N{combining enclosing keycap}",
        skip_if=_should_skip_3,
    )
    async def _3_click_passthrough(self, payload):
        await self.handle_click(payload)

    @menus.button(
        "4\N{variation selector-16}\N{combining enclosing keycap}",
        skip_if=_should_skip_4,
    )
    async def _4_click_passthrough(self, payload):
        await self.handle_click(payload)

    async def handle_click(self, payload):
        # Get the number that was clicked
        num = int(str(payload.emoji)[0])
        role, current_num = self.source.entries[num]
        # Only allow up to how many members can remain
        if role.is_mafia:
            amt_allowed = self.amount_of_mafia - self.total_mafia + current_num
        else:
            amt_allowed = self.amount_of_citizens - self.total_citizens + current_num
        msg = await self.ctx.send(f"How many? 0 - {amt_allowed}")
        answer = await self.ctx.bot.wait_for(
            "message", check=self.ctx.bot.min_max_check(self.ctx, 0, amt_allowed)
        )
        # Delete and set answer
        self.source.entries[num] = (role, int(answer.content))
        await self.ctx.channel.delete_messages([msg, answer])
        # Refresh
        await self.show_page(self.current_page)

    @menus.button(
        "\N{BLACK LEFT-POINTING TRIANGLE}\ufe0f",
        position=menus.First(1),
        skip_if=_should_not_paginate,
    )
    async def go_to_previous_page(self, payload):
        """go to the previous page"""
        await self.show_checked_page(self.current_page - 1)

    @menus.button(
        "\N{BLACK RIGHT-POINTING TRIANGLE}\ufe0f",
        position=menus.Last(0),
        skip_if=_should_not_paginate,
    )
    async def go_to_next_page(self, payload):
        """go to the next page"""
        await self.show_checked_page(self.current_page + 1)

    @menus.button(
        "\N{BLACK SQUARE FOR STOP}\ufe0f",
        position=menus.Last(2),
        skip_if=lambda x: True,
    )
    async def stop_pages(self, payload):
        pass

    @menus.button("\N{WHITE HEAVY CHECK MARK}", position=menus.Last(2))
    async def accept_setings(self, payload):
        self.stop()


def setup(bot):
    bot.MafiaMenu = MafiaMenu
    bot.MafiaPages = MafiaPages


def teardown(bot):
    del bot.MafiaMenu
    del bot.MafiaPages