import base64, json

s="eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJHdHpVIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJHaWFpIEN1dSBUaGUgR2lvaSJ9LCJwb2ludFBhY2thZ2UiOnsicG9pbnQiOjEsImFtb3VudCI6MH0sInByb21vdGlvbiI6Im4vYSIsInBheW1lbnREYXRlIjoiMTEvMDkvMjAyNiAxODoyNzowOCIsImlwQWRkcmVzcyI6IjI0MDU6NDgwMjpjNjM6ZWNkMDoxOTM4OjQ2ZTk6NDVhYzo3NGJkIiwiY3VycmVudF9wb2ludCI6MTI4MCwidG90YWxfcG9pbnQiOjEyODF9"
print("len", len(s), len(s)%4)
for pad in ["", "=", "==", "==="]:
 try:
  d=base64.b64decode(s+pad).decode()
  print("pad", repr(pad), "ok", d[-50:])
  break
 except Exception as e:
  print("pad", repr(pad), "fail", e)

# try adding one char Q
for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=":
 try:
  d=base64.b64decode(s+c).decode()
  j=json.loads(d)
  print("added",c,"ok",j)
  break
 except: pass
else:
 print("no single char fix")

# Try constructing expected JSON and encoding to see what correct b64 should be
expected={"tenantId":"OQAGl0","tenantName":"Tinh Ha Say Hi","domain":"https://tinhhasayhi.1vote.vn","event":{"id":"EVENT_BXThu","name":"THE GROUP PERFORMANCE ICON"},"product":{"id":"GtzV","productGroupId":"y4KWu","name":"Giai Cuu The Gioi"},"pointPackage":{"point":1,"amount":0},"promotion":"n/a","paymentDate":"11/09/2026 18:27:08","ipAddress":"2405:4802:c63:ecd0:1938:46e9:45ac:74bd","current_point":1280,"total_point":1281}
enc=base64.b64encode(json.dumps(expected, separators=(',',':')).encode()).decode()
print("expected len", len(enc), len(enc)%4)
print(enc)
print("diff len", len(enc)-len(s))
# compare
for i,(a,b) in enumerate(zip(s,enc)):
 if a!=b:
  print("first diff at",i, repr(s[i-5:i+5]), repr(enc[i-5:i+5]))
  break

# try decode user string with url safe? no
import binascii
try:
 print(base64.b64decode(s+"==", validate=False))
except Exception as e: print(e)
