from __future__ import annotations

import collections
import time
import typing

import discord
from discord.components import SelectOption

if typing.TYPE_CHECKING:
    from utils.custom_context import Context


class Vote(discord.ui.View):
    def __init__(
        self,
        message: str,
        *,
        timeout: typing.Optional[float] = None,
        yes_label: str = "yes",
        no_label: str = "no",
    ):
        super().__init__(timeout=timeout)
        self._message = message
        self.votes: typing.Dict[int, str] = {}

        self._start_time: typing.Optional[float] = None
        self.yes.label = yes_label
        self.no.label = no_label

    @property
    def time_left(self) -> typing.Optional[float | str]:
        if self._start_time:
            _left = (self.timeout + self._start_time) - time.monotonic()
            return _left if _left > 0 else "No"
        return None

    @property
    def message(self) -> str:
        counter = collections.Counter(self.votes.values())
        if time_left := self.time_left:
            if isinstance(time_left, float):
                msg = f"{time_left:.2f} seconds left\n"
            else:
                msg = f"{time_left} seconds left\n"
        else:
            msg = ""
        msg += " to ".join(f"{value}: {count}" for value, count in counter.items())

        return f"{self._message}\n{msg}"

    async def start(self, channel: discord.abc.Messageable) -> collections.Counter[str]:
        self._start_time = time.monotonic()
        msg = await channel.send(self.message, view=self)

        await super().wait()

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        await msg.edit(view=self)
        return collections.Counter(self.votes.values())

    # @discord.ui.select(
    #     placeholder="l",
    #     options=[
    #         SelectOption(
    #             label="1",
    #             description="1",
    #             value="1",
    #             default=True,
    #         ),
    #         SelectOption(
    #             label="2",
    #             description="2",
    #             value="2",
    #             default=False,
    #         ),
    #     ],
    # )
    # async def choose(self, select: discord.ui.Select, interaction: discord.Interaction):
    #     print(select, interaction)

    @discord.ui.button(style=discord.ButtonStyle.green)
    async def yes(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.votes[interaction.user.id] = self.yes.label
        await interaction.message.edit(content=self.message, view=self)

    @discord.ui.button(style=discord.ButtonStyle.red)
    async def no(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.votes[interaction.user.id] = self.no.label
        await interaction.message.edit(content=self.message, view=self)
