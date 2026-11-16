"""Point config at the test fixture before any project module imports profile."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["JOBHUNT_CONFIG"] = os.path.join(HERE, "fixture_config.toml")
