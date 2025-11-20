import os


class AtomicWriter:

    def __init__(self, path: str) -> None:
        self.path = path
        self.tmp_path = path + ".tmp"

    def write(self, data: str) -> None:
        with open(self.tmp_path, "w+") as file:
            file.write(data)
            file.flush()
            # os.fsync(file.fileno())
        os.rename(self.tmp_path, self.path)
