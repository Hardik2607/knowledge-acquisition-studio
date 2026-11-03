import json, os, glob
base = "projects/live-youtube"
d = json.load(open(base + "/status.json"))
print("project:", d["project_id"])
print("phase:", d["phase"])
print("runtime files:")
for root, _, files in os.walk(base + "/runtime"):
    for f in files:
        print(" ", os.path.join(root, f))
print("root runtime/inbox:", os.listdir("runtime/inbox") if os.path.isdir("runtime/inbox") else "none")