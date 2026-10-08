"""Private command bootstrap. No child starts until its owner sends GO."""
import subprocess
import sys
import os


def main():
    if sys.stdin.buffer.readline() not in (b'GO\n', b'GO\r\n') or len(sys.argv) < 2:
        return 125
    # Inherit the already assigned Windows Job / POSIX session and output pipe.
    # Children cannot read the owner's private startup handshake.
    try:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        return subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, **options).wait()
    except OSError as exc:
        print(f'Could not start media command: {exc}', file=sys.stderr, flush=True)
        return 126


if __name__ == '__main__':
    raise SystemExit(main())
