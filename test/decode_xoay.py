import base64, json

extra="eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJmMHh3IiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJYb2F5IFZvbmcifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MjU6MDUiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjc0NTQsInRvdGFsX3BvaW50Ijo3NDU1fQ=="
d=json.loads(base64.b64decode(extra).decode())
print(json.dumps(d, indent=2, ensure_ascii=False))
print(f"delta={d['total_point']-d['current_point']} point={d['pointPackage']}")
# so sanh voi Laviem truoc
print(f"\nXoay Vong total={d['total_point']} vs Laviem truoc 4854")
print(f"chenh lech={d['total_point']-4854}")
print(f"paymentDate={d['paymentDate']}")
print(f"orderId=vGpj261xGCtF remaining=0 next=20094s")
