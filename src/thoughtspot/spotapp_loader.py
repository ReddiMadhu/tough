"""
SpotApp Loader — loads ThoughtSpot .zip SpotApp bundles or individual .tml files.
Auto-detects worksheet: vs model: root keys (both treated as models).
"""
import zipfile
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger


class SpotAppLoader:
    """Load a ThoughtSpot SpotApp .zip bundle or individual .tml files."""

    def load_zip(self, zip_path: str) -> Dict[str, Any]:
        """
        Extract and parse all .tml files from a SpotApp zip bundle.

        Returns classified dict:
            { manifest, tables[], models[], liveboards[], answers[], views[] }
        """
        result = self._empty_result()

        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.namelist():
                if entry.endswith("/"):  # skip directories
                    continue

                try:
                    content = zf.read(entry).decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning(f"Skipping binary entry: {entry}")
                    continue

                # Manifest detection
                base = Path(entry).name.lower()
                if base in ("manifest", "manifest.yaml", "manifest.yml"):
                    result["manifest"] = yaml.safe_load(content)
                    continue

                if not entry.endswith(".tml"):
                    continue

                try:
                    parsed = yaml.safe_load(content)
                except yaml.YAMLError as e:
                    logger.error(f"YAML parse error in {entry}: {e}")
                    raise ValueError(f"Failed to parse TML file '{entry}': {e}") from e

                if not parsed or not isinstance(parsed, dict):
                    logger.warning(f"Empty or non-dict TML: {entry}")
                    continue

                self._classify(parsed, result)

        logger.info(
            f"Loaded SpotApp: {len(result['tables'])} tables, "
            f"{len(result['models'])} models, {len(result['liveboards'])} liveboards, "
            f"{len(result['answers'])} answers"
        )
        return result

    def load_tml(self, tml_path: str) -> Dict[str, Any]:
        """Parse a single .tml file and return a classified result."""
        with open(tml_path, "r", encoding="utf-8") as f:
            try:
                parsed = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse TML file '{tml_path}': {e}") from e

        if not parsed or not isinstance(parsed, dict):
            raise ValueError(f"Empty or invalid TML file: {tml_path}")

        result = self._empty_result()
        self._classify(parsed, result)
        return result

    def load_files(self, file_paths: List[str]) -> Dict[str, Any]:
        """Load multiple .tml and/or .zip files into a combined result."""
        combined = self._empty_result()

        for path in file_paths:
            if path.endswith(".zip"):
                data = self.load_zip(path)
            elif path.endswith(".tml"):
                data = self.load_tml(path)
            else:
                logger.warning(f"Skipping unsupported file: {path}")
                continue

            for key in ("tables", "models", "liveboards", "answers", "views"):
                combined[key].extend(data.get(key, []))

            if data.get("manifest") and not combined["manifest"]:
                combined["manifest"] = data["manifest"]

        return combined

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "manifest": None,
            "tables": [],
            "models": [],
            "liveboards": [],
            "answers": [],
            "views": [],
        }

    @staticmethod
    def _classify(parsed: Dict[str, Any], result: Dict[str, Any]):
        """Classify a parsed TML dict into the appropriate bucket."""
        if "table" in parsed:
            result["tables"].append(parsed)
        elif "worksheet" in parsed or "model" in parsed:
            # Auto-detect both worksheet: and model: root keys
            result["models"].append(parsed)
        elif "liveboard" in parsed or "pinboard" in parsed:
            result["liveboards"].append(parsed)
        elif "answer" in parsed:
            result["answers"].append(parsed)
        elif "view" in parsed:
            result["views"].append(parsed)
        else:
            logger.warning(f"Unknown TML root key(s): {list(parsed.keys())}")
