import subprocess
import sys

import pytest


@pytest.mark.integration
def test_installed_package_is_importable_in_fresh_process() -> None:
    command = (
        "import regime_strategy_selector; "
        "print(regime_strategy_selector.__version__)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "0.0.0"
