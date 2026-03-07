"""PTY helper for vin-terminal. Wraps zsh in a real PTY with resize support.

Accepts resize commands via OSC escape sequence: \x1b]R;cols;rows\x07
These are intercepted before reaching the shell, and the PTY is resized
so the shell reflows output to the new dimensions.
"""
import os, sys, select, signal, struct, fcntl, termios, pty

def main():
    cols = int(os.environ.get("VIN_TERM_COLS", "80"))
    rows = int(os.environ.get("VIN_TERM_ROWS", "24"))

    master, slave = pty.openpty()

    # Set initial PTY size
    fcntl.ioctl(master, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0))

    pid = os.fork()
    if pid == 0:
        # Child: connect to slave PTY, exec zsh
        os.close(master)
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        if slave > 2:
            os.close(slave)
        os.execvp("/bin/zsh", ["/bin/zsh", "-i", "-l"])

    # Parent: copy between stdin/stdout and master fd
    os.close(slave)

    def resize(c, r):
        fcntl.ioctl(master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", r, c, 0, 0))
        os.kill(pid, signal.SIGWINCH)

    buf = b""
    SEQ_START = b"\x1b]R;"
    SEQ_END = b"\x07"

    try:
        while True:
            rlist, _, _ = select.select([0, master], [], [])

            if 0 in rlist:
                data = os.read(0, 4096)
                if not data:
                    break

                buf += data

                # Extract and handle any resize sequences
                while SEQ_START in buf:
                    idx = buf.index(SEQ_START)
                    end = buf.find(SEQ_END, idx)
                    if end < 0:
                        # Incomplete sequence; flush everything before it
                        if idx > 0:
                            os.write(master, buf[:idx])
                        buf = buf[idx:]
                        break
                    # Send any data before the sequence to the shell
                    if idx > 0:
                        os.write(master, buf[:idx])
                    # Parse cols;rows
                    seq = buf[idx + len(SEQ_START):end]
                    buf = buf[end + 1:]
                    try:
                        parts = seq.split(b";")
                        if len(parts) == 2:
                            resize(int(parts[0]), int(parts[1]))
                    except (ValueError, IndexError):
                        pass
                else:
                    # No more sequences, flush remaining buffer
                    if buf:
                        os.write(master, buf)
                        buf = b""

            if master in rlist:
                try:
                    data = os.read(master, 4096)
                    if not data:
                        break
                    os.write(1, data)
                except OSError:
                    break
    except Exception:
        pass

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass

if __name__ == "__main__":
    main()
