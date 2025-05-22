import os
import sys
import atexit
import platform

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

class SingleInstance:
    def __init__(self, lockfile):
        self.lockfile = os.path.abspath(lockfile)
        self.fp = None

        try:
            self.fp = open(self.lockfile, 'w+')

            if os.name == 'nt':
                # Windows: intenta bloquear el archivo
                try:
                    msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    raise RuntimeError("Otra instancia ya se está ejecutando.")
            else:
                # Unix: intenta obtener un bloqueo exclusivo
                try:
                    fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise RuntimeError("Otra instancia ya se está ejecutando.")

            # Guarda el PID en el archivo para fines informativos
            self.fp.write(str(os.getpid()))
            self.fp.flush()

            # Registra cleanup
            atexit.register(self.cleanup)

        except Exception:
            if self.fp:
                self.fp.close()
            raise

    def cleanup(self):
        try:
            if self.fp:
                self.fp.close()
            if os.path.exists(self.lockfile):
                os.remove(self.lockfile)
        except Exception:
            pass  # Ignorar errores al salir


