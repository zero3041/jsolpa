import base64, json

extra = "eyJ0ZW5hbnRJZCI6Ik9RQUdsMCIsInRlbmFudE5hbWUiOiJUaW5oIEhhIFNheSBIaSIsImRvbWFpbiI6Imh0dHBzOi8vdGluaGhhc2F5aGkuMXZvdGUudm4iLCJldmVudCI6eyJpZCI6IkVWRU5UX0JYVGh1IiwibmFtZSI6IlRIRSBHUk9VUCBQRVJGT1JNQU5DRSBJQ09OIn0sInByb2R1Y3QiOnsiaWQiOiJSaHZCIiwicHJvZHVjdEdyb3VwSWQiOiJ5NEtXdSIsIm5hbWUiOiJMYXZpZW0ifSwicG9pbnRQYWNrYWdlIjp7InBvaW50IjoxLCJhbW91bnQiOjB9LCJwcm9tb3Rpb24iOiJuL2EiLCJwYXltZW50RGF0ZSI6IjExLzA5LzIwMjYgMTg6MTk6MzYiLCJpcEFkZHJlc3MiOiIyNDA1OjQ4MDI6YzYzOmVjZDA6MTkzODo0NmU5OjQ1YWM6NzRiZCIsImN1cnJlbnRfcG9pbnQiOjQ4NTMsInRvdGFsX3BvaW50Ijo0ODU0fQ=="
data = json.loads(base64.b64decode(extra).decode())
print(json.dumps(data, indent=2, ensure_ascii=False))
print(f"\ncurrent_point={data['current_point']}")
print(f"total_point={data['total_point']}")
print(f"delta={data['total_point']-data['current_point']}")
print(f"pointPackage={data['pointPackage']}")

# check response wrapper
resp = {"remainingFreeVotes":0,"nextVoteTime":"2026-09-11T17:00:00.000Z","nextVoteInSeconds":20423}
print(f"\nremainingFreeVotes={resp['remainingFreeVotes']} -> het luot free")
print(f"nextVoteInSeconds={resp['nextVoteInSeconds']} = {resp['nextVoteInSeconds']/3600:.2f}h")
