import fcntl
import os


def get_worker_id():
    lockfile = "worker_id.lock"
    if not os.path.exists(lockfile):
        # Create the file and initialize with 0
        with open(lockfile, "w") as f:
            f.write("0")

    with open(lockfile, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read().strip()
        if content == "":
            worker_id = 0
        else:
            worker_id = int(content)
        # Write back the incremented worker id
        f.seek(0)
        f.truncate()
        f.write(str(worker_id + 1))
        f.flush()
        # Lock is released when file is closed
    return worker_id
