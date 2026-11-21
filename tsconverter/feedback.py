"""Send-feedback link: a Google Form (anonymous; users need no account). Stdlib only."""
from __future__ import annotations

import platform
import urllib.parse

# The form's "Get pre-filled link", with the sample answers replaced by {version}
# and {os}. Empty hides every feedback entry point. installer.iss has its own
# copy (FeedbackUrl) for the uninstall survey.
FORM_URL = ("https://docs.google.com/forms/d/e/"
            "1FAIpQLSfWqDBaixb86yIZpCTIWi7qgdc51QH50MmLIRZjrljdROA5mQ/viewform"
            "?usp=pp_url&entry.645232226={version}&entry.841044536={os}")


def form_url(app_version: str) -> str:
    """Feedback form with the app version and OS prefilled ("" while unconfigured)."""
    q = urllib.parse.quote
    return FORM_URL.format(version=q(app_version), os=q(platform.platform()))
