import sys
sys.path.insert(0, ".")
import asyncio
from mail_providers import OutlookCombo
from web.mail_reader import parse_combos

combo_line = "arianni5502071991@outlook.com|rxrdqxxut3|M.C552_BL2.0.U.MsaArtifacts.-Cs!!v6BuEXL3LxarTyW5oNSDgn5dc6b9Neuhd8Ofk3Zq7UK0NzWXG8npB7QPH5WFAwDMwEzt4djwJJzJhCYWQ1pb3x1n4IWICYnxxTtqLeUQ1oj*VzNe6Kkr8xbOF!Qnn8SVS0!4J9JOQz504bmdE4iZAuKKeOd10Z5SpY8Vtq7XBVXGOcIN8VkyjLxqztH5YRj9Wjj!Nx2W279gVQ0XOrJ!a6HQZHg36LhEHCbF*GQQAkBzVTS7S2Szl4E3778kcjIKvkwQunmqX0WLV3g9v8i2oIt89Nu2fLfOpf3ToyaeVIr4WVkTnRWHKxuLFT4SOqWjUrP*AtKosd07MJx6CRlwKga9PfOV9JnG2cOwGTrji3pFuNQ71LnK2V4QMME8pycSSQcDSH6Ckg0uaapfYig$|9e5f94bc-e8a4-4e73-b8be-63364c29d753|arianni5502071991@fviainboxes.com"

# test parse
try:
    combo = OutlookCombo.parse(combo_line)
    print(f"parse OK email={combo.email} cid={combo.client_id} rt_prefix={combo.refresh_token[:10]}")
except Exception as e:
    print(f"parse FAIL {e}")
    sys.exit(1)

# test parse_combos via mail_reader (should not raise)
try:
    combos = parse_combos(combo_line)
    print(f"parse_combos OK count={len(combos)}")
except Exception as e:
    print(f"parse_combos FAIL {e}")

# test extra handling: ensure fvia part ignored
if combo.email == "arianni5502071991@outlook.com" and combo.client_id == "9e5f94bc-e8a4-4e73-b8be-63364c29d753":
    print("extra fvia correctly ignored, 5-field support OK")
else:
    print("extra handling wrong")

# check format detection: if cut last field, also OK
combo_line_cut = "|".join(combo_line.split("|")[:4])
try:
    c2 = OutlookCombo.parse(combo_line_cut)
    print(f"cut last field also OK: {c2.email} same={c2.email==combo.email}")
except Exception as e:
    print(f"cut FAIL {e}")

# optional: try mail check with short timeout (may fail network but should not be parse_error)
from web.mail_reader import check_many
async def try_check():
    # Use 10s timeout for refresh? check_many uses default max_messages 10, concurrency 10
    # We limit to 1 combo, but will attempt Graph refresh - may take time
    # Set max_messages=1 to quick
    try:
        res = await asyncio.wait_for(check_many(combo_line, max_messages=1, concurrency=1), timeout=20)
        print(f"check_many result: total={res['total']} parse_error={res['parse_error']} alive={res['alive']} dead={res['dead']} net={res['network_error']}")
        if res['results']:
            r = res['results'][0]
            print(f"  first result status={r['status']} error={r['error'][:200] if r['error'] else None}")
            if res['parse_error'] is None:
                print("SUPPORT FORMAT OK - not parse_error")
            else:
                print("SUPPORT FORMAT FAIL - parse_error present")
        else:
            print("no results")
    except asyncio.TimeoutError:
        print("check_many timeout (network slow) - but parse OK")
    except Exception as e:
        print(f"check_many exception {type(e).__name__}: {e}")

# only run if network available; wrap
try:
    asyncio.run(try_check())
except Exception as e:
    print(f"async run fail {e}")

print("done")
