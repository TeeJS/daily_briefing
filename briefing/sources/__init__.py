"""Data sources. Each module exposes `fetch()` returning a dict for the renderer.

Every fetch result has a `status` field:
- "ready":  data is real and renderable
- "stub":   section is not yet implemented; renderer shows a placeholder
- "error":  fetch failed; renderer shows the message, briefing still ships

The shape of the rest of the dict is source-specific. See each module.
"""

from typing import Any

SectionResult = dict[str, Any]
