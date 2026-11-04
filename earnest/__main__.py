import sys

from .startup import boot

boot(interactive=len(sys.argv) == 1)

if len(sys.argv) == 1:
    from .shell import run
    sys.exit(run())
else:
    from .cli import main
    sys.exit(main())
