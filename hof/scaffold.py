"""Public scaffolding API.

``get_project_files`` is the single source of truth for the file layout of a
new hof project.  It is consumed by:

* ``hof new project`` — writes files to local disk
* hof-os ``project_scaffold_repo`` — pushes files to GitHub via the Trees API
"""

from hof.cli.commands.new import get_project_files

__all__ = ["get_project_files"]
