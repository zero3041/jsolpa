import base64, json

datas = {
 "Laviem": "eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJSaHZCIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJMYXZpZW0ifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MTk6MzYiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjQ4NTMsInRvdGFsX3BvaW50Ijo0ODU0fQ==",
 "Xoay Vong": "eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJmMHh3IiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJYb2F5IFZvbmcifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MjU6MDUiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjc0NTQsInRvdGFsX3BvaW50Ijo3NDU1fQ==",
 "Giai Cuu The Gioi": "eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJHdHpVIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJHaWFpIEN1dSBUaGUgR2lvaSJ9LCJwb2ludFBhY2thZ2UiOnsicG9pbnQiOjEsImFtb3VudCI6MH0sInByb21vdGlvbiI6Im4vYSIsInBheW1lbnREYXRlIjoiMTEvMDkvMjAyNiAxODoyNzowOCIsImlwQWRkcmVzcyI6IjI0MDU6NDgwMjpjNjM6ZWNkMDoxOTM4OjQ2ZTk6NDVhYzo3NGJkIiwiY3VycmVudF9wb2lbnQiOjEyODAsInRvdGFsX3BvaW50IjoxMjgxfQ=="
}
orders={"Laviem":"f04ddNAizSom","Xoay Vong":"vGpj261xGCtF","Giai Cuu The Gioi":"dYnuez54FL7d"}
def b64d(s):
 s=s.strip()
 s+= "=" * (-len(s)%4)
 return json.loads(base64.b64decode(s).decode())

for k,v in datas.items():
 d=b64d(v)
 print(f"{k}: id={d['product']['id']} current={d['current_point']} total={d['total_point']} delta={d['total_point']-d['current_point']} date={d['paymentDate']} order={orders[k]}")
 print(json.dumps(d, ensure_ascii=False))
 print()

# ranking
ranking=sorted([(k, b64d(v)['total_point']) for k,v in datas.items()], key=lambda x: -x[1])
print("Ranking:")
for i,(k,pts) in enumerate(ranking,1):
 print(f"{i}. {k}: {pts}")
