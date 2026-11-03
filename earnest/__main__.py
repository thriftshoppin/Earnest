import sys

from .startup import boot

boot()

from .cli import main

sys.exit(main())
