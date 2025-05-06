# bugfix: use same playwright instance in browsergym and pytest
from ..utils import setup_playwright, run_multiple_tests_concurrently