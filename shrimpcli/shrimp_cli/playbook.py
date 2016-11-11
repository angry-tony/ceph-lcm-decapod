# -*- coding: utf-8 -*-
"""CLI methods for playbook."""


from __future__ import absolute_import
from __future__ import unicode_literals

from shrimp_cli import decorators
from shrimp_cli import main


@main.cli_group
def playbook():
    """Playbook subcommands."""


@decorators.command(playbook)
def get_all(client):
    """Request a list of permissions avaialable in API."""

    return client.get_playbooks()