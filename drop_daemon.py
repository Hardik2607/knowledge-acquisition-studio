import os, time, glob
base = "projects/live-youtube"
os.makedirs(base + "/runtime/inbox", exist_ok=True)
with open(base + "/runtime/inbox/daemon-test.yaml", "w") as f:
    f.write("project_id: daemon-test\ngoal: daemon smoke test\nsources:\n  - kind: video\n    origin: https://www.youtube.com/watch?v=jNQXAC9IVRw\n    title: Me at the zoo\n    language: en\n")
print("dropped")
time.sleep(90)
for d in ("inbox", "queue", "done", "failed"):
    p = base + "/runtime/" + d
    files = os.listdir(p) if os.path.isdir(p) else []
    print(d, ":", files if files else "(empty)")