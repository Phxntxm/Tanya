from __future__ import annotations

import math
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, TYPE_CHECKING, List, Optional, Type, cast

from discord import ButtonStyle, Interaction, Member, User
import discord
from discord.asset import AssetMixin
from discord.ui import Button, View, button
from utils import Alignment

if TYPE_CHECKING:
    from mafia import Role


@dataclass
class SetupRole:
    role: Type[Role]
    amount: int = 0


class SpecifyAmt(View):
    def __init__(
        self, role: SetupRole, limit: int, orig: Config, timeout: Optional[float] = 180
    ):
        super().__init__(timeout=timeout)

        self.role = role
        self.orig = orig
        self.limit = limit
        self.finished: bool = False
        self.inter: Interaction

        for i in range(limit + 1):
            b = Button(style=ButtonStyle.blurple, label=f"{i}")
            b.callback = partial(self.change_amount, b)
            self.add_item(b)

    async def change_amount(self, b: Button, inter: Interaction):
        self.role.amount = int(cast(int, b.label))
        self.inter = inter
        self.stop()


class RoleButton(Button):
    def __init__(self, role: SetupRole, *args, **kwargs):
        self.role = role
        super().__init__(*args, **kwargs)


class Config(View):
    def __init__(
        self,
        roles: List[Type[Role]],
        author: Member | User,
        timeout: Optional[float] = 180,
    ):
        super().__init__(timeout=timeout)

        self.author = author
        self.finished: bool = False
        self._roles: List[SetupRole] = []

        for role in roles:
            setup_role = SetupRole(role)
            self._roles.append(setup_role)

        self._cur_page = 0
        self._per_page = 5
        self._last_page = math.ceil(len(roles) / self._per_page) - 1
        self.setup_buttons()

    @property
    def entries(self) -> List[SetupRole]:
        """Returns the subset of entries based on the page we're on"""
        return self._roles[
            self._cur_page * self._per_page : (self._cur_page + 1) * self._per_page
        ]

    @property
    def allowed_mafia(self) -> int:
        """The amount of mafia roles allowed to add"""
        # Start with max / 2 - 1
        # / 2 because less than half of town can be mafia, otherwise it would be an automatic win
        # - 1 because one has to be godfather
        # Then subtract all the mafia currently assigned
        return 11 - sum(
            [r.amount for r in self._roles if r.role.alignment is Alignment.mafia]
        )

    @property
    def allowed_non_mafia(self) -> int:
        """The amount of non-mafia roles allowed to add"""
        # 25 townsfolk allowed, -1 because at least one has to be mafia
        return 24 - sum(
            [r.amount for r in self._roles if r.role.alignment is not Alignment.mafia]
        )

    @property
    def min_players(self) -> int:
        """Returns an int representing how many players would be required to play this game"""
        return sum([r.amount for r in self._roles])

    @property
    def send_args(self) -> Dict[str, Any]:
        """Returns the args to be sent when sending/editing"""
        msg = f"Choose your roles. Min players required: {max(3, self.min_players)}"
        if errors := self.errors:
            msg += "\n"
            msg += "\n".join(errors)

            self.confirm.disabled = True
        return {"content": msg, "view": self}

    @property
    def errors(self) -> List[str]:
        """Returns the errors if any"""
        errs: List[str] = []

        maf_amount = sum(
            [r.amount for r in self._roles if r.role.alignment is Alignment.mafia]
        )
        non_maf_amount = sum(
            [r.amount for r in self._roles if r.role.alignment is not Alignment.mafia]
        )

        if maf_amount == 0:
            errs.append("Need at least one mafia!")
        if non_maf_amount / 2 < maf_amount:
            errs.append("Too many mafia! At least half of the town must be non-mafia")
        if non_maf_amount < 2:
            errs.append("Need at least two non-mafia!")
        if non_maf_amount + maf_amount < 3:
            errs.append("Need at least three players total!")

        return errs

    async def start(self, channel: discord.abc.Messageable) -> List[SetupRole] | None:
        await channel.send(**self.send_args)
        await self.wait()

        if self.finished:
            return [r for r in self._roles if r.amount]

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user == self.author:
            return True
        else:
            await inter.response.send_message(
                "You cannot modify this config", ephemeral=True
            )
            return False

    def setup_buttons(self):

        for child in self.children.copy():
            if isinstance(child, RoleButton):
                self.remove_item(child)

        for role in self.entries:
            b = RoleButton(
                role,
                style=ButtonStyle.blurple,
                label=f"{role.role.__name__}: {role.amount}",
            )
            b.callback = partial(self.handle_click, b)
            self.add_item(b)

    def reload_view(self):
        for b in self.children:
            if isinstance(b, RoleButton):
                b.label = f"{b.role.role.__name__}: {b.role.amount}"

        # Don't allow starting if there are any errors
        self.confirm.disabled = len(self.errors) > 0

    async def handle_click(self, b: RoleButton, inter: Interaction):
        role = b.role.role
        amount = b.role.amount

        # Only allow up to how many members can remain
        # add on the role's amount, since we're reassigning
        if role.alignment is Alignment.mafia:
            amt_allowed = self.allowed_mafia + amount
        else:
            amt_allowed = self.allowed_non_mafia + amount
        # Make sure to limit to the role's limit
        if role.limit:
            amt_allowed = min(role.limit, amt_allowed)

        if amt_allowed > 0:
            view = SpecifyAmt(b.role, amt_allowed, self, timeout=10)
            await inter.response.edit_message(
                content=f"{role.__name__}: How many? 0 - {amt_allowed}",
                view=view,
            )
            await view.wait()
            self.reload_view()
            await inter.followup.edit_message(inter.message.id, **self.send_args)
        else:
            await inter.response.send_message(
                "No more allowed of that role", ephemeral=True
            )

    @button(label="Start", style=ButtonStyle.green, row=3, disabled=True)
    async def confirm(self, b: Button, inter: Interaction):
        for child in self.children:
            cast(Button, child).disabled = True

        await inter.response.edit_message(**self.send_args)

        self.finished = True
        self.stop()

    @button(label="Cancel", style=ButtonStyle.red, row=3)
    async def cancel(self, b: Button, inter: Interaction):
        for child in self.children:
            cast(Button, child).disabled = True

        await inter.response.edit_message(**self.send_args)
        self.stop()

    @button(label="Previous Page", style=ButtonStyle.secondary, row=4)
    async def prev(self, b: Button, inter: Interaction):
        self._cur_page -= 1
        if self._cur_page < 0:
            self._cur_page = 0

        self.setup_buttons()
        await inter.response.edit_message(**self.send_args)

    @button(label="Next Page", style=ButtonStyle.secondary, row=4)
    async def next(self, b: Button, inter: Interaction):
        self._cur_page += 1
        if self._cur_page > self._last_page:
            self._cur_page = self._last_page

        self.setup_buttons()
        await inter.response.edit_message(**self.send_args)
