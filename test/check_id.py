import base64
# from user extraData third, extract id part
# JSON snippet: "product":{"id":"GtzV"
# we saw raw b64 segment "JHdHpVIiwi" vs expected "JHdHpWIiwi"
for s in ["JHdHpVIiwi", "JHdHpWIiwi", "SGd6Vg==", "R3R6Vg==", "Ikd0elYi", "Ikd0elUi"]:
    try:
        print(s, "->", base64.b64decode(s+"==").decode(errors='ignore'))
    except Exception as e:
        print(s, e)
# full decode again with strict
import json
extra="eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJHdHpVIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJHaWFpIEN1dSBUaGUgR2lvaSJ9LCJwb2ludFBhY2thZ2UiOnsicG9pbnQiOjEsImFtb3VudCI6MH0sInByb21vdGlvbiI6Im4vYSIsInBheW1lbnREYXRlIjoiMTEvMDkvMjAyNiAxODoyNzowOCIsImlwQWRkcmVzcyI6IjI0MDU6NDgwMjpjNjM6ZWNkMDoxOTM4OjQ2ZTk6NDVhYzo3NGJkIiwiY3VycmVudF9wb2ludCI6MTI4MCwidG90YWxfcG9pbnQiOjEyODF9"
# try decode with no padding addition
for pad in ["", "=", "=="]:
    try:
        j=json.loads(base64.b64decode(extra+pad).decode())
        print("pad", repr(pad), "id", j['product']['id'], "name", j['product']['name'])
    except Exception as e:
        print("pad", repr(pad), "err", e)
# also try with urlsafe
print("len", len(extra))
print(extra[230:250])
