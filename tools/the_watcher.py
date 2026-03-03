import pyinotify
from pathlib import Path

WATCH_DIR = "/data/gandalf/deployments"

class Handler(pyinotify.ProcessEvent):
    def process_IN_CLOSE_WRITE(self, event):
        path = Path(event.pathname)
        if path.is_file():
            print(f"[COMPLETE] File finished writing: {path}")

def watch_directory(path):
    wm = pyinotify.WatchManager()
    mask = pyinotify.IN_CLOSE_WRITE

    handler = Handler()
    notifier = pyinotify.Notifier(wm, handler)

    wm.add_watch(path, mask, rec=True, auto_add=True)

    print(f"Watching {path} for completed files (IN_CLOSE_WRITE)...")
    notifier.loop()


if __name__ == "__main__":
    watch_directory(WATCH_DIR)

