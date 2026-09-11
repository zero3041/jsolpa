import base64, json

def dec(s):
    s=s.strip().replace("\n","")
    # fix padding if needed
    s+= "=" * (-len(s)%4)
    # if remainder 1 after, try trim? but our data is ok
    try:
        return json.loads(base64.b64decode(s).decode())
    except Exception as e:
        # try without added padding
        s2=s.rstrip("=")
        try:
            return json.loads(base64.b64decode(s2).decode())
        except:
            raise e

extras = {
 "Laviem": ("f04ddNAizSom","eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJSaHZCIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJMYXZpZW0ifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MTk6MzYiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjQ4NTMsInRvdGFsX3BvaW50Ijo0ODU0fQ==", 20423),
 "Xoay Vong": ("vGpj261xGCtF","eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJmMHh3IiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJYb2F5IFZvbmcifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MjU6MDUiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjc0NTQsInRvdGFsX3BvaW50Ijo3NDU1fQ==", 20094),
 "Giai Cuu The Gioi": ("dYnuez54FL7d","eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJHdHpVIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJHaWFpIEN1dSBUaGUgR2lvaSJ9LCJwb2ludFBhY2thZ2UiOnsicG9pbnQiOjEsImFtb3VudCI6MH0sInByb21vdGlvbiI6Im4vYSIsInBheW1lbnREYXRlIjoiMTEvMDkvMjAyNiAxODoyNzowOCIsImlwQWRkcmVzcyI6IjI0MDU6NDgwMjpjNjM6ZWNkMDoxOTM4OjQ2ZTk6NDVhYzo3NGJkIiwiY3VycmVudF9wb2ludCI6MTI4MCwidG90YWxfcG9pbnQiOjEyODF9", 19971),
}

rows=[]
for name,(oid,extra,nexts) in extras.items():
 d=dec(extra)
 rows.append((name, d['product']['id'], d['current_point'], d['total_point'], d['total_point']-d['current_point'], d['paymentDate'], oid, nexts))

# sort by total desc
rows_sorted=sorted(rows, key=lambda x: -x[3])
print("| # | Bài | productId | current | total | + | orderId | paymentDate | nextVoteIn |")
print("|---|-----|-----------|---------|-------|---|---------|-------------|------------|")
for i,r in enumerate(rows_sorted,1):
 print(f"| {i} | {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[6]} | {r[5]} | {r[7]}s |")

print("\nKiem tra:")
for r in rows:
 print(f"{r[0]}: {r[2]} -> {r[3]} = +{r[4]} (pointPackage 1, amount 0) OK")
