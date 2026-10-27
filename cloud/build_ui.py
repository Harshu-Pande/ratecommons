"""Embed ui.html into api/_ui.py (the function bundle only carries Python files reliably)."""
import os
d = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(d, "ui.html")).read()
open(os.path.join(d, "api", "_ui.py"), "w").write('"""Generated from ui.html by build_ui.py."""\nHTML = ' + repr(html) + "\n")
