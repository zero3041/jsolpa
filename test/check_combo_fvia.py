import sys
sys.path.insert(0, ".")
from mail_providers import OutlookCombo
import pathlib, ast

# combos test
c1 = "arianni5502071991@outlook.com|rxrdqxxut3|M.C552_BL2.0.U.MsaArtifacts.-Cs!!v6BuEXL3LxarTyW5oNSDgn5dc6b9Neuhd8Ofk3Zq7UK0NzWXG8npB7QPH5WFAwDMwEzt4djwJJzJhCYWQ1pb3x1n4IWICYnxxTtqLeUQ1oj*VzNe6Kkr8xbOF!Qnn8SVS0!4J9JOQz504bmdE4iZAuKKeOd10Z5SpY8Vtq7XBVXGOcIN8VkyjLxqztH5YRj9Wjj!Nx2W279gVQ0XOrJ!a6HQZHg36LhEHCbF*GQQAkBzVTS7S2Szl4E3778kcjIKvkwQunmqX0WLV3g9v8i2oIt89Nu2fLfOpf3ToyaeVIr4WVkTnRWHKxuLFT4SOqWjUrP*AtKosd07MJx6CRlwKga9PfOV9JnG2cOwGTrji3pFuNQ71LnK2V4QMME8pycSSQcDSH6Ckg0uaapfYig$|9e5f94bc-e8a4-4e73-b8be-63364c29d753|arianni5502071991@fviainboxes.com"
# also test with pipe in password
c2 = "test@outlook.com|pass|with|pipe|M.C12345678901234567890|aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
c3 = "test@outlook.com|simplepass|M.C123|bbbbbbbb-cccc-dddd-eeee-ffffffffffff"

for idx, c in enumerate([c1,c2,c3],1):
    try:
        combo = OutlookCombo.parse(c)
        print(f"OK {idx}: email={combo.email} pwd_len={len(combo.password)} rt={combo.refresh_token[:10]}... cid={combo.client_id}")
        print(f"   password={combo.password[:20]}")
    except Exception as e:
        print(f"FAIL {idx}: {e}")

# also test original 4-field still works
c4 = "a@outlook.com|p|M.C123456|11111111-2222-3333-4444-555555555555"
try:
    combo = OutlookCombo.parse(c4)
    print(f"OK 4-field: {combo.email}")
except Exception as e:
    print(f"FAIL 4-field: {e}")

# syntax check
for p in ["mail_providers.py", "web/mail_reader.py", "web/change_email.py"]:
    src = pathlib.Path(p).read_text(encoding="utf-8", errors="ignore")
    try:
        ast.parse(src)
        print(f"OK syntax {p}")
    except Exception as e:
        print(f"FAIL syntax {p}: {e}")
