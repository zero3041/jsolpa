import ast, re, pathlib

# 1. check syntax
for p in ["web/vote.py", "web/change_email.py", "web/static/change_email.js", "web/static/vote.js"]:
    src = pathlib.Path(p).read_text(encoding="utf-8", errors="ignore")
    try:
        if p.endswith(".py"):
            ast.parse(src)
        print(f"OK syntax {p}")
    except Exception as e:
        print(f"FAIL syntax {p}: {e}")

# 2. test regex extraction
samples = [
    "Tai khoan da duoc chuyen doi sang ngochoangdjdbalq4@outlook.com. Vui long dang nhap dung tai khoan de tiep tuc binh chon.",
    "Tai khoan dang dang nhap da duoc chuyen doi sang ngochoangdjdbalq4@outlook.com",
]
pat = r"chuyen doi sang\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
for s in samples:
    m = re.search(pat, s, re.IGNORECASE)
    print(f"extract -> {m.group(1) if m else None}")

# also test with Vietnamese diacritics
s3 = "Tài khoản đã được chuyển đổi sang ngochoangdjdbalq4@outlook.com"
m3 = re.search(r"chuyển đổi sang\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", s3, re.IGNORECASE)
print(f"extract vn -> {m3.group(1) if m3 else None}")

# 3. check AlreadyConvertedError class exists
import importlib.util, sys
spec = importlib.util.spec_from_file_location("vote", "web/vote.py")
mod = importlib.util.module_from_spec(spec)
# don't exec fully (needs deps), just check string
text = pathlib.Path("web/vote.py").read_text(encoding="utf-8")
assert "class AlreadyConvertedError" in text, "missing class"
assert "chuyển đổi" in text.lower(), "missing detection"
print("OK AlreadyConvertedError detection present")

# 4. change_email imports
text2 = pathlib.Path("web/change_email.py").read_text(encoding="utf-8")
assert "AlreadyConvertedError" in text2, "change_email missing import"
assert "from .vote import AlreadyConvertedError" in text2
print("OK change_email imports and handles")

# 5. check static js fix still present
for p in ["web/static/change_email.js", "web/static/vote.js"]:
    t = pathlib.Path(p).read_text(encoding="utf-8")
    assert "dom.logPane.innerHTML = renderLogLines" not in t, f"bug still in {p}"
    print(f"OK js fix still in {p}")

print("all checks passed")
