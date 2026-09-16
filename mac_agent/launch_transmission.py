"""Delay Transmission autostart until the configured external volume is ready."""

import json
import os
import subprocess
import time
from pathlib import Path

from mac_agent.media import DiskUnavailable
from mac_agent.server import volume_guard


def main():
    state = Path(os.environ.get('AGENT_STATE_DIRECTORY', str(Path.home() / 'Library/Application Support/HomeMediaAssistant')))
    config = json.loads((state / 'agent.json').read_text())
    check = volume_guard(config['volume'], config['volume_uuid'])
    while True:
        try:
            check()
            break
        except DiskUnavailable:
            time.sleep(15)
    subprocess.run(['/usr/bin/open', '-W', '-a', str(Path.home() / 'Applications/Transmission.app')], check=True)


if __name__ == '__main__':
    main()
