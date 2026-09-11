import re
from pathlib import Path

for fname in ["web/static/change_email.js", "web/static/vote.js"]:
    p = Path(fname)
    text = p.read_text(encoding="utf-8")
    # Check fetchLog no longer assigns renderLogLines to innerHTML
    if "dom.logPane.innerHTML = renderLogLines" in text:
        print(f"FAIL {fname}: still has bug")
    else:
        print(f"OK {fname}: bug fixed")
    # Check renderLogLines exists
    assert "function renderLogLines" in text, f"missing renderLogLines in {fname}"
    # Check fetchLog calls renderLogLines without assignment
    m = re.search(r"async function fetchLog.*?renderLogLines\(job, data\.log_lines", text, re.S)
    if m:
        print(f"  fetchLog correctly calls renderLogLines in {fname}")
    else:
        print(f"  FAIL fetchLog not found in {fname}")

# also verify eventista still correct (should not have bug)
p = Path("web/static/eventista.js")
text = p.read_text(encoding="utf-8")
if "dom.logPane.innerHTML = creds + renderLinesInner" in text:
    print("OK eventista.js: correct pattern")
else:
    print("WARN eventista.js pattern changed")

print("done")
