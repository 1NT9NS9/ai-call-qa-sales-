import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCENARIOS_PATH = REPO_ROOT / "data" / "demo" / "stage5-demo-scenarios.md"
README_PATH = REPO_ROOT / "README.md"


class Stage5DemoScenarioDocumentationTests(unittest.TestCase):
    def test_stage5_demo_scenarios_file_lists_two_to_three_happy_path_scenarios(
        self,
    ) -> None:
        demo_text = DEMO_SCENARIOS_PATH.read_text(encoding="utf-8")

        scenario_headers = [
            line
            for line in demo_text.splitlines()
            if line.startswith("## Scenario ")
        ]

        self.assertGreaterEqual(len(scenario_headers), 2)
        self.assertLessEqual(len(scenario_headers), 3)
        self.assertIn("API returns the final result", demo_text)
        self.assertIn("Successful webhook delivery", demo_text)
        self.assertTrue(
            "DeliveryEvent" in demo_text and "app.pipeline" in demo_text,
            "expected the Stage 5 demo scenarios to include delivery review and log visibility",
        )

    def test_readme_points_to_stage5_demo_scenarios(self) -> None:
        readme_text = README_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "data/demo/stage5-demo-scenarios.md",
            readme_text,
        )
