from __future__ import annotations

from typing import ClassVar

from poetry.console.commands.command import Command
from poetry.plugins import ApplicationPlugin


class MyCommand(Command):
    name = "my-command"

    description = "My Command"

    def handle(self) -> int:
        self.line("my-command called")

        return 0


class MyApplicationPlugin(ApplicationPlugin):
    commands: ClassVar[list[type[Command]]] = [MyCommand]
