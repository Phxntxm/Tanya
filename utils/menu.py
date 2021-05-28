from __future__ import annotations

import asyncio
import typing


import discord
from discord.ext import menus, commands

from utils import min_max_check, to_keycap

if typing.TYPE_CHECKING:
    from utils import Context


class MafiaPages(menus.ListPageSource):
    def __init__(self, data: typing.List, ctx: Context):
        self.ctx = ctx

        data.sort(key=lambda x: x.id)
        super().__init__(data, per_page=5)

    async def format_page(self, menu: MafiaMenu, entries: typing.List):
        embed = discord.Embed(
            title="Choose special roles",
            description="Choose the corresponding emote to the role you want to modify, "
            "then provide the amount you want this role to have\n\n",
        )
        for count, (role, amt) in enumerate(entries):
            emoji = to_keycap(count)
            role_type = "Unknown"
            if role.is_citizen:
                role_type = "Citizen"
            elif role.is_mafia:
                role_type = "Mafia"
            elif role.is_independent:
                role_type = "Independent"
            embed.description = (
                f"{embed.description}{emoji} **{role.__name__}**({role_type}): {amt}\n"
            )
        return embed


class MafiaMenu(menus.MenuPages):
    amount_of_players = 0
    amount_of_mafia = 0
    ctx: Context

    @property
    def allowed_mafia(self):
        """The amount of mafia roles allowed to add"""
        # Subtract an extra one, because one of them HAS to be Godfather
        return (
            self.amount_of_mafia
            - sum([v for k, v in self.source.entries if k.is_mafia])
            - 1
        )

    @property
    def allowed_non_mafia(self):
        """The amount of non-mafia roles allowed to add"""
        return (
            self.amount_of_players
            - self.amount_of_mafia
            - sum([v for k, v in self.source.entries if not k.is_mafia])
        )

    async def finalize(self, timed_out):
        if timed_out:
            raise asyncio.TimeoutError

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
        index = num + self.source.per_page * self.current_page
        role, current_num = self.source.entries[index]
        # Only allow up to how many members can remain
        if role.is_mafia:
            amt_allowed = self.allowed_mafia + current_num
        else:
            amt_allowed = self.allowed_non_mafia + current_num
        # Make sure to limit to the role's limit
        if role.limit:
            amt_allowed = min(role.limit, amt_allowed)

        # No need to get answer if can't add any anymore
        if not amt_allowed:
            await self.ctx.send("Cannot add any more of that role", delete_after=5)
            return

        msg = await self.ctx.send(f"{role.__name__}: How many? 0 - {amt_allowed}")
        answer = await self.ctx.bot.wait_for(
            "message", check=min_max_check(self.ctx, 0, amt_allowed)
        )
        # Delete and set answer
        self.source.entries[index] = (role, int(answer.content))
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
