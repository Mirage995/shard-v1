import time


class TerminalMemory:
    """
    Tracks recently failed commands to avoid infinite retry loops.
    """

    def __init__(self):
        self.failed_commands = {}

    def register_failure(self, command: str):
        self.failed_commands[command] = time.time()

    def should_block(self, command: str, window=60):
        """
        Block command if it failed recently.
        """
        if command in self.failed_commands:
            last_fail = self.failed_commands[command]

            if time.time() - last_fail < window:
                return True

        return False
